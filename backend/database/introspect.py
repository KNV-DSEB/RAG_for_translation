"""Đọc cấu trúc cơ sở dữ liệu — SQLite dùng `PRAGMA`, PostgreSQL dùng `information_schema`.

Đây là ba chỗ DUY NHẤT trong toàn bộ mã mà hai phương ngữ không thể dùng chung một câu
lệnh. Gom lại đây thay vì rải `if is_postgres()` khắp `db.py`.
"""

from __future__ import annotations

from typing import Any

from backend.database import driver


def table_columns(conn: Any, table: str) -> set[str]:
    """Tên các cột hiện có của một bảng. Bảng chưa tồn tại thì trả về tập rỗng."""
    if driver.is_postgres():
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ?",
            (table,),
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def table_names(conn: Any) -> list[str]:
    """Danh sách bảng, sắp xếp theo tên — dùng để nghiệm thu schema."""
    if driver.is_postgres():
        rows = conn.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [str(row["name"]) for row in rows]
