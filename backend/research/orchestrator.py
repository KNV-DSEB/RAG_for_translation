"""Gộp một lần nghiên cứu hoàn chỉnh: hồ sơ khách hàng + bảng thuật ngữ.

Input:  workspace_id + thông tin buổi làm việc.
Output: `FullResearchResult` — hồ sơ các bên, thống kê glossary, và các ghi chú/cảnh báo.

Đây là hàm mà route gọi. Vòng lặp tuần tự, không dùng framework agent (xem CLAUDE.md):
    1. Lập kế hoạch truy vấn (LLM)
    2. Tìm kiếm web (qua cửa egress, ≤8 truy vấn)
    3. Tổng hợp hồ sơ, mỗi trường gắn URL nguồn (LLM)
    4. Trích thuật ngữ từ tài liệu song ngữ → tài liệu đơn ngữ → web (LLM)
    5. Ghi vào bảng glossary, chống trùng và ghi nhận xung đột

Bước 4 chạy được cả khi không có mạng: trích thuật ngữ từ tài liệu đã nạp không cần web
(spec edge case §4.4 — "không có internet thì trích thuật ngữ từ tài liệu vẫn chạy").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from backend.config import settings
from backend.db import get_conn
from backend.research import terminology
from backend.research.profiler import EntityProfile, ResearchOutcome, run_research
from backend.research.search import SearchResult
from backend.security import llm

ProgressFn = Callable[[str], None]

# Tài liệu ngắn hơn mức này thì bỏ qua, không đáng một lệnh gọi LLM.
MIN_DOC_CHARS_FOR_TERMS = 200


@dataclass
class FullResearchResult:
    research_run_id: int
    entities: list[EntityProfile] = field(default_factory=list)
    queries_used: list[str] = field(default_factory=list)
    n_sources: int = 0
    n_terms_total: int = 0
    n_terms_added: int = 0
    n_terms_human: int = 0
    n_conflicts: int = 0
    not_found_notes: list[str] = field(default_factory=list)
    ambiguity_warning: str = ""
    warnings: list[str] = field(default_factory=list)
    status: str = "done"


def _count_terms(workspace_id: int) -> tuple[int, int]:
    """Trả về (tổng thuật ngữ đang dùng, số thuật ngữ có bản dịch của người thật)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN confidence = 'human_translated' THEN 1 ELSE 0 END) AS human
            FROM glossary WHERE workspace_id = ? AND status <> 'skipped'
            """,
            (workspace_id,),
        ).fetchone()
    return int(row["total"] or 0), int(row["human"] or 0)


def extract_all_terms(
    workspace_id: int,
    topic: str,
    web_results: list[SearchResult],
    report: ProgressFn,
) -> terminology.UpsertStats:
    """Trích thuật ngữ từ cả ba nguồn rồi ghi vào bảng."""
    collected: list[terminology.TermRecord] = []
    stats_notes: list[str] = []

    documents = terminology.document_texts(workspace_id)

    # --- Nguồn 1: tài liệu song ngữ song song (đáng tin nhất) ---
    for doc in documents:
        if doc["language"] != "parallel":
            continue
        vi_text, en_text = str(doc["vi_text"]), str(doc["en_text"])
        if len(vi_text) < MIN_DOC_CHARS_FOR_TERMS or len(en_text) < MIN_DOC_CHARS_FOR_TERMS:
            continue
        report(f"Trích cặp thuật ngữ từ tài liệu song ngữ '{doc['filename']}'…")
        try:
            terms = terminology.extract_from_parallel(
                vi_text, en_text, topic, str(doc["filename"]), workspace_id
            )
            collected.extend(terms)
            report(f"  → {len(terms)} cặp do người thật dịch")
        except llm.LLMError as exc:
            stats_notes.append(f"Không trích được từ '{doc['filename']}': {exc}")

    # --- Nguồn 2: tài liệu một ngôn ngữ ---
    for doc in documents:
        if doc["language"] not in ("vi", "en"):
            continue
        text = str(doc["full_text"])
        if len(text) < MIN_DOC_CHARS_FOR_TERMS:
            continue
        report(f"Trích thuật ngữ từ '{doc['filename']}'…")
        try:
            terms = terminology.extract_from_monolingual(
                text, str(doc["language"]), topic, str(doc["filename"]), workspace_id
            )
            collected.extend(terms)
            report(f"  → {len(terms)} thuật ngữ")
        except llm.LLMError as exc:
            stats_notes.append(f"Không trích được từ '{doc['filename']}': {exc}")

    # --- Nguồn 3: kết quả web ---
    if web_results:
        report(f"Trích thuật ngữ từ {len(web_results)} nguồn web…")
        try:
            terms = terminology.extract_from_web(web_results, topic, workspace_id)
            collected.extend(terms)
            report(f"  → {len(terms)} thuật ngữ")
        except llm.LLMError as exc:
            stats_notes.append(f"Không trích được thuật ngữ từ web: {exc}")

    report(f"Ghi {len(collected)} thuật ngữ ứng viên vào bảng…")
    stats = terminology.upsert_terms(workspace_id, collected)
    stats.notes.extend(stats_notes)
    return stats


def run_full_research(
    workspace_id: int,
    client_name: str,
    partner_names: list[str],
    topic: str,
    industry: str | None = None,
    extra_notes: str | None = None,
    engagement_id: int | None = None,
    on_progress: ProgressFn | None = None,
) -> FullResearchResult:
    """Chạy trọn: hồ sơ khách hàng + bảng thuật ngữ."""

    def report(message: str) -> None:
        if on_progress:
            on_progress(message)

    outcome: ResearchOutcome
    web_results: list[SearchResult]

    try:
        outcome, web_results = run_research(
            workspace_id=workspace_id,
            client_name=client_name,
            partner_names=partner_names,
            topic=topic,
            industry=industry,
            extra_notes=extra_notes,
            engagement_id=engagement_id,
            on_progress=on_progress,
        )
    except Exception:
        raise

    result = FullResearchResult(
        research_run_id=outcome.research_run_id,
        entities=outcome.entities,
        queries_used=outcome.queries_used,
        n_sources=outcome.n_sources,
        not_found_notes=list(outcome.not_found_notes),
        ambiguity_warning=outcome.ambiguity_warning,
        warnings=list(outcome.warnings),
        status=outcome.status,
    )

    stats = extract_all_terms(workspace_id, topic, web_results, report)
    result.n_terms_added = stats.added
    result.n_conflicts = stats.conflicts
    result.warnings.extend(stats.notes)

    if stats.skipped_expert:
        result.warnings.append(
            f"{stats.skipped_expert} thuật ngữ bạn đã sửa tay được giữ nguyên, "
            "không bị lần nghiên cứu này ghi đè."
        )
    if stats.conflicts:
        result.warnings.append(
            f"{stats.conflicts} thuật ngữ có bản dịch khác với bản đã lưu — "
            "xem mục xung đột trong bảng thuật ngữ để chọn bản chuẩn."
        )

    total, human = _count_terms(workspace_id)
    result.n_terms_total = total
    result.n_terms_human = human

    # Nói rõ khi chưa đạt ngưỡng thay vì im lặng (spec edge case §4.4)
    if total < settings.min_glossary_terms:
        result.not_found_notes.append(
            f"Chỉ trích được {total} thuật ngữ, chưa đạt ngưỡng {settings.min_glossary_terms}. "
            "Nguyên nhân thường là ít tài liệu hoặc chủ đề hẹp. Cách xử lý: nạp thêm tài liệu, "
            "mở rộng mô tả chủ đề, hoặc tự thêm thuật ngữ vào bảng."
        )

    with get_conn() as conn:
        conn.execute(
            "UPDATE research_runs SET n_terms = ? WHERE id = ?",
            (total, result.research_run_id),
        )

    report(
        f"Xong · {len(result.queries_used)} truy vấn · {result.n_sources} nguồn · "
        f"{total} thuật ngữ ({human} do người thật dịch)"
    )
    return result
