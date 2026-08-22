"""Tìm kiếm web — đường dữ liệu ra ngoài thứ hai của hệ thống (E2 trong spec §7.1).

Input:  chuỗi truy vấn.
Output: danh sách `SearchResult` (tiêu đề, URL, đoạn trích).

Hai ràng buộc nghiệp vụ:
    - Tối đa 5–8 truy vấn mỗi lần nghiên cứu (CLAUDE.md) — quản bằng `QueryBudget`,
      không tin vào việc gọi hàm cho đúng.
    - Truy vấn CÓ CHỨA tên khách hàng, nên phải đi qua cửa egress để hồ sơ mật được
      hỏi ý kiến trước và mọi truy vấn đều vào nhật ký.

Bị chặn hoặc mất mạng thì trả về KẾT QUẢ MỘT PHẦN kèm ghi chú, không làm hỏng cả lần chạy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.config import settings
from backend.security import egress

# Đoạn trích dài hơn mức này bị cắt — nhiều kết quả nhân lên sẽ vượt trần payload egress.
MAX_SNIPPET_CHARS = 500
# Số lần thử lại khi bị giới hạn tần suất, kèm chờ tăng dần.
SEARCH_RETRIES = 2


class SearchBudgetExceeded(RuntimeError):
    """Đã dùng hết hạn mức truy vấn cho lần nghiên cứu này."""


class SearchUnavailable(RuntimeError):
    """Không tìm kiếm được: mất mạng hoặc bị công cụ tìm kiếm chặn."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    query: str

    def as_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "query": self.query,
        }


@dataclass
class QueryBudget:
    """Đếm và chặn cứng số truy vấn của một lần nghiên cứu."""

    limit: int = field(default_factory=lambda: settings.max_search_queries)
    used: int = 0
    queries: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def consume(self, query: str) -> None:
        if self.remaining <= 0:
            raise SearchBudgetExceeded(
                f"Đã dùng hết {self.limit} truy vấn cho lần nghiên cứu này. "
                "Đây là hạn mức để không vượt giới hạn miễn phí."
            )
        self.used += 1
        self.queries.append(query)


def search_web(
    query: str,
    *,
    workspace_id: int | None,
    budget: QueryBudget,
    module: str = "research.search",
    max_results: int | None = None,
) -> list[SearchResult]:
    """Chạy một truy vấn tìm kiếm. Ném `ConsentRequired` nếu hồ sơ mật chưa đồng ý."""
    query = query.strip()
    if not query:
        return []

    limit = max_results or settings.search_results_per_query

    request = egress.EgressRequest(
        module=module,
        destination="search",
        payload_text=query,
        summary=f"Truy vấn tìm kiếm: {query[:120]}",
        workspace_id=workspace_id,
        endpoint="duckduckgo",
    )

    # Cửa egress chạy TRƯỚC khi tính vào hạn mức: bị chặn vì chưa đồng ý thì
    # không được trừ hạn mức của chuyên gia.
    with egress.egress(request):
        budget.consume(query)

        from ddgs import DDGS

        last_error: Exception | None = None
        for attempt in range(SEARCH_RETRIES + 1):
            try:
                with DDGS() as client:
                    raw = client.text(query, max_results=limit, region="wt-wt")
                break
            except Exception as exc:
                last_error = exc
                if attempt < SEARCH_RETRIES:
                    time.sleep(1.5 * (attempt + 1))  # giảm tốc rồi thử lại
        else:
            raw = None

        if raw is None:
            raise SearchUnavailable(
                "Không tìm kiếm được trên web — có thể mất mạng hoặc công cụ tìm kiếm "
                f"đang giới hạn tần suất ({type(last_error).__name__}). "
                "Kết quả đã thu được vẫn giữ nguyên."
            )

    results: list[SearchResult] = []
    for item in raw or []:
        url = str(item.get("href") or "").strip()
        if not url:
            continue
        body = str(item.get("body") or "").strip()
        results.append(
            SearchResult(
                title=str(item.get("title") or url)[:250],
                url=url,
                snippet=body[:MAX_SNIPPET_CHARS],
                query=query,
            )
        )
    return results


def search_many(
    queries: list[str],
    *,
    workspace_id: int | None,
    budget: QueryBudget,
    module: str = "research.search",
    on_progress: object | None = None,
) -> tuple[list[SearchResult], list[str]]:
    """Chạy nhiều truy vấn. Trả về (kết quả gộp, danh sách ghi chú về sự cố).

    Một truy vấn hỏng không làm hỏng các truy vấn còn lại — đúng nguyên tắc
    "trả về kết quả một phần thay vì hỏng cả lần chạy" (spec edge case §4.4).
    """
    collected: list[SearchResult] = []
    notes: list[str] = []
    seen_urls: set[str] = set()

    for index, query in enumerate(queries, start=1):
        if budget.remaining <= 0:
            notes.append(
                f"Dừng ở truy vấn {index}/{len(queries)} vì đã hết hạn mức "
                f"{budget.limit} truy vấn."
            )
            break

        try:
            results = search_web(
                query,
                workspace_id=workspace_id,
                budget=budget,
                module=module,
            )
        except SearchBudgetExceeded as exc:
            notes.append(str(exc))
            break
        except SearchUnavailable as exc:
            notes.append(f"Truy vấn '{query[:60]}' thất bại: {exc}")
            continue

        for result in results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            collected.append(result)

        if callable(on_progress):
            on_progress(index, len(queries), query, len(results))

    return collected, notes
