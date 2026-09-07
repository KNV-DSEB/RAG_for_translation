"""Quyền sở hữu hồ sơ khách hàng — chokepoint DUY NHẤT cho mọi truy cập theo hồ sơ.

Vào:  `workspace_id` do client gửi, và danh tính đã xác minh từ JWT.
Ra:   dòng `workspaces` nếu người này thật sự sở hữu nó, còn không thì 404.

Vì sao gom về một hàm
---------------------
Trước đợt này có BA bản `_require_workspace` giống hệt nhau ở `documents.py`,
`research.py`, `simulate.py` — chỉ kiểm hồ sơ có tồn tại không, không kiểm của ai. Thêm
quyền sở hữu vào ba bản riêng là chắc chắn có ngày một bản bị bỏ quên, và bản bị quên
đó chính là lỗ rò. `test_c14` khoá lại: không route nào được tự định nghĩa hàm này nữa.

Vì sao trả 404 chứ không 403
----------------------------
403 xác nhận hồ sơ đó CÓ TỒN TẠI, chỉ là không phải của bạn. Với dữ liệu khách hàng
của phiên dịch viên, riêng việc biết "tổ chức X có hồ sơ trong hệ thống" đã là rò rỉ.
Đoán `workspace_id` phải cho ra đúng câu trả lời như hỏi một id không có thật.

RANH GIỚI PHÂN QUYỀN NẰM Ở ĐÂY, KHÔNG PHẢI Ở RLS
------------------------------------------------
Backend nối PostgreSQL bằng vai trò có quyền cao, tức là **bỏ qua RLS**. Vậy nên không
được nói "RLS bảo vệ dữ liệu" cho đường đi này. Thứ thật sự chặn là hàm dưới đây.
RLS vẫn bắt buộc cho tài nguyên trình duyệt chạm thẳng vào Supabase — trước hết là
Storage (xem `docs/security-model.md`).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.auth.verify import AuthUser
from backend.config import settings
from backend.db import get_conn

_NOT_FOUND = "Không tìm thấy hồ sơ khách hàng này."


def auth_enabled() -> bool:
    """Xác thực có đang bật không.

    Bật khi đã cấu hình khoá kiểm JWT. Chạy trên máy cá nhân thì không có khoá, không có
    danh tính, và cũng chỉ có một người dùng — nên không có gì để phân quyền. Cloud thì
    luôn có khoá.
    """
    return bool(settings.supabase_jwt_secret or settings.supabase_jwt_jwks)


def require_workspace(workspace_id: int, user: AuthUser | None) -> dict[str, Any]:
    """Hồ sơ phải tồn tại VÀ thuộc về người đang gọi. Không thì 404.

    `user=None` chỉ chấp nhận được khi xác thực đang tắt (chạy trên máy cá nhân). Khi
    xác thực đã bật mà không có danh tính thì đây là lỗi lập trình, không phải trường
    hợp hợp lệ — chặn lại thay vì để lọt.
    """
    if auth_enabled() and user is None:
        raise HTTPException(
            status_code=401,
            detail="Yêu cầu này chạm vào dữ liệu hồ sơ nhưng không có danh tính đã xác minh.",
        )

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    record = dict(row)

    if user is not None:
        owner = record.get("owner_user_id")
        # Hồ sơ chưa có chủ là dòng cũ từ bản chạy local, chưa được migration nhận. Trên
        # cloud KHÔNG ai đọc được nó — mặc định đóng, không mặc định mở.
        if not owner or str(owner) != user.user_id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)

    return record


def owned_workspace_ids(user: AuthUser | None) -> list[int] | None:
    """Danh sách id hồ sơ người này sở hữu. `None` khi xác thực tắt (thấy tất cả)."""
    if user is None:
        return None
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM workspaces WHERE owner_user_id = ? ORDER BY id", (user.user_id,)
        ).fetchall()
    return [int(r["id"]) for r in rows]


def claim_workspace(workspace_id: int, user: AuthUser | None) -> None:
    """Gắn chủ sở hữu cho hồ sơ vừa tạo."""
    if user is None:
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE workspaces SET owner_user_id = ? WHERE id = ?", (user.user_id, workspace_id)
        )
