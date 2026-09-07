"""Bản đồ dữ liệu: từng loại dữ liệu THẬT SỰ nằm ở đâu, sinh từ cấu hình đang chạy.

Vì sao phải sinh từ cấu hình chứ không viết tay
----------------------------------------------
Màn Bảo mật từng có một câu viết cứng: *"Nhúng embedding, vector DB, nhận dạng giọng nói
và cơ sở dữ liệu đều chạy trên máy này."* Câu đó mắc BA lỗi cùng lúc:

  1. "nhận dạng giọng nói" đã bị gỡ khỏi dự án từ lâu — sai ngay cả trên bản chạy local;
  2. trên cloud, cơ sở dữ liệu nằm ở Supabase, không phải "máy này";
  3. trên cloud, vector nằm trong pgvector, cũng ở Supabase.

Một câu viết tay không thể tự đúng khi kiến trúc đổi. Nên nó phải được SINH RA từ chính
cấu hình quyết định nơi dữ liệu nằm — cùng nguyên tắc đã dùng cho `scope_note` (sinh từ
`declares`) và `session_scope_label` (sinh từ chế độ chạy).

Ba mức `boundary`, và chúng KHÁC nhau
-------------------------------------
  `device`      nằm trên chính máy đang chạy tiến trình này
  `app_cloud`   nằm trên hạ tầng của ứng dụng (Supabase) — đã rời thiết bị, chưa sang bên thứ ba
  `third_party` gửi sang tổ chức khác

Gộp `app_cloud` vào `device` là nói dối chuyên gia. Gộp nó vào `third_party` là làm nhật
ký gửi-ra-ngoài mất tác dụng. Ba mức, không phải hai.
"""

from __future__ import annotations

from typing import Any

from backend.config import settings


def _db_location() -> dict[str, Any]:
    if settings.database_url:
        return {
            "what": "Cơ sở dữ liệu",
            "detail": "hồ sơ, thuật ngữ, lịch sử buổi mock, nhật ký",
            "where": "PostgreSQL trên Supabase",
            "boundary": "app_cloud",
        }
    return {
        "what": "Cơ sở dữ liệu",
        "detail": "hồ sơ, thuật ngữ, lịch sử buổi mock, nhật ký",
        "where": "SQLite trên máy này",
        "boundary": "device",
    }


def _vector_location() -> dict[str, Any]:
    if settings.database_url:
        return {
            "what": "Chỉ mục ngữ nghĩa",
            "detail": "vector dùng để tìm đoạn tài liệu liên quan",
            "where": "pgvector trong PostgreSQL trên Supabase",
            "boundary": "app_cloud",
        }
    return {
        "what": "Chỉ mục ngữ nghĩa",
        "detail": "vector dùng để tìm đoạn tài liệu liên quan",
        "where": "ChromaDB trên máy này",
        "boundary": "device",
    }


def _document_location() -> dict[str, Any]:
    from backend.storage import is_cloud_storage

    if is_cloud_storage():
        return {
            "what": "Tệp tài liệu",
            "detail": "bản gốc tài liệu bạn tải lên",
            "where": f"kho riêng trên Supabase (bucket `{settings.supabase_bucket}`, không công khai)",
            "boundary": "app_cloud",
        }
    return {
        "what": "Tệp tài liệu",
        "detail": "bản gốc tài liệu bạn tải lên",
        "where": "thư mục trên máy này",
        "boundary": "device",
    }


def data_map() -> list[dict[str, Any]]:
    """Nơi từng loại dữ liệu đang nằm. Không có mục nào viết cứng."""
    return [
        _document_location(),
        _db_location(),
        _vector_location(),
        {
            # Đây là mục DUY NHẤT luôn ở `device`, và nó đúng ở cả hai chế độ: model
            # embedding chạy trong chính tiến trình backend, không gọi API nào.
            "what": "Tạo vector (embedding)",
            "detail": "mô hình chạy trong tiến trình backend, không gọi dịch vụ ngoài",
            "where": "máy chạy backend",
            "boundary": "device",
        },
        {
            "what": "Gọi mô hình ngôn ngữ",
            "detail": "chỉ các đoạn ngữ cảnh đã truy hồi, không bao giờ cả tài liệu",
            "where": "Gemini (Google)",
            "boundary": "third_party",
        },
        {
            "what": "Truy vấn tìm kiếm",
            "detail": "chuỗi truy vấn, có chứa tên khách hàng và chủ đề",
            "where": "DuckDuckGo",
            "boundary": "third_party",
        },
        {
            "what": "Đọc lời thoại",
            "detail": "văn bản lời thoại. Lần nghe lại lấy từ cache thì không gọi mạng",
            "where": "edge-tts (Microsoft), dự phòng gTTS (Google)",
            "boundary": "third_party",
        },
    ]


def headline() -> str:
    """Câu tóm tắt, cũng sinh từ cấu hình.

    Bản local nói được "mọi thứ ở trên máy này trừ ba đường ra ngoài". Bản cloud KHÔNG
    nói được câu đó, và giữ nguyên nó là nói dối theo chiều nguy hiểm nhất: chuyên gia
    tin rằng tài liệu khách hàng vẫn nằm trong tầm tay mình.
    """
    rows = data_map()
    n_cloud = sum(1 for r in rows if r["boundary"] == "app_cloud")
    n_third = sum(1 for r in rows if r["boundary"] == "third_party")

    if n_cloud == 0:
        return (
            f"Mọi dữ liệu nằm trên máy này. Có đúng {n_third} đường gửi ra ngoài, "
            "và cả ba đều được ghi nhật ký."
        )
    return (
        f"Dữ liệu của bạn nằm trên hạ tầng riêng của ứng dụng ({n_cloud} loại), "
        f"KHÔNG còn chỉ ở máy bạn. Ngoài ra có {n_third} đường gửi sang dịch vụ của "
        "bên thứ ba, và cả ba đều phải xin phép rồi mới gửi."
    )
