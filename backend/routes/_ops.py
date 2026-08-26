"""Cầu nối giữa HTTP và `gateway.operation(...)`.

Vào:  `Request` của FastAPI.
Ra:   `OpContext` — vân tay của request + mã thao tác cần vào lại (nếu có).

Vì sao cần vân tay
------------------
Sau khi chuyên gia bấm đồng ý, giao diện gửi LẠI đúng request cũ kèm header
`X-Operation-Id`. Nếu chỉ kiểm mã thao tác thì quyền cấp cho "nghiên cứu khách hàng A"
dùng lại được cho khách hàng B — cùng hồ sơ, cùng loại thao tác, mọi kiểm tra khác đều
lọt. Vân tay khoá quyền vào đúng LẦN thao tác đó.

Chạy được vì `web/js/api.js` thử lại bằng đúng `options` cũ nên thân request giống hệt
từng byte. Đó là tính chất của việc gom retry về một chỗ duy nhất, không phải may mắn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from backend.security import gateway

# Header giao diện gửi kèm khi thử lại sau khi được đồng ý.
OPERATION_HEADER = "X-Operation-Id"


@dataclass(frozen=True)
class OpContext:
    fingerprint: str
    resume_id: str | None


async def op_context(request: Request) -> OpContext:
    """Dependency của FastAPI: dựng vân tay từ chính request đang xử lý.

    Đọc thân request ở đây an toàn: `Request.body()` nhớ kết quả, nên phần đọc tham số
    của FastAPI phía sau vẫn lấy được cùng nội dung đó.
    """
    body: Any = None
    raw = await request.body()
    if raw:
        try:
            body = json.loads(raw)
        except ValueError:
            # Không phải JSON (multipart chẳng hạn). Băm chính chuỗi byte để vân tay vẫn
            # gắn được với đúng lần gửi này. Hiện không route multipart nào gọi ra ngoài,
            # nhưng nếu sau này có thì nó vẫn được khoá đúng lần thao tác.
            body = {"__raw_sha__": gateway.fingerprint(
                method="", route="", body=raw.decode("utf-8", "replace")
            )}

    return OpContext(
        fingerprint=gateway.fingerprint(
            method=request.method,
            route=request.url.path,
            body=body,
            query=dict(request.query_params),
        ),
        resume_id=request.headers.get(OPERATION_HEADER),
    )
