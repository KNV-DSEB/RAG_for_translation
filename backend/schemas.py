"""Pydantic schemas dùng chung: request/response của API và cấu trúc output mong đợi từ LLM.

Input/Output: các model ở đây là hợp đồng dữ liệu giữa frontend ↔ backend ↔ LLM.
Schema dành cho LLM (hậu tố `LLMOut`) được truyền vào `llm.generate_json` để validate,
sai cấu trúc thì thử lại một lần rồi báo lỗi — không bao giờ hiện kết quả rỗng.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ============================ Hồ sơ khách hàng ============================


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = None
    is_confidential: bool = False
    notes: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = None
    is_confidential: bool | None = None
    notes: str | None = None


class WorkspaceOut(BaseModel):
    id: int
    name: str
    industry: str | None = None
    is_confidential: bool = False
    notes: str | None = None
    created_at: str
    updated_at: str
    # Số liệu tổng hợp để Dashboard hiện ngay, không phải gọi nhiều lần
    n_documents: int = 0
    n_terms: int = 0
    n_sessions: int = 0


# ============================ Bảo mật §7 ============================


class ConsentGrant(BaseModel):
    """Giao diện chỉ gửi lại mã yêu cầu do máy chủ phát ra, và phạm vi muốn cấp.

    CỐ Ý không có `destination`/`provider`/`payload_hash`: chúng đọc từ bản ghi
    `pending_consents` của chính máy chủ. Để giao diện tự khai những trường đó nghĩa là
    tin nó rằng "đây đúng là thứ người dùng vừa xem" — sai hình dạng cho một quyết định
    bảo mật, kể cả khi mối lo chỉ là bug của chính giao diện.
    """

    consent_request_id: str
    scope: Literal["operation", "session"] = "operation"


class EgressPreviewOut(BaseModel):
    """Trả về kèm HTTP 409 khi hồ sơ mật chưa cho phép thao tác này."""

    consent_request_id: str
    operation_id: str
    workspace_id: int
    workspace_name: str
    operation_kind: str
    declares: list[dict[str, object]]
    scope_note: str
    payload_excerpt: str
    # False = thao tác nhiều lệnh gọi, nội dung do các bước bên trong sinh ra nên chưa
    # biết trước. Hộp thoại PHẢI nói rõ điều đó thay vì hiện một khối rỗng.
    payload_known: bool
    payload_truncated: bool
    n_chars: int


class EgressLogOut(BaseModel):
    id: int
    workspace_id: int | None = None
    module: str
    destination: str
    provider: str = ""
    provider_label: str = ""
    endpoint: str | None = None
    n_chars: int
    summary: str | None = None
    # 'blocked' — chưa chạm mạng. 'attempt_succeeded' — nhà cung cấp trả lời bình thường.
    # 'attempt_failed' — đã cố gửi rồi hỏng; KHÔNG kết luận được dữ liệu đã đi hay chưa.
    status: str = "attempt_succeeded"
    error_class: str | None = None
    operation_id: str | None = None
    created_at: str


# ============================ Sức khoẻ hệ thống ============================


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    python_version: str
    tables: list[str]
    n_tables: int
    has_gemini_key: bool
    gemini_model: str
    gemini_model_light: str
    # Chuỗi model sẽ thử khi model chính hết hạn mức ngày (free tier tính theo từng model)
    gemini_chain_quality: list[str] = Field(default_factory=list)
    gemini_chain_light: list[str] = Field(default_factory=list)
    tts_voice_vi: str
    tts_voice_en: str
    rss_mb: float
    # Cảnh báo cấu hình để biết ngay cái gì đang thiếu, không phải mò
    warnings: list[str] = Field(default_factory=list)
