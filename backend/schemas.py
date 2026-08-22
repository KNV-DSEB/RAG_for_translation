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
    workspace_id: int
    scope: Literal["session", "once"] = "session"
    destination: Literal["llm", "search"] | None = None


class EgressPreviewOut(BaseModel):
    """Trả về kèm HTTP 409 khi hồ sơ mật chưa có vé đồng ý."""

    workspace_id: int
    workspace_name: str
    module: str
    destination: str
    endpoint: str
    n_chars: int
    summary: str
    payload_excerpt: str


class EgressLogOut(BaseModel):
    id: int
    workspace_id: int | None = None
    module: str
    destination: str
    endpoint: str | None = None
    n_chars: int
    summary: str | None = None
    consented: bool
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
