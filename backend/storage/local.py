"""Kho lưu trữ trên đĩa — dùng khi chạy trên máy cá nhân và khi chạy test.

Đây KHÔNG phải bản giả lập Supabase. Nó là kho thật của bản chạy local, và nó hiện thực
đúng cùng một luồng: máy chủ phát giấy phép, người tải lên gửi tệp tới URL trong giấy
phép, rồi bước chốt kiểm lại đối tượng. Nhờ vậy luồng được kiểm thật từ đầu tới cuối mà
không cần credential.

Cái nó KHÔNG chứng minh được: rằng Supabase Storage hành xử đúng như tài liệu mô tả.
Chuyện đó chỉ có credential thật mới trả lời được.

Giấy phép ở đây là một mã ngẫu nhiên có hạn dùng, trỏ tới endpoint của chính backend.
Cùng tính chất với URL ký sẵn của Supabase ở đúng chỗ quan trọng: **người tải lên không
chọn được nơi ghi** — khoá đã bị khoá cứng trong giấy phép từ lúc máy chủ phát.
"""

from __future__ import annotations

import hashlib
import pathlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from backend.storage.base import ObjectInfo, ObjectNotFound, StorageError, UploadTicket


class LocalStorage:
    """Kho đặt trong một thư mục gốc. Khoá đối tượng là đường dẫn tương đối trong đó."""

    name = "local"

    def __init__(self, root: pathlib.Path, base_url: str = "") -> None:
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._base_url = base_url.rstrip("/")
        self._tickets: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---------- đường dẫn ----------

    def _path(self, key: str) -> pathlib.Path:
        """Khoá → đường dẫn thật, có chốt chống thoát ra ngoài thư mục gốc.

        `paths.document_key` đã làm sạch rồi, nhưng chốt này vẫn cần: nó bảo vệ cả những
        khoá đến từ đường khác (dữ liệu cũ, lần chạy lại, mã viết sau này). Một lớp chặn
        đặt ngay chỗ ghi đĩa thì không phụ thuộc vào việc mọi người gọi đúng hàm.
        """
        target = (self._root / key).resolve()
        root = self._root.resolve()
        if root != target and root not in target.parents:
            raise StorageError(f"khoá thoát ra ngoài thư mục kho: {key!r}")
        return target

    # ---------- tải lên ----------

    def create_upload_ticket(
        self, key: str, *, content_type: str, max_bytes: int, ttl_sec: int = 900
    ) -> UploadTicket:
        token = secrets.token_urlsafe(32)
        expires = time.time() + ttl_sec
        with self._lock:
            self._tickets[token] = {
                "key": key, "expires": expires,
                "max_bytes": max_bytes, "content_type": content_type,
            }
        return UploadTicket(
            key=key,
            url=f"{self._base_url}/storage/upload/{token}",
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=ttl_sec)).isoformat(),
            max_bytes=max_bytes,
        )

    def consume_ticket(self, token: str, data: bytes) -> ObjectInfo:
        """Nhận tệp cho một giấy phép. Dùng một lần, hết hạn thì từ chối."""
        with self._lock:
            ticket = self._tickets.pop(token, None)
        if ticket is None:
            raise StorageError("giấy phép tải lên không tồn tại hoặc đã dùng rồi")
        if time.time() > ticket["expires"]:
            raise StorageError("giấy phép tải lên đã hết hạn")
        if len(data) > ticket["max_bytes"]:
            raise StorageError(
                f"tệp {len(data)} byte, vượt mức {ticket['max_bytes']} byte đã cấp phép"
            )

        path = self._path(ticket["key"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return ObjectInfo(
            key=ticket["key"],
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=ticket["content_type"],
        )

    # ---------- đọc / xoá ----------

    def stat(self, key: str) -> ObjectInfo | None:
        path = self._path(key)
        if not path.is_file():
            return None
        data = path.read_bytes()
        return ObjectInfo(key=key, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

    def download(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(f"không có đối tượng {key!r}")
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        # Dọn thư mục rỗng còn lại, nhưng KHÔNG bao giờ vượt lên trên thư mục gốc.
        parent = path.parent
        root = self._root.resolve()
        while parent != root and root in parent.parents and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
        return True

    def delete_prefix(self, prefix: str) -> int:
        base = self._path(prefix.rstrip("/"))
        if not base.is_dir():
            return 0
        removed = 0
        for item in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if item.is_file():
                item.unlink()
                removed += 1
            elif item.is_dir() and not any(item.iterdir()):
                item.rmdir()
        if base.is_dir() and not any(base.iterdir()):
            base.rmdir()
        return removed

    def signed_download_url(self, key: str, *, ttl_sec: int = 300) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tickets[f"dl:{token}"] = {"key": key, "expires": time.time() + ttl_sec}
        return f"{self._base_url}/storage/download/{token}"

    def resolve_download(self, token: str) -> str:
        with self._lock:
            ticket = self._tickets.get(f"dl:{token}")
        if ticket is None or time.time() > ticket["expires"]:
            raise StorageError("liên kết tải xuống không còn hiệu lực")
        return str(ticket["key"])
