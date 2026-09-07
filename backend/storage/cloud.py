"""Cửa kho lưu trữ Supabase — cửa thứ hai, tách bạch với cửa gửi ra bên thứ ba.

Đây là module DUY NHẤT ngoài `security/gateway.py` được phép import
`security.providers`. Ngoại lệ này là CÓ CHỦ ĐÍCH và có invariant canh (C1b), không phải
chuyện lọt qua:

  `security/gateway.py`  →  cửa ra BÊN THỨ BA.        Nhật ký `egress_log`.
  `backend/storage/cloud.py`  →  cửa vào KHO CỦA CHÍNH ỨNG DỤNG.  Nhật ký `storage_events`.

Vì sao không dùng chung một cửa: hai thứ này cần hai câu trả lời khác nhau cho cùng một
câu hỏi. "Dữ liệu này có rời khỏi tổ chức không?" — với Gemini là CÓ, với kho riêng của
ứng dụng là KHÔNG. Ép chung một nhật ký thì hoặc mỗi lần lưu tệp lại hỏi xin phép gửi ra
ngoài, hoặc nhật ký gửi-ra-ngoài đầy dòng lưu trữ nội bộ và việc gửi cho Gemini chìm
trong đó. Cả hai đều làm nhật ký kém tin cậy đúng lúc cần nhất.

Chuyên gia VẪN phải được báo là tệp rời khỏi thiết bị — đó là việc của lớp đồng ý tải
lên, không phải của `egress_log`.
"""

from __future__ import annotations

from backend.config import settings
from backend.storage.base import ObjectInfo, ObjectNotFound, StorageError, UploadTicket


class SupabaseStorage:
    """Kho riêng trên Supabase. CHƯA từng chạy với credential thật — xem provider."""

    name = "supabase"

    def __init__(self) -> None:
        # Import muộn: bản chạy trên máy cá nhân không cần `httpx`, và nạp sớm thì
        # invariant C1a bắt được ở đúng chỗ nhưng lại kéo thư viện vào lúc khởi động.
        from backend.security.providers import supabase_storage as provider

        if not (settings.supabase_url and settings.supabase_service_key):
            raise StorageError(
                "Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_ROLE_KEY. Không có thì KHÔNG "
                "dùng kho cloud — thà dừng còn hơn ghi tệp vào một nơi không ai biết."
            )
        self._p = provider
        self._cfg = provider.Config(
            url=settings.supabase_url,
            service_key=settings.supabase_service_key,
            bucket=settings.supabase_bucket,
        )

    def create_upload_ticket(
        self, key: str, *, content_type: str, max_bytes: int, ttl_sec: int = 900
    ) -> UploadTicket:
        from datetime import datetime, timedelta, timezone

        signed = self._p.create_signed_upload_url(self._cfg, key)
        return UploadTicket(
            key=key,
            url=str(signed["signed_url"]),
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=ttl_sec)).isoformat(),
            max_bytes=max_bytes,
        )

    def stat(self, key: str) -> ObjectInfo | None:
        info = self._p.stat(self._cfg, key)
        if info is None:
            return None
        return ObjectInfo(
            key=key,
            size_bytes=int(info["size_bytes"]),
            content_type=info.get("content_type"),
            # Supabase không trả SHA256 qua HEAD. Bước chốt tự tính lại từ nội dung —
            # xem `storage/service.py`. Để `None` ở đây là nói đúng: CHƯA biết.
            sha256=None,
        )

    def download(self, key: str) -> bytes:
        data = self._p.download(self._cfg, key)
        if not data:
            raise ObjectNotFound(f"không có đối tượng {key!r}")
        return data

    def delete(self, key: str) -> bool:
        return self._p.delete(self._cfg, [key]) > 0

    def delete_prefix(self, prefix: str) -> int:
        """Xoá mọi đối tượng dưới một tiền tố. Trả về số THẬT SỰ bị xoá.

        Supabase không có lệnh "xoá theo tiền tố", nên phải liệt kê rồi xoá. Đếm theo
        thứ máy chủ báo về, KHÔNG theo số khoá đã gửi — đó là chỗ "đã xoá toàn bộ" trở
        thành lời nói dối khi một khoá bị từ chối.
        """
        items = self._p.list_prefix(self._cfg, prefix)
        keys = [f"{prefix.rstrip('/')}/{i['name']}" for i in items if i.get("name")]
        return self._p.delete(self._cfg, keys) if keys else 0

    def signed_download_url(self, key: str, *, ttl_sec: int = 300) -> str:
        return self._p.create_signed_download_url(self._cfg, key, ttl_sec)
