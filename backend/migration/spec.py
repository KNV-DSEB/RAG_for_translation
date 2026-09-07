"""Đặc tả những gì được chuyển lên cloud, và những gì CỐ Ý không chuyển.

Đây là bản mô tả DUY NHẤT. Cả `runner` (ghi) lẫn `verify` (kiểm) đều đọc từ đây, nên
hai bên không thể lệch nhau — nếu verify có danh sách riêng thì nó sẽ kiểm đúng thứ
runner làm, kể cả khi cả hai cùng sai.

Thứ tự trong `DURABLE` là thứ tự CHÈN, xếp theo phụ thuộc khoá ngoại. Đảo thứ tự là
PostgreSQL từ chối vì khoá ngoại chưa tồn tại — và đó là điều tốt: sai thứ tự thì hỏng
to tiếng, không hỏng âm thầm.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    """Một bảng được chuyển lên cloud."""

    table: str
    pk: str
    depends_on: tuple[str, ...] = ()
    # Cột dùng để so nội dung khi kiểm. Không so `created_at` của những bảng mà
    # PostgreSQL tự sinh mặc định khác định dạng — chỉ so thứ mang ý nghĩa nghiệp vụ.
    hash_columns: tuple[str, ...] = ()


# ============================== Dữ liệu bền ==============================
#
# Xếp theo phụ thuộc khoá ngoại. `document_chunks` phải sau `documents`, `scores` phải
# sau `turn_attempts`, v.v.

DURABLE: tuple[Entity, ...] = (
    Entity("workspaces", "id", (),
           ("name", "industry", "is_confidential", "notes")),
    Entity("engagements", "id", ("workspaces",),
           ("workspace_id", "topic", "partners", "event_date", "notes")),
    Entity("documents", "id", ("workspaces",),
           ("workspace_id", "filename", "ext", "size_bytes", "content_hash",
            "language", "language_source", "extraction_quality", "extractor",
            "status", "n_chars", "n_chunks")),
    # Văn bản chunk là NGUỒN CHUẨN để dựng lại vector — xem `docs/cloud-migration.md` §7.
    Entity("document_chunks", "id", ("documents",),
           ("document_id", "workspace_id", "chunk_index", "text", "locator", "lang")),
    # `confidence` là NHÃN TIN CẬY: `aligned_from_parallel` không được nâng thành gì khác.
    Entity("glossary", "id", ("workspaces",),
           ("workspace_id", "term_vi", "term_vi_norm", "term_en", "pronunciation",
            "definition", "category", "confidence", "status", "source_type",
            "source_ref", "frequency")),
    Entity("glossary_conflicts", "id", ("glossary",),
           ("glossary_id", "proposed_term_en", "proposed_definition", "confidence", "resolved")),
    Entity("research_runs", "id", ("workspaces", "engagements"),
           ("workspace_id", "engagement_id", "client_name", "topic", "industry",
            "queries_used", "n_queries", "n_sources", "n_terms", "status")),
    Entity("profiles", "id", ("workspaces", "research_runs"),
           ("workspace_id", "research_run_id", "entity_name", "entity_role")),
    # `has_source` và `is_expert_edited` là NHÃN TIN CẬY. Chuyển nguyên trạng, không diễn
    # giải lại — nâng `has_source` thành "đã xác minh" là đúng loại lỗi dự án này đang chống.
    Entity("profile_fields", "id", ("profiles",),
           ("profile_id", "field_key", "value", "has_source", "is_expert_edited")),
    Entity("profile_sources", "id", ("profile_fields",),
           ("profile_field_id", "url", "title", "published_at", "snippet")),
    Entity("mock_sessions", "id", ("workspaces", "engagements"),
           ("workspace_id", "engagement_id", "mode", "difficulty", "n_turns",
            "hide_script", "status", "overall_score")),
    # `reference_tier` giữ nguyên: 'ai' | 'expert_pinned' | 'verbatim_parallel'.
    # Không tự nâng 'ai' thành 'human' — nhãn cũ đó đã được chứng minh là dương tính giả.
    Entity("mock_turns", "id", ("mock_sessions",),
           ("session_id", "turn_index", "speaker_name", "speaker_role", "source_lang",
            "target_lang", "source_text", "reference_translation", "reference_tier",
            "est_duration_sec")),
    Entity("turn_attempts", "id", ("mock_turns",),
           ("turn_id", "session_id", "transcript_edited", "input_mode",
            "replay_count", "response_time_sec")),
    Entity("scores", "id", ("turn_attempts",),
           ("attempt_id", "score_overall", "score_meaning", "score_terminology",
            "score_completeness", "score_expression", "comment")),
    # Nhận định của chuyên gia — điểm người chấm KHÔNG được lẫn với điểm máy chấm.
    Entity("expert_verdicts", "id", ("glossary", "turn_attempts"),
           ("attempt_id", "workspace_id", "action", "score_overall", "note",
            "related_category", "pinned_translation")),
    Entity("qa_history", "id", ("workspaces",),
           ("workspace_id", "question", "answer", "citations", "confidence")),
    # Nhật ký gửi ra ngoài là LỊCH SỬ, không phải trạng thái chạy. Ba trạng thái
    # blocked/attempt_succeeded/attempt_failed chuyển nguyên trạng — đổi `attempt_failed`
    # thành `blocked` là nói rằng dữ liệu chưa rời máy trong khi không ai chứng minh được.
    Entity("egress_log", "id", (),
           ("workspace_id", "module", "destination", "provider", "endpoint",
            "n_chars", "summary", "status", "error_class", "operation_id")),
)


# ============================== Trạng thái chạy: KHÔNG chuyển ==============================
#
# Đây không phải mất dữ liệu. Đây là bốn bảng mà việc mang chúng sang mới là sai.

RUNTIME_SKIPPED: dict[str, str] = {
    "operations": (
        "Thao tác đang dở của bản chạy trên máy. `operation_id` chỉ có nghĩa trong đúng "
        "tiến trình đã sinh ra nó; mang sang cloud là cho phép resume một thao tác mà "
        "chuyên gia đã bỏ dở ở một máy khác, một phiên khác."
    ),
    "operation_calls": (
        "Bộ đếm ngân sách của các thao tác trên. Không có thao tác thì bộ đếm vô nghĩa, "
        "và mang sang thì một thao tác mới có thể thừa hưởng số lượt đã tiêu."
    ),
    "consent_grants": (
        "Quyền đồng ý đã cấp trên máy cá nhân. Chuyên gia bấm đồng ý cho ứng dụng chạy "
        "trên MÁY MÌNH — đó không phải sự đồng ý cho một máy chủ ở nơi khác. Đồng ý "
        "phải được hỏi lại, và hỏi lại đúng ngữ cảnh mới."
    ),
    "pending_consents": (
        "Challenge đồng ý chưa dùng, tuổi thọ 10 phút. Không có gì để mang sang."
    ),
}


def durable_tables() -> tuple[str, ...]:
    return tuple(e.table for e in DURABLE)


def entity(table: str) -> Entity:
    for e in DURABLE:
        if e.table == table:
            return e
    raise KeyError(f"{table} không nằm trong danh sách chuyển")
