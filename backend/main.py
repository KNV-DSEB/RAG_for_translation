"""Ứng dụng FastAPI — điểm vào của backend.

Input:  HTTP requests từ giao diện web trong thư mục `web/`.
Output: JSON. Mọi lỗi được dịch thành thông báo tiếng Việt nói rõ chuyện gì xảy ra
        và làm gì tiếp (spec A0.3 / A6.8) — không bao giờ trả lỗi thô.

Khởi động: tạo thư mục dữ liệu + tạo schema SQLite (idempotent).
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psutil
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.db import init_db
from backend.rag.extractors import ExtractionError
from backend.research.search import SearchBudgetExceeded, SearchUnavailable
from backend.routes import dashboard as dashboard_routes
from backend.routes import documents as document_routes
from backend.routes import feedback as feedback_routes
from backend.routes import glossary as glossary_routes
from backend.routes import research as research_routes
from backend.routes import security as security_routes
from backend.routes import simulate as simulate_routes
from backend.routes import speech as speech_routes
from backend.routes import workspaces as workspace_routes
from backend.schemas import HealthOut
from backend.security import gateway, llm
from backend.security.gateway import (
    ConsentRequired,
    NoActiveOperation,
    OperationBudgetExceeded,
    PayloadTooLarge,
)

# Số bảng schema phải có. Lệch số này nghĩa là DB chưa tạo đủ.
# 21 = 18 bảng nghiệp vụ + operations + operation_calls + pending_consents
# (consent_tickets cũ đã bị thay bằng consent_grants, không cộng thêm).
EXPECTED_TABLES = 21


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.ensure_dirs()
    tables = init_db()
    app.state.tables = tables
    yield


app = FastAPI(
    title="AI Assistant cho chuyên gia dịch thuật",
    description="RAG tài liệu · Research Agent · Mock buổi dịch · Đọc lời thoại",
    version="0.1.0",
    lifespan=lifespan,
)

# Không cần CORS: giao diện được phục vụ từ chính máy chủ này nên mọi lệnh gọi đều cùng gốc.


# ======================= Xử lý lỗi thành tiếng Việt =======================


@app.exception_handler(ConsentRequired)
async def handle_consent_required(request: Request, exc: ConsentRequired) -> JSONResponse:
    """Hồ sơ mật chưa cho phép → 409 kèm bản xem trước để giao diện hỏi chuyên gia.

    `operation_id` đi kèm ở đây là thứ giữ cho lần thử lại vào ĐÚNG thao tác vừa được
    đồng ý. Thiếu nó, request thứ hai đúc một thao tác mới và quyền vừa cấp thành vô dụng
    — chuyên gia bấm đồng ý xong vẫn bị hỏi lại.
    """
    return JSONResponse(
        status_code=409,
        content={
            "error": "consent_required",
            "detail": str(exc),
            "operation_id": exc.preview.operation_id,
            "preview": exc.preview.as_dict(),
        },
    )


@app.exception_handler(OperationBudgetExceeded)
async def handle_budget_exceeded(request: Request, exc: OperationBudgetExceeded) -> JSONResponse:
    """Thao tác gọi ra ngoài nhiều hơn số lần đã cho chuyên gia biết trước."""
    return JSONResponse(
        status_code=429,
        content={"error": "operation_budget", "detail": str(exc)},
    )


@app.exception_handler(NoActiveOperation)
async def handle_no_operation(request: Request, exc: NoActiveOperation) -> JSONResponse:
    """Lỗi LẬP TRÌNH, không phải lỗi người dùng: có route gọi ra ngoài mà quên mở thao tác.

    Trả 500 vì đúng là hỏng bên trong. Quan trọng là dữ liệu KHÔNG rời khỏi máy — gateway
    đã chặn trước khi chạm mạng.
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": "no_active_operation",
            "detail": (
                "Có lỗi bên trong: một thao tác định gửi dữ liệu ra ngoài mà chưa xin phép. "
                "Dữ liệu KHÔNG bị gửi đi. Hãy báo lại lỗi này."
            ),
            "debug": str(exc),
        },
    )


@app.exception_handler(PayloadTooLarge)
async def handle_payload_too_large(request: Request, exc: PayloadTooLarge) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"error": "payload_too_large", "detail": str(exc)},
    )


@app.exception_handler(llm.LLMUnavailable)
async def handle_llm_unavailable(request: Request, exc: llm.LLMUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": "llm_unavailable", "detail": str(exc)})


@app.exception_handler(llm.LLMQuotaExceeded)
async def handle_llm_quota(request: Request, exc: llm.LLMQuotaExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"error": "llm_quota", "detail": str(exc)})


@app.exception_handler(llm.LLMTimeout)
async def handle_llm_timeout(request: Request, exc: llm.LLMTimeout) -> JSONResponse:
    return JSONResponse(status_code=504, content={"error": "llm_timeout", "detail": str(exc)})


@app.exception_handler(llm.LLMError)
async def handle_llm_error(request: Request, exc: llm.LLMError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"error": "llm_error", "detail": str(exc)})


@app.exception_handler(ExtractionError)
async def handle_extraction_error(request: Request, exc: ExtractionError) -> JSONResponse:
    """Lỗi đọc tài liệu đã có thông báo tiếng Việt nói rõ cách xử lý."""
    return JSONResponse(status_code=422, content={"error": "extraction_error", "detail": str(exc)})


@app.exception_handler(SearchUnavailable)
async def handle_search_unavailable(request: Request, exc: SearchUnavailable) -> JSONResponse:
    """Mất mạng hoặc bị công cụ tìm kiếm chặn — kết quả đã thu vẫn được giữ."""
    return JSONResponse(status_code=503, content={"error": "search_unavailable", "detail": str(exc)})


@app.exception_handler(SearchBudgetExceeded)
async def handle_search_budget(request: Request, exc: SearchBudgetExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"error": "search_budget", "detail": str(exc)})


# ============================== Routes ==============================

app.include_router(workspace_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(document_routes.router)
app.include_router(research_routes.router)
app.include_router(glossary_routes.router)
app.include_router(simulate_routes.router)
app.include_router(speech_routes.router)
app.include_router(feedback_routes.router)
app.include_router(security_routes.router)


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Kiểm tra sức khoẻ: schema đủ bảng chưa, cấu hình thiếu gì, đang dùng bao nhiêu RAM.

    RSS được theo dõi vì máy chỉ có 7.8 GB — mục tiêu giữ tiến trình này dưới ~2.5 GB.
    """
    tables = init_db()
    rss_mb = round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)

    warnings: list[str] = []
    if not settings.has_gemini_key:
        warnings.append(
            "Thiếu GOOGLE_API_KEY trong .env — phần LLM (sinh kịch bản, chấm điểm, "
            "nghiên cứu) sẽ không chạy. Lấy key miễn phí tại https://aistudio.google.com/apikey"
        )
    if len(tables) < EXPECTED_TABLES:
        warnings.append(
            f"Schema chỉ có {len(tables)}/{EXPECTED_TABLES} bảng — cơ sở dữ liệu chưa tạo đủ."
        )
    if rss_mb > 2500:
        warnings.append(
            f"Backend đang dùng {rss_mb} MB, vượt ngân sách ~2.5 GB trên máy 7.8 GB RAM."
        )

    return HealthOut(
        status="ok" if not warnings else "degraded",
        python_version=sys.version.split()[0],
        tables=tables,
        n_tables=len(tables),
        has_gemini_key=settings.has_gemini_key,
        gemini_model=settings.gemini_model,
        gemini_model_light=settings.gemini_model_light,
        gemini_chain_quality=llm.available_models("quality"),
        gemini_chain_light=llm.available_models("light"),
        tts_voice_vi=settings.tts_voice_vi,
        tts_voice_en=settings.tts_voice_en,
        rss_mb=rss_mb,
        warnings=warnings,
    )


@app.get("/system/design-tokens")
def design_tokens() -> dict[str, object]:
    """Bảng màu và bộ chữ, để kiểm tra giao diện và backend không lệch nhau."""
    return {
        "fonts": ["Be Vietnam Pro", "JetBrains Mono"],
        "languages": {"vi": "#1B4079", "en": "#175E63"},
        "signature": "cái sống — khối song ngữ có đường kẻ dọc ở giữa",
    }


@app.post("/system/ping-llm")
def ping_llm(workspace_id: int | None = None) -> dict[str, object]:
    """Gọi thử Gemini một lệnh ngắn: có kết nối + có ghi nhật ký.

    Vẫn phải mở thao tác như mọi đường ra khác — kể cả một lệnh ping. Cửa 0 của gateway
    chặn theo runtime chứ không theo thiện chí, nên không có ngoại lệ nào.
    """
    with gateway.operation(
        workspace_id,
        kind="system.ping",
        declares=[gateway.OperationDeclaration(
            "llm", gateway.PROVIDER_GEMINI, unit_calls=1,
            retries_each=llm.retry_ceiling("light"),
        )],
        fingerprint=gateway.fingerprint(
            method="POST", route="/system/ping-llm", body={"workspace_id": workspace_id}
        ),
        payload_preview="(lệnh ping ngắn để kiểm kết nối)",
    ):
        reply = llm.ping(workspace_id=workspace_id)
    return {
        "reply": reply,
        "model": settings.gemini_model,
        "message": "Lệnh gọi đã được ghi vào nhật ký egress — kiểm tại /security/egress-log",
    }


# ============================== Giao diện ==============================
# Đặt CUỐI CÙNG: mount ở "/" sẽ nuốt mọi đường dẫn chưa khớp route API nào phía trên.
# Một tiến trình, một cổng — không còn phải chạy song song Streamlit ở 8501.

_WEB_DIR = settings.base_dir / "web"


@app.middleware("http")
async def no_cache_for_assets(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Không cache CSS/JS/HTML.

    Đây là ứng dụng chạy trên máy cá nhân, tải lại tệp tĩnh gần như tức thì nên cache
    không đem lại gì. Đổi lại nó gây một kiểu lỗi rất tốn thời gian: sửa xong rồi mà
    trình duyệt vẫn dựng bằng bản cũ, dẫn tới đi tìm bug không tồn tại.
    """
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".css", ".js", ".html")) or path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")
