"""Research Agent: lập kế hoạch truy vấn → tìm kiếm → dựng hồ sơ khách hàng/đối tác.

Input:  tên khách hàng, tên đối tác, chủ đề buổi làm việc (+ ngành, ghi chú).
Output: `ResearchOutcome` gồm hồ sơ từng bên, mỗi TRƯỜNG kèm URL nguồn riêng.

Không dùng LangChain/LangGraph (xem CLAUDE.md): vòng lặp tuần tự tự viết, ba bước rõ ràng,
mọi lệnh gọi ra ngoài đi qua `security.egress`. Đơn giản hơn và kiểm soát được.

Ba ràng buộc nghiệp vụ:
    A2.4  — mỗi thông tin phải có ít nhất một URL nguồn mở được
    A2.5  — thông tin không xác minh được phải đánh dấu rõ, tách khỏi thông tin có nguồn
    A2.15 — không tìm thấy thì nói không tìm thấy, KHÔNG sinh hồ sơ bịa
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Literal

from pydantic import Field

from backend.config import settings
from backend.db import get_conn
from backend.research.search import QueryBudget, SearchResult, search_many
from backend.security import llm
from backend.security.llm import LLMSchema

# Các trường hồ sơ, khớp bảng ở spec §2.2. Khoá cố định để giao diện hiển thị nhất quán.
FIELD_LABELS: dict[str, str] = {
    "official_names": "Tên chính thức & tên gọi khác",
    "industry": "Ngành nghề / lĩnh vực",
    "size": "Quy mô",
    "products": "Sản phẩm / dịch vụ / chương trình chính",
    "recent_news": "Tin tức liên quan gần đây",
    "topic_context": "Bối cảnh liên quan chủ đề",
    "cooperation_history": "Lịch sử hợp tác với đối tác",
    "interpreter_notes": "Ghi chú cho phiên dịch",
}

ProgressFn = Callable[[str], None]


# ============================== Schema output của LLM ==============================


class QueryPlanOut(LLMSchema):
    queries: list[str] = Field(
        description=(
            "Danh sách truy vấn tìm kiếm, mỗi truy vấn một dòng. Trộn cả tiếng Việt và "
            "tiếng Anh vì tổ chức nước ngoài thường có thông tin bằng tiếng Anh. "
            "Bám sát tên tổ chức và chủ đề buổi làm việc."
        )
    )
    reasoning: str = Field(description="Một câu giải thích chiến lược tìm kiếm")


class ProfileFieldOut(LLMSchema):
    field_key: str = Field(description=f"Một trong: {', '.join(FIELD_LABELS)}")
    value: str = Field(description="Nội dung, viết bằng tiếng Việt, ngắn gọn và cụ thể")
    source_urls: list[str] = Field(
        description=(
            "URL các nguồn thực sự chứa thông tin này, lấy nguyên văn từ danh sách nguồn "
            "được cung cấp. Danh sách RỖNG nếu đây là suy luận của bạn."
        )
    )
    is_inference: bool = Field(
        description="True nếu đây là suy luận của bạn chứ không đọc được trực tiếp từ nguồn"
    )


class EntityProfileOut(LLMSchema):
    entity_name: str
    entity_role: Literal["client", "partner"]
    fields: list[ProfileFieldOut]


class ProfileBundleOut(LLMSchema):
    entities: list[EntityProfileOut]
    not_found_notes: list[str] = Field(
        description=(
            "Những gì KHÔNG tìm được thông tin công khai. Ghi rõ thay vì đoán. "
            "Ví dụ: 'Không tìm thấy số nhân viên của tổ chức X'."
        )
    )
    ambiguity_warning: str = Field(
        description=(
            "Nếu tên tổ chức trùng với nhiều đơn vị khác nhau, nêu các khả năng để chuyên gia "
            "tự chọn. Chuỗi rỗng nếu không nhập nhằng. TUYỆT ĐỐI không tự chọn một bên rồi "
            "coi như chắc chắn."
        )
    )


# ============================== Kết quả trả về ==============================


@dataclass
class ProfileField:
    field_key: str
    label: str
    value: str
    source_urls: list[str]
    is_inference: bool


@dataclass
class EntityProfile:
    entity_name: str
    entity_role: str
    fields: list[ProfileField]


@dataclass
class ResearchOutcome:
    research_run_id: int
    entities: list[EntityProfile] = field(default_factory=list)
    queries_used: list[str] = field(default_factory=list)
    n_sources: int = 0
    not_found_notes: list[str] = field(default_factory=list)
    ambiguity_warning: str = ""
    warnings: list[str] = field(default_factory=list)
    status: str = "done"


# ============================== Bước 1: lập kế hoạch truy vấn ==============================

PLAN_SYSTEM = """\
Bạn giúp một chuyên gia phiên dịch Việt–Anh chuẩn bị hồ sơ trước buổi dịch.
Nhiệm vụ: soạn các truy vấn tìm kiếm web để hiểu rõ các bên tham gia và chủ đề buổi làm việc.

Nguyên tắc:
- Truy vấn phải CỤ THỂ, gắn với tên tổ chức và chủ đề. Tránh truy vấn chung chung.
- Trộn tiếng Việt và tiếng Anh: tổ chức nước ngoài thường có thông tin tiếng Anh, còn hoạt
  động tại Việt Nam lại thường được đưa tin bằng tiếng Việt.
- Ưu tiên: tổ chức đó là ai và làm gì · quy mô và lĩnh vực · hoạt động tại Việt Nam ·
  tin tức gần đây liên quan chủ đề · lịch sử hợp tác giữa các bên.
- Không soạn nhiều hơn số truy vấn được phép.
Trả về JSON thuần đúng schema."""


def plan_queries(
    client_name: str,
    partner_names: list[str],
    topic: str,
    industry: str | None,
    extra_notes: str | None,
    workspace_id: int | None,
    max_queries: int,
) -> tuple[list[str], str]:
    partners = ", ".join(partner_names) if partner_names else "(không nêu)"
    prompt = (
        f"KHÁCH HÀNG: {client_name}\n"
        f"ĐỐI TÁC: {partners}\n"
        f"CHỦ ĐỀ BUỔI LÀM VIỆC: {topic}\n"
        f"NGÀNH/LĨNH VỰC: {industry or '(không nêu)'}\n"
        f"GHI CHÚ THÊM: {extra_notes or '(không có)'}\n\n"
        f"Soạn TỐI ĐA {max_queries} truy vấn tìm kiếm."
    )
    result = llm.generate_json(
        module="research.plan",
        prompt=prompt,
        schema=QueryPlanOut,
        workspace_id=workspace_id,
        system_instruction=PLAN_SYSTEM,
        temperature=0.4,
        summary=f"Lập kế hoạch truy vấn cho: {client_name} / {topic[:60]}",
        tier="light",
    )
    queries = [q.strip() for q in result.queries if q.strip()][:max_queries]
    return queries, result.reasoning


# ============================== Bước 3: tổng hợp hồ sơ ==============================

PROFILE_SYSTEM = f"""\
Bạn tổng hợp hồ sơ các bên tham gia một buổi dịch, dựa TRÊN CÁC NGUỒN WEB được cung cấp.

Quy tắc bắt buộc:
1. Mỗi trường thông tin phải kèm source_urls lấy NGUYÊN VĂN từ danh sách nguồn. Không được
   tự bịa URL, không được sửa URL.
2. Nếu một thông tin là suy luận của bạn chứ không đọc được từ nguồn: đặt is_inference=true
   và để source_urls rỗng. Thà ghi là suy luận còn hơn gán nguồn sai.
3. KHÔNG tìm thấy thông tin công khai thì ghi vào not_found_notes. TUYỆT ĐỐI KHÔNG đoán ra
   số nhân viên, doanh thu, năm thành lập hay bất kỳ con số nào.
4. Nếu các nguồn nói về nhiều tổ chức KHÁC NHAU cùng tên, ghi vào ambiguity_warning và nêu
   các khả năng — để chuyên gia tự chọn, không tự chọn hộ.
5. Nguồn nói trái ngược nhau thì nêu cả hai kèm nguồn của từng bên, đừng chọn một bên.
6. Viết value bằng tiếng Việt, ngắn gọn, cụ thể. Với "recent_news" thì kèm mốc thời gian.
7. Trường interpreter_notes: cách đọc tên riêng, tên viết tắt hay dùng, lưu ý nghi thức/văn hoá.

Các khoá field_key được dùng: {', '.join(FIELD_LABELS)}
Trả về JSON thuần đúng schema."""


def _format_sources(results: list[SearchResult]) -> str:
    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        lines.append(
            f"[Nguồn {index}]\n"
            f"URL: {item.url}\n"
            f"Tiêu đề: {item.title}\n"
            f"Trích: {item.snippet}"
        )
    return "\n\n".join(lines)


def build_profiles(
    client_name: str,
    partner_names: list[str],
    topic: str,
    results: list[SearchResult],
    workspace_id: int | None,
) -> ProfileBundleOut:
    partners = ", ".join(partner_names) if partner_names else "(không nêu)"
    prompt = (
        f"CÁC NGUỒN WEB TÌM ĐƯỢC:\n\n{_format_sources(results)}\n\n"
        f"---\n\n"
        f"KHÁCH HÀNG cần dựng hồ sơ: {client_name}\n"
        f"ĐỐI TÁC cần dựng hồ sơ: {partners}\n"
        f"CHỦ ĐỀ BUỔI LÀM VIỆC: {topic}\n\n"
        "Dựng hồ sơ cho khách hàng (entity_role='client') và cho từng đối tác "
        "(entity_role='partner'). Chỉ dùng thông tin trong các nguồn trên."
    )
    return llm.generate_json(
        module="research.profile",
        prompt=prompt,
        schema=ProfileBundleOut,
        workspace_id=workspace_id,
        system_instruction=PROFILE_SYSTEM,
        temperature=0.25,
        summary=f"Tổng hợp hồ sơ: {client_name} ({len(results)} nguồn)",
    )


# ============================== Lưu vào cơ sở dữ liệu ==============================


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Trạng thái liên kết. Phân biệt "chặn kiểm tự động" với "chết thật" là quan trọng:
# đo thực tế trên bộ LDSC, Wikipedia và thuvienphapluat.vn đều trả 403 cho request tự
# động nhưng mở bằng trình duyệt hoàn toàn bình thường. Gán nhãn "chết" cho chúng sẽ
# khiến chuyên gia mất tin vào nguồn tốt — sai còn tệ hơn không kiểm.
LinkStatus = Literal["ok", "blocked", "dead", "unchecked"]


def check_urls_reachable(urls: set[str], timeout: float = 8.0) -> dict[str, str]:
    """Kiểm nhanh từng URL, trả về {url: 'ok' | 'blocked' | 'dead'}.

        ok      — mở được bình thường (2xx/3xx)
        blocked — server từ chối kiểm tự động (401/403/429), nhưng trình duyệt vẫn mở được
        dead    — không tồn tại (404/410) hoặc không kết nối được (DNS/timeout)

    Không tính là egress mới: chỉ mở lại đúng các URL mà công cụ tìm kiếm đã trả về,
    không gửi thêm dữ liệu nào của hồ sơ ra ngoài.
    """
    import concurrent.futures

    import httpx

    def classify(status_code: int) -> str:
        """Phân loại theo mức độ CHẮC CHẮN, không liệt kê mã lỗi.

        Server có phản hồi nghĩa là tên miền còn sống — chỉ 404/410 mới khẳng định được
        trang đã mất. Mọi mã khác là "không kiểm được", vì mỗi trang chặn bot một kiểu:
        đo thực tế trên bộ LDSC — Wikipedia 403, LinkedIn 999, Facebook 400.
        Chỉ khi không kết nối được (DNS/timeout) mới kết luận là chết.
        """
        if status_code < 400:
            return "ok"
        if status_code in (404, 410):
            return "dead"
        return "blocked"

    def probe(url: str) -> tuple[str, str]:
        headers = {"User-Agent": _BROWSER_UA}
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.head(url, headers=headers)
                # Nhiều trang chặn HEAD nhưng vẫn cho GET — thử lại trước khi kết luận.
                if response.status_code >= 400:
                    response = client.get(url, headers=headers)
                return url, classify(response.status_code)
        except Exception:
            return url, "dead"

    if not urls:
        return {}
    statuses: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for url, status in pool.map(probe, urls):
            statuses[url] = status
    return statuses


def _save_outcome(
    run_id: int,
    workspace_id: int,
    bundle: ProfileBundleOut,
    valid_urls: set[str],
    url_status: dict[str, str] | None = None,
) -> list[EntityProfile]:
    """Lưu hồ sơ, GIỮ NGUYÊN các trường chuyên gia đã sửa tay (spec A2.12)."""
    entities: list[EntityProfile] = []

    with get_conn() as conn:
        for entity in bundle.entities:
            # Các trường chuyên gia đã chỉnh của lần chạy trước — không được ghi đè.
            edited = {
                str(row["field_key"])
                for row in conn.execute(
                    """
                    SELECT f.field_key FROM profile_fields f
                    JOIN profiles p ON p.id = f.profile_id
                    WHERE p.workspace_id = ? AND p.entity_name = ? AND f.is_expert_edited = 1
                    """,
                    (workspace_id, entity.entity_name),
                ).fetchall()
            }

            profile_id = int(
                conn.execute(
                    """
                    INSERT INTO profiles (workspace_id, research_run_id, entity_name, entity_role)
                    VALUES (?, ?, ?, ?)
                    """,
                    (workspace_id, run_id, entity.entity_name, entity.entity_role),
                ).lastrowid
                or 0
            )

            saved_fields: list[ProfileField] = []
            for item in entity.fields:
                if item.field_key in edited:
                    continue
                if not item.value.strip():
                    continue

                # Chỉ giữ URL thật sự có trong kết quả tìm kiếm — chặn URL do mô hình bịa.
                urls = [u.strip() for u in item.source_urls if u.strip() in valid_urls]
                verified = bool(urls) and not item.is_inference

                field_id = int(
                    conn.execute(
                        """
                        INSERT INTO profile_fields (profile_id, field_key, value, is_verified)
                        VALUES (?, ?, ?, ?)
                        """,
                        (profile_id, item.field_key, item.value.strip(), int(verified)),
                    ).lastrowid
                    or 0
                )
                for url in urls:
                    conn.execute(
                        "INSERT INTO profile_sources (profile_field_id, url, reachable) VALUES (?, ?, ?)",
                        (field_id, url, (url_status or {}).get(url, "unchecked")),
                    )

                saved_fields.append(
                    ProfileField(
                        field_key=item.field_key,
                        label=FIELD_LABELS.get(item.field_key, item.field_key),
                        value=item.value.strip(),
                        source_urls=urls,
                        is_inference=item.is_inference or not urls,
                    )
                )

            entities.append(
                EntityProfile(
                    entity_name=entity.entity_name,
                    entity_role=entity.entity_role,
                    fields=saved_fields,
                )
            )
    return entities


# ============================== Điểm vào ==============================


def run_research(
    workspace_id: int,
    client_name: str,
    partner_names: list[str],
    topic: str,
    industry: str | None = None,
    extra_notes: str | None = None,
    engagement_id: int | None = None,
    on_progress: ProgressFn | None = None,
) -> tuple[ResearchOutcome, list[SearchResult]]:
    """Chạy trọn một lần nghiên cứu. Trả về (kết quả, các nguồn web) để trích thuật ngữ tiếp."""

    def report(message: str) -> None:
        if on_progress:
            on_progress(message)

    budget = QueryBudget(limit=settings.max_search_queries)

    with get_conn() as conn:
        run_id = int(
            conn.execute(
                """
                INSERT INTO research_runs
                    (workspace_id, engagement_id, client_name, partner_names, topic,
                     industry, extra_notes, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
                """,
                (
                    workspace_id,
                    engagement_id,
                    client_name,
                    json.dumps(partner_names, ensure_ascii=False),
                    topic,
                    industry,
                    extra_notes,
                ),
            ).lastrowid
            or 0
        )

    outcome = ResearchOutcome(research_run_id=run_id)

    try:
        # --- Bước 1: lập kế hoạch ---
        report("Lập kế hoạch tìm kiếm…")
        queries, reasoning = plan_queries(
            client_name, partner_names, topic, industry, extra_notes,
            workspace_id, budget.limit,
        )
        report(f"Đã lập {len(queries)} truy vấn · {reasoning[:110]}")

        # --- Bước 2: tìm kiếm ---
        def progress(index: int, total: int, query: str, n: int) -> None:
            report(f"[{index}/{total}] \"{query[:70]}\" … {n} kết quả")

        results, search_notes = search_many(
            queries, workspace_id=workspace_id, budget=budget, on_progress=progress
        )
        outcome.warnings.extend(search_notes)
        outcome.queries_used = list(budget.queries)
        outcome.n_sources = len(results)

        if not results:
            outcome.status = "partial"
            outcome.not_found_notes.append(
                f"Không tìm thấy nguồn web nào cho '{client_name}'. Thử nhập tên đầy đủ, "
                "website, hoặc quốc gia của tổ chức để thu hẹp tìm kiếm."
            )
            _finish(run_id, outcome, budget)
            return outcome, []

        # --- Bước 3: tổng hợp ---
        report(f"Tổng hợp hồ sơ từ {len(results)} nguồn…")
        bundle = build_profiles(client_name, partner_names, topic, results, workspace_id)

        valid_urls = {r.url for r in results}

        # Chỉ kiểm những URL thực sự được LLM trích dẫn, không kiểm cả 55 nguồn.
        cited_urls = {
            u.strip()
            for entity in bundle.entities
            for item in entity.fields
            for u in item.source_urls
            if u.strip() in valid_urls
        }
        report(f"Kiểm {len(cited_urls)} liên kết nguồn có mở được không…")
        url_status = check_urls_reachable(cited_urls)
        n_dead = sum(1 for s in url_status.values() if s == "dead")
        n_blocked = sum(1 for s in url_status.values() if s == "blocked")
        if n_dead:
            outcome.warnings.append(
                f"{n_dead}/{len(url_status)} liên kết nguồn không truy cập được (trang đã đổi "
                "hoặc tạm sập) — đã đánh dấu 'link chết' để bạn không mất thời gian bấm vào."
            )
        if n_blocked:
            outcome.warnings.append(
                f"{n_blocked}/{len(url_status)} liên kết chặn kiểm tự động nhưng MỞ BẰNG "
                "TRÌNH DUYỆT VẪN ĐƯỢC (ví dụ Wikipedia, thuvienphapluat.vn). "
                "Đây không phải link chết."
            )

        outcome.entities = _save_outcome(
            run_id, workspace_id, bundle, valid_urls, url_status
        )
        outcome.not_found_notes.extend(bundle.not_found_notes)
        outcome.ambiguity_warning = bundle.ambiguity_warning.strip()
        outcome.status = "partial" if search_notes else "done"

        _finish(run_id, outcome, budget)
        report(
            f"Hoàn tất · {budget.used} truy vấn · {len(results)} nguồn · "
            f"{len(outcome.entities)} hồ sơ"
        )
        return outcome, results

    except Exception as exc:
        with get_conn() as conn:
            conn.execute(
                "UPDATE research_runs SET status = 'error', error_message = ? WHERE id = ?",
                (f"{type(exc).__name__}: {exc}", run_id),
            )
        raise


def _finish(run_id: int, outcome: ResearchOutcome, budget: QueryBudget) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE research_runs
            SET queries_used = ?, n_queries = ?, n_sources = ?, status = ?
            WHERE id = ?
            """,
            (
                json.dumps(budget.queries, ensure_ascii=False),
                budget.used,
                outcome.n_sources,
                outcome.status,
                run_id,
            ),
        )
