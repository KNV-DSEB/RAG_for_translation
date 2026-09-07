"""Giao diện kho lưu trữ tài liệu — một hình dạng, hai cách hiện thực.

HAI HẠNG MỤC ĐƯỜNG MẠNG, ĐỪNG GỘP
----------------------------------
Trước đợt cloud, CLAUDE.md nói hệ thống có "đúng ba đường dữ liệu ra khỏi máy": LLM,
tìm kiếm, đọc lời thoại. Câu đó đúng khi mọi thứ chạy trên máy cá nhân.

Lên cloud thì nó không còn đúng, và đã không còn đúng TỪ LÚC thêm PostgreSQL — `psycopg`
mở kết nối mạng tới Supabase, mà invariant C1a không hề thấy vì `psycopg` không nằm
trong danh sách thư viện nó canh. Kho lưu trữ này là đường thứ hai cùng loại.

Nên phải phân hai hạng mục, và giữ chúng tách bạch:

  **Bên thứ ba** — Gemini, DuckDuckGo, edge-tts, gTTS.
  Dữ liệu rời khỏi ranh giới tin cậy của ứng dụng, sang tổ chức khác. Bắt buộc qua
  `security/gateway.py`, ghi vào `egress_log`, hồ sơ mật phải xin phép trước.

  **Hạ tầng của chính ứng dụng** — PostgreSQL, Supabase Storage.
  Vẫn là mạng, nhưng đây là nơi ứng dụng CẤT dữ liệu của chính nó, không phải nơi nó
  gửi dữ liệu đi. Có nhật ký riêng (`storage_events`), KHÔNG trộn vào `egress_log`.

Gộp hai thứ này lại sẽ hỏng theo cả hai chiều: hoặc mỗi lần lưu tệp lại hỏi xin phép
gửi ra ngoài (vô nghĩa, và làm chuyên gia quen tay bấm đồng ý), hoặc nhật ký "gửi ra
ngoài" đầy dòng lưu trữ nội bộ khiến việc gửi cho Gemini chìm trong đó.

Chuyên gia vẫn phải được báo là tệp rời khỏi thiết bị — đó là việc của lớp đồng ý tải
lên (Phase 8), không phải của `egress_log`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class StorageError(RuntimeError):
    """Thao tác với kho lưu trữ hỏng."""


class ObjectNotFound(StorageError):
    pass


@dataclass(frozen=True)
class UploadTicket:
    """Giấy phép tải lên MỘT đối tượng, do máy chủ phát.

    Trình duyệt nhận `url` và gửi thẳng tệp tới đó — KHÔNG đi vòng qua backend. Tệp
    100 MB đi qua backend là chiếm bộ nhớ và thời gian của tiến trình đang phục vụ mọi
    người, mà không đổi lại được bảo đảm nào.

    `key` do MÁY CHỦ đặt và nằm trong giấy phép. Trình duyệt không chọn được nơi ghi.
    """

    key: str
    url: str
    method: str
    headers: dict[str, str]
    expires_at: str
    max_bytes: int


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size_bytes: int
    sha256: str | None = None
    content_type: str | None = None


@runtime_checkable
class StorageBackend(Protocol):
    """Hình dạng chung của mọi kho lưu trữ.

    Hai hiện thực:
      `LocalStorage`     — thư mục trên đĩa. Dùng khi chạy trên máy cá nhân và khi test.
      `SupabaseStorage`  — bucket riêng trên Supabase. Dùng khi chạy trên cloud.

    `LocalStorage` KHÔNG phải bản giả lập Supabase. Nó là kho thật của bản chạy local,
    nên nó kiểm được luồng (giấy phép → tải lên → chốt) chứ không kiểm được rằng
    Supabase hành xử đúng như tài liệu của họ mô tả. Phân biệt này phải giữ trong mọi
    báo cáo: chạy hết test không có nghĩa là đã kiểm chứng Supabase.
    """

    name: str

    def create_upload_ticket(
        self, key: str, *, content_type: str, max_bytes: int, ttl_sec: int = 900
    ) -> UploadTicket: ...

    def stat(self, key: str) -> ObjectInfo | None: ...

    def download(self, key: str) -> bytes: ...

    def delete(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def signed_download_url(self, key: str, *, ttl_sec: int = 300) -> str: ...
