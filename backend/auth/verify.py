"""Xác minh JWT của Supabase Auth — CHỮ KÝ thật, không chỉ giải mã.

Vào:  chuỗi JWT lấy từ header `Authorization: Bearer …`
Ra:   `AuthUser` gồm `user_id` (UUID trong `sub`) và `email`, hoặc ném `AuthError`.

Vì sao KHÔNG tải JWKS qua mạng
------------------------------
Cách phổ biến là gọi `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` để lấy khoá công
khai. Nhưng invariant C1a của dự án (`tests/test_c1_single_door.py`) cấm mọi module ngoài
`backend/security/providers/**` import thư viện mạng, và CLAUDE.md tuyên bố hệ thống chỉ
có **đúng ba đường dữ liệu ra ngoài**. Thêm một lệnh gọi mạng ở tầng xác thực là làm câu
tuyên bố đó thành sai — đúng loại lỗi cả dự án này đang chống.

Nên khoá được cấp qua biến môi trường, và xác minh chạy hoàn toàn tại chỗ:

  SUPABASE_JWT_SECRET   khoá đối xứng HS256 (dự án Supabase dùng secret dùng chung)
  SUPABASE_JWT_JWKS     tài liệu JWKS dạng JSON, cho khoá bất đối xứng (ES256/RS256)

**Giới hạn thật, không giấu:** Supabase xoay khoá bất đối xứng thì phải cập nhật
`SUPABASE_JWT_JWKS` bằng tay rồi khởi động lại. Đây là cái giá đã biết của việc giữ đúng
ba đường ra ngoài, không phải chuyện bỏ sót. Ghi trong `docs/security-model.md`.

Xác minh những gì
-----------------
Chữ ký · thời hạn (`exp`) · thời điểm phát hành (`iat`) · `iss` nếu có cấu hình ·
`aud` nếu có cấu hình · `sub` phải tồn tại và là chuỗi không rỗng.

`sub` là danh tính chuẩn. **Không dùng email làm khoá sở hữu** — email đổi được, `sub`
thì không.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKSet

from backend.config import settings


class AuthError(Exception):
    """JWT không hợp lệ. Thông báo cố ý mơ hồ với bên ngoài, chi tiết nằm ở `reason`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AuthUser:
    """Danh tính đã xác minh. Chỉ được tạo ra từ một JWT đã qua kiểm chữ ký."""

    user_id: str
    email: str

    @property
    def email_lower(self) -> str:
        return self.email.strip().lower()


def _algorithms() -> list[str]:
    return ["ES256", "RS256"] if settings.supabase_jwt_jwks else ["HS256"]


def _key_for(token: str) -> Any:
    """Khoá dùng để kiểm chữ ký. Ném `AuthError` nếu chưa cấu hình khoá nào."""
    if settings.supabase_jwt_jwks:
        try:
            key_set = PyJWKSet.from_dict(json.loads(settings.supabase_jwt_jwks))
        except Exception as exc:  # noqa: BLE001
            raise AuthError(f"SUPABASE_JWT_JWKS không đọc được: {type(exc).__name__}") from exc

        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        for key in key_set.keys:
            if kid is None or key.key_id == kid:
                return key.key
        raise AuthError("không tìm thấy khoá công khai khớp `kid` — có thể Supabase đã xoay khoá")

    if settings.supabase_jwt_secret:
        return settings.supabase_jwt_secret

    raise AuthError(
        "Chưa cấu hình khoá xác minh JWT. Đặt SUPABASE_JWT_SECRET hoặc SUPABASE_JWT_JWKS. "
        "Không có khoá thì KHÔNG chấp nhận token nào — thà chặn hết còn hơn tin bừa."
    )


def verify_token(token: str) -> AuthUser:
    """Kiểm một JWT và trả về danh tính. Ném `AuthError` nếu bất kỳ điều kiện nào trượt."""
    if not token or not token.strip():
        raise AuthError("thiếu token")

    options: dict[str, Any] = {
        "require": ["exp", "sub"],
        "verify_signature": True,
        "verify_exp": True,
        "verify_aud": bool(settings.supabase_jwt_audience),
        "verify_iss": bool(settings.supabase_jwt_issuer),
    }

    kwargs: dict[str, Any] = {}
    if settings.supabase_jwt_audience:
        kwargs["audience"] = settings.supabase_jwt_audience
    if settings.supabase_jwt_issuer:
        kwargs["issuer"] = settings.supabase_jwt_issuer

    try:
        claims = jwt.decode(
            token,
            key=_key_for(token),
            algorithms=_algorithms(),
            options=options,
            leeway=30,          # lệch đồng hồ giữa Supabase và Railway
            **kwargs,
        )
    except AuthError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token đã hết hạn") from exc
    except jwt.InvalidTokenError as exc:
        # Gộp mọi lỗi token về một thông báo: chữ ký sai, `aud` sai, thuật toán sai đều
        # không nên nói rõ với bên ngoài là sai ở đâu.
        raise AuthError(f"token không hợp lệ ({type(exc).__name__})") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise AuthError("token thiếu `sub` — không xác định được ai")

    email = claims.get("email")
    if not isinstance(email, str):
        email = ""

    return AuthUser(user_id=sub.strip(), email=email.strip())


def is_allowed(user: AuthUser) -> bool:
    """Danh sách thử nghiệm: chỉ những email được liệt kê mới dùng được.

    Đây là CHÍNH SÁCH XÁC THỰC, không phải mô hình dữ liệu. Bỏ `ALLOWED_USER_EMAILS` đi
    là mở cho nhiều người dùng ngay, không phải sửa quyền sở hữu ở bất kỳ đâu — vì quyền
    sở hữu đã gắn với `owner_user_id` của từng hồ sơ chứ không gắn với danh sách này.

    Danh sách rỗng nghĩa là KHÔNG AI được vào. Cố ý chọn hướng chặn: một biến môi trường
    quên đặt thì phải làm hệ thống đóng lại, không phải mở toang.
    """
    return user.email_lower in settings.allowed_user_emails
