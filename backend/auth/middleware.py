"""Chặn mặc định: mọi endpoint đều cần đăng nhập, trừ danh sách công khai tường minh.

Vì sao là middleware chứ không phải Depends() trên từng route
------------------------------------------------------------
Ứng dụng có 53 endpoint. Gắn `Depends(get_current_user)` lên từng cái là 53 cơ hội bỏ
sót, và cái bị sót chính là lỗ rò. Tệ hơn: endpoint viết SAU đợt này mặc định sẽ KHÔNG
được bảo vệ, tức là lỗ rò tự sinh ra theo thời gian mà không ai làm gì sai.

Đảo lại: chặn hết, rồi liệt kê tường minh những đường thật sự công khai. Endpoint mới
mặc định được bảo vệ. `test_c14` khoá danh sách công khai lại, nên nới nó ra là một thay
đổi có chủ đích và nhìn thấy được trong diff, không phải chuyện xảy ra âm thầm.

Danh tính KHÔNG bao giờ đến từ thân request
------------------------------------------
`user_id`, `email`, `owner` do client gửi lên đều bị bỏ qua. Chỉ `sub` trong JWT đã kiểm
chữ ký mới được tính.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.auth import ownership
from backend.auth.context import set_request_identity
from backend.auth.verify import AuthError, AuthUser, is_allowed, verify_token

# Đường công khai. Cố ý ngắn, và mỗi mục phải tự giải thích được vì sao nó ở đây.
PUBLIC_EXACT: frozenset[str] = frozenset(
    {
        "/health",              # kiểm tra sống — Railway gọi, không mang dữ liệu
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/favicon.ico",
    }
)

# Tiền tố công khai: tệp tĩnh của giao diện, và đường nhận tệp tải lên.
#
# `/storage/upload/` và `/storage/download/` nằm ngoài lớp xác thực có CHỦ ĐÍCH: chúng
# là bản tương đương của URL ký sẵn mà Supabase phát ra, và trình duyệt cũng gửi tệp tới
# URL đó mà không kèm JWT. Thứ cấp quyền là GIẤY PHÉP — token ngẫu nhiên 32 byte, dùng
# một lần, hết hạn 15 phút, và khoá đích đã bị khoá cứng trong đó từ lúc máy chủ phát.
# Cầm token chỉ ghi được đúng một tệp vào đúng một chỗ đã định. Xem `routes/storage.py`.
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/static/", "/js/", "/css/", "/storage/upload/", "/storage/download/",
)

# Trang HTML phục vụ ở gốc. Bản thân trang không chứa dữ liệu — dữ liệu nằm sau API.
PUBLIC_SUFFIXES: tuple[str, ...] = (".html",)


def is_public(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    if path == "/" or path.endswith(PUBLIC_SUFFIXES):
        return True
    return path.startswith(PUBLIC_PREFIXES)


def _unauthorized(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "unauthenticated", "detail": reason},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def auth_middleware(request: Request, call_next):
    """Gắn `request.state.user` sau khi đã kiểm chữ ký, hoặc chặn ngay tại đây."""
    request.state.user = None
    request.state.client_session_id = (
        request.headers.get("X-Client-Session-Id", "").strip() or None
    )

    # Chạy trên máy cá nhân: không có khoá, không có danh tính, chỉ một người dùng.
    # Không giả vờ có phân quyền ở nơi không có ai để phân.
    set_request_identity(None, request.state.client_session_id)

    if not ownership.auth_enabled():
        return await call_next(request)

    if request.method == "OPTIONS" or is_public(request.url.path):
        return await call_next(request)

    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return _unauthorized("Thiếu header Authorization: Bearer <token>.")

    try:
        user: AuthUser = verify_token(header[7:].strip())
    except AuthError as exc:
        return _unauthorized(exc.reason)

    if not is_allowed(user):
        # Đăng nhập được KHÔNG có nghĩa là được dùng. Giai đoạn thử nghiệm chỉ mở cho
        # những email trong ALLOWED_USER_EMAILS.
        return JSONResponse(
            status_code=403,
            content={
                "error": "not_in_pilot",
                "detail": "Tài khoản này chưa được mở quyền dùng bản thử nghiệm.",
            },
        )

    request.state.user = user
    set_request_identity(user, request.state.client_session_id)
    return await call_next(request)


def current_user(request: Request) -> AuthUser | None:
    """Danh tính đã xác minh của request hiện tại, hoặc None khi xác thực đang tắt."""
    return getattr(request.state, "user", None)


def client_session_id(request: Request) -> str | None:
    """Mã phiên trình duyệt, dùng để giới hạn phạm vi quyền `session` (xem gateway)."""
    return getattr(request.state, "client_session_id", None)
