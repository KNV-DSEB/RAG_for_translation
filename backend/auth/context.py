"""Danh tính của request đang xử lý, đọc được từ chỗ không cầm `Request`.

Middleware gắn danh tính vào `request.state`, nhưng các hàm trợ giúp trong `routes/`
(ví dụ `_require_workspace`) không nhận `Request` làm tham số. Đổi chữ ký của chúng thì
phải sửa mọi chỗ gọi; dùng `ContextVar` thì không.

`ContextVar` ở đây CHỈ để mang danh tính trong phạm vi MỘT request — giống cách
`gateway._ACTIVE` mang thao tác đang mở. Không có trạng thái nào cần sống lâu hơn thế
được để ở đây: chạy nhiều bản backend song song thì mỗi bản có bộ nhớ riêng, nên trạng
thái lâu dài phải nằm trong PostgreSQL.
"""

from __future__ import annotations

from contextvars import ContextVar

from backend.auth.verify import AuthUser

_USER: ContextVar[AuthUser | None] = ContextVar("request_user", default=None)
_SESSION: ContextVar[str | None] = ContextVar("request_client_session", default=None)


def set_request_identity(user: AuthUser | None, client_session_id: str | None) -> None:
    _USER.set(user)
    _SESSION.set(client_session_id)


def request_user() -> AuthUser | None:
    return _USER.get()


def request_session_id() -> str | None:
    return _SESSION.get()
