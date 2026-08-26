"""Cấu hình chung cho pytest.

Hai việc:

1. **Ép UTF-8 cho đầu ra.** Toàn bộ thông báo test của dự án viết bằng tiếng Việt, mà
   stdout mặc định trên Windows là cp1252 — pytest sẽ escape dấu thành `\\u1ea1` và
   thông báo thành vô dụng đúng lúc cần đọc nhất.

2. **Tách test khỏi dữ liệu thật.** Các test invariant có ghi vào cơ sở dữ liệu (dòng
   nhật ký egress, bản ghi thao tác). Chúng KHÔNG được đụng tới `data/app.db` — trong
   đó là hồ sơ khách hàng thật. Mỗi phiên test chạy trên một thư mục dữ liệu tạm.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest


def pytest_configure() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@pytest.fixture(scope="session", autouse=True)
def temp_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Trỏ mọi đường ghi của ứng dụng vào thư mục tạm, rồi tạo schema.

    Đặt `autouse` + `scope="session"` và chạy TRƯỚC mọi test: nếu một test lỡ mở kết nối
    trước khi fixture này chạy, nó sẽ mở đúng vào cơ sở dữ liệu thật.
    """
    from backend.config import settings
    from backend.db import init_db

    root = tmp_path_factory.mktemp("rag_test_data")
    # `settings` là dataclass frozen — cố ý, để mã chạy không đổi cấu hình giữa chừng.
    # Test là ngoại lệ hợp lệ duy nhất, nên đi cửa sau một cách có chủ đích.
    paths = {
        "data_dir": root,
        "db_path": root / "app.db",
        "chroma_dir": root / "chroma",
        "documents_dir": root / "documents",
        "tts_cache_dir": root / "tts_cache",
        "recordings_dir": root / "recordings",
    }
    for name, value in paths.items():
        if hasattr(settings, name):
            object.__setattr__(settings, name, value)
    settings.ensure_dirs()

    init_db()
    return root


def _new_workspace(name_prefix: str, confidential: int) -> int:
    """`workspaces.name` là UNIQUE, nên mỗi test phải có hồ sơ mang tên riêng."""
    from backend.db import get_conn

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO workspaces (name, is_confidential) VALUES (?, ?)",
            (f"{name_prefix} {uuid.uuid4().hex[:8]}", confidential),
        )
    return int(cur.lastrowid or 0)


@pytest.fixture()
def workspace(temp_data_dir: Path) -> int:
    """Một hồ sơ thường (không mật)."""
    return _new_workspace("Hồ sơ thử", 0)


@pytest.fixture()
def secret_workspace(temp_data_dir: Path) -> int:
    """Một hồ sơ đã bật cờ mật — mọi lần gửi ra ngoài phải xin phép."""
    return _new_workspace("Hồ sơ mật thử", 1)
