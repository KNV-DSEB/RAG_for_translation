"""Chốt quyền sở hữu hồ sơ — MỘT nơi, phủ toàn bộ endpoint.

Vì sao không gắn vào từng route
-------------------------------
Đo trên mã trước khi sửa: 24 endpoint nhận `workspace_id` mà KHÔNG kiểm gì cả, và ba
bản `_require_workspace` sao chép nhau ở `documents.py`, `research.py`, `simulate.py`
cũng chỉ kiểm hồ sơ có tồn tại không, không kiểm của ai.

Vá 24 chỗ bằng tay là 24 cơ hội bỏ sót, và endpoint viết sau đợt này mặc định lại không
có kiểm. Nên đặt guard làm dependency và gắn ở chỗ `include_router(...)` trong `main.py`
— FastAPI áp nó cho MỌI route của router đó. `test_c14` khoá lại: router nào được gắn
mà thiếu guard thì đỏ.

Lấy `workspace_id` từ đâu
-------------------------
Query string, path param, và thân JSON — cả ba đều là đường client gửi id vào. Đọc thân
request ở dependency là an toàn: FastAPI nhớ lại body nên route vẫn tự phân tích được
như thường.

Không tin `workspace_id` do client gửi
--------------------------------------
Chính vì client gửi nên mới phải kiểm. Guard đối chiếu nó với `owner_user_id` của hồ sơ
và `sub` trong JWT đã xác minh. Không khớp thì 404 — KHÔNG phải 403, vì 403 xác nhận hồ
sơ đó có tồn tại, mà riêng điều đó đã là rò rỉ (xem `ownership.require_workspace`).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from backend.auth import ownership
from backend.auth.middleware import current_user, is_public


def _first_int(value: Any) -> int | None:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


async def _workspace_ids_in(request: Request) -> set[int]:
    """Mọi `workspace_id` xuất hiện trong request, bất kể client đặt nó ở đâu."""
    found: set[int] = set()

    for source in (request.query_params, request.path_params):
        for key in ("workspace_id", "workspace"):
            if key in source:
                n = _first_int(source[key])
                if n is not None:
                    found.add(n)

    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith("application/json"):
            try:
                body = await request.body()
                if body:
                    # `request.body()` nhớ lại nội dung, nên route vẫn đọc được sau đây.
                    payload = json.loads(body)
                    if isinstance(payload, dict):
                        n = _first_int(payload.get("workspace_id"))
                        if n is not None:
                            found.add(n)
            except (ValueError, UnicodeDecodeError):
                # Thân request hỏng là việc của route, không phải của guard.
                pass

    return found


async def workspace_guard(request: Request) -> None:
    """Chặn nếu request chạm tới hồ sơ không thuộc về người gọi."""
    if not ownership.auth_enabled() or is_public(request.url.path):
        return

    user = current_user(request)
    for workspace_id in await _workspace_ids_in(request):
        # Ném HTTPException(404) khi không phải chủ. Kiểm TỪNG id: một request có thể
        # mang nhiều id (ví dụ chuyển thuật ngữ giữa hai hồ sơ).
        ownership.require_workspace(workspace_id, user)
