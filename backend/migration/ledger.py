"""Sổ cái các lần chuyển dữ liệu — trả lời "trạng thái cloud này dựng từ ảnh chụp nào".

Không có sổ này thì sau vài tháng không ai biết dữ liệu trên cloud tương ứng với lần
chạy local nào, và một lần chạy lại không phân biệt được với lần đầu.

Lần chạy HỎNG phải phân biệt được với lần chạy XONG. Ghi mọi lần chạy là `completed`
rồi mới cập nhật là mất đúng thông tin cần nhất lúc đi tìm nguyên nhân.
"""

from __future__ import annotations

import json
from typing import Any

from backend.database import driver
from backend.db import get_conn

DDL = """
CREATE TABLE IF NOT EXISTS migration_runs (
    id                 %(pk)s,
    source_fingerprint TEXT    NOT NULL,
    source_git_commit  TEXT    NOT NULL,
    owner_user_id      TEXT,
    started_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at       TEXT,
    -- 'running' | 'completed' | 'failed'. Không có mặc định 'completed': một lần chạy
    -- bị giết giữa chừng phải để lại dấu vết là nó chưa xong.
    status             TEXT    NOT NULL DEFAULT 'running',
    summary_json       TEXT,
    error_class        TEXT,
    tool_version       TEXT
)
"""

TOOL_VERSION = "phase6.1"


def ensure_table() -> None:
    pk = "BIGSERIAL PRIMARY KEY" if driver.is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    sql = DDL % {"pk": pk}
    if driver.is_postgres():
        from backend.database.dialect import ddl_to_postgres

        sql = ddl_to_postgres(sql)
    with get_conn() as conn:
        conn.execute(sql)
    driver.reset_table_cache()


def start(fingerprint: str, git_commit: str, owner_user_id: str | None) -> int:
    ensure_table()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO migration_runs (source_fingerprint, source_git_commit, "
            "owner_user_id, tool_version) VALUES (?, ?, ?, ?)",
            (fingerprint, git_commit, owner_user_id, TOOL_VERSION),
        )
        return int(cur.lastrowid or 0)


def finish(run_id: int, summary: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE migration_runs SET status = 'completed', completed_at = datetime('now'), "
            "summary_json = ? WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False), run_id),
        )


def fail(run_id: int, exc: BaseException, summary: dict[str, Any] | None = None) -> None:
    """Ghi lại lần chạy hỏng.

    Chỉ ghi TÊN LỚP lỗi, không ghi nội dung: nội dung lỗi có thể chứa mẩu dữ liệu khách
    hàng hoặc chuỗi kết nối, mà sổ này thì đọc được từ ứng dụng.
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE migration_runs SET status = 'failed', completed_at = datetime('now'), "
            "error_class = ?, summary_json = ? WHERE id = ?",
            (type(exc).__name__, json.dumps(summary or {}, ensure_ascii=False), run_id),
        )


def last_completed(fingerprint: str | None = None) -> dict[str, Any] | None:
    ensure_table()
    sql = "SELECT * FROM migration_runs WHERE status = 'completed'"
    params: tuple[Any, ...] = ()
    if fingerprint:
        sql += " AND source_fingerprint = ?"
        params = (fingerprint,)
    sql += " ORDER BY id DESC LIMIT 1"
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def history(limit: int = 20) -> list[dict[str, Any]]:
    ensure_table()
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, source_fingerprint, source_git_commit, owner_user_id, "
                "started_at, completed_at, status, error_class FROM migration_runs "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
