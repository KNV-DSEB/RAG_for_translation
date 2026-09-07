"""Endpoint kho lưu trữ: xin giấy phép, nhận tệp (bản local), chốt.

Vì sao đường nhận tệp của bản local KHÔNG cần header xác thực
------------------------------------------------------------
`PUT /storage/upload/{token}` nằm ngoài lớp xác thực, và đó là CÓ CHỦ ĐÍCH: nó là bản
tương đương của URL ký sẵn mà Supabase phát ra — trình duyệt cũng gửi tệp tới URL đó mà
không kèm JWT của ứng dụng.

Thứ cấp quyền ở đây là **giấy phép**, không phải danh tính:

  - token ngẫu nhiên 32 byte, không đoán được;
  - dùng ĐÚNG MỘT LẦN, hết hạn sau 15 phút;
  - khoá đích đã bị khoá cứng trong giấy phép từ lúc máy chủ phát — người cầm token
    không chọn được nơi ghi, kể cả khi họ đoán được khoá của người khác;
  - trần dung lượng cũng nằm trong giấy phép.

Nói cách khác: cầm được token thì ghi được đúng một tệp vào đúng một chỗ đã định, một
lần. Đó là toàn bộ quyền mà nó cấp.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.storage import get_backend
from backend.storage.base import StorageError
from backend.storage.local import LocalStorage

router = APIRouter(prefix="/storage", tags=["storage"])


@router.put("/upload/{token}")
async def receive_upload(token: str, request: Request) -> dict[str, Any]:
    """Nhận tệp cho một giấy phép (CHỈ bản chạy local — cloud tải thẳng lên Supabase)."""
    backend = get_backend()
    if not isinstance(backend, LocalStorage):
        raise HTTPException(
            status_code=404,
            detail="Đường này chỉ có ở bản chạy trên máy. Trên cloud, tệp đi thẳng tới kho.",
        )

    data = await request.body()
    try:
        info = backend.consume_ticket(token, data)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"key": info.key, "size_bytes": info.size_bytes, "sha256": info.sha256}


@router.get("/download/{token}")
def resolve_download(token: str) -> dict[str, Any]:
    """Đổi mã tải xuống lấy nội dung (chỉ bản local)."""
    backend = get_backend()
    if not isinstance(backend, LocalStorage):
        raise HTTPException(status_code=404, detail="Chỉ có ở bản chạy trên máy.")
    try:
        key = backend.resolve_download(token)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"key": key, "size_bytes": len(backend.download(key))}
