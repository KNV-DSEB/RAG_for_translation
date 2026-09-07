"""Kho lưu trữ tài liệu: chọn hiện thực theo cấu hình đang chạy."""

from __future__ import annotations

import threading
from typing import Any

from backend.config import settings

_backend: Any = None
_lock = threading.Lock()


def get_backend() -> Any:
    """Kho đang dùng. Supabase khi có cấu hình, không thì thư mục trên đĩa.

    Không có cờ "chế độ cloud" riêng: một cờ có thể lệch với thực tế, sự hiện diện của
    cấu hình Supabase thì không.
    """
    global _backend
    if _backend is None:
        with _lock:
            if _backend is None:
                if settings.supabase_url and settings.supabase_service_key:
                    from backend.storage.cloud import SupabaseStorage

                    _backend = SupabaseStorage()
                else:
                    from backend.storage.local import LocalStorage

                    settings.ensure_dirs()
                    _backend = LocalStorage(settings.documents_dir.parent / "objects")
    return _backend


def reset_backend() -> None:
    """Quên kho đang nhớ. Dùng khi test đổi cấu hình."""
    global _backend
    with _lock:
        _backend = None


def is_cloud_storage() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)
