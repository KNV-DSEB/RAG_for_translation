"""Kết nối cơ sở dữ liệu — SQLite (máy cá nhân) hoặc PostgreSQL (cloud).

Vào:  `DATABASE_URL` trong môi trường. Có thì dùng PostgreSQL, không thì SQLite.
Ra:   một connection có `.execute(sql, params)` trả cursor kiểu SQLite.

Mã nghiệp vụ KHÔNG được biết mình đang chạy trên cơ sở dữ liệu nào. Nó viết SQL theo
phương ngữ SQLite; `dialect.py` dịch, tệp này che khác biệt về driver:

  - hàng trả về là ánh xạ (dùng được `row["ten"]` và `dict(row)`) trên cả hai
  - `cur.lastrowid` chạy được trên cả hai — Postgres không có, nên với INSERT ta tự thêm
    `RETURNING id` rồi đọc lại. 18 chỗ trong mã đang dùng `lastrowid`.
  - `cur.rowcount` giữ nguyên nghĩa

Vì sao không dùng ORM: mã hiện tại có 159 lệnh `execute` viết bằng SQL thật, và các
invariant về ngân sách/consent phụ thuộc vào câu lệnh chính xác (ví dụ `UPDATE ... WHERE
used_calls < allowed_calls` phải là MỘT câu, không đọc-rồi-ghi). Đưa ORM vào là viết lại
toàn bộ phần đó mà không thu được bảo đảm nào tốt hơn.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Iterable, Sequence

from backend.database import dialect

# Nhận diện INSERT để biết có cần thêm `RETURNING id` không.
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+\"?(\w+)\"?", re.IGNORECASE)
_HAS_RETURNING = re.compile(r"\bRETURNING\b", re.IGNORECASE)


class _PgCursor:
    """Bọc cursor psycopg cho giống cursor sqlite3 ở đúng những chỗ mã đang dùng."""

    __slots__ = ("_cur", "_lastrowid")

    def __init__(self, cur: Any, lastrowid: int | None = None) -> None:
        self._cur = cur
        self._lastrowid = lastrowid

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    def __iter__(self) -> Any:
        return iter(self._cur)


# Bảng nào có cột `id` thì mới thêm được `RETURNING id`. Không phải bảng nào cũng có:
# `operation_calls` khoá theo (operation_id, destination, provider), không có khoá thay
# thế. Thử rồi bắt lỗi thì không dùng được — trên PostgreSQL, một câu lệnh hỏng làm hỏng
# cả giao dịch, nên phải biết TRƯỚC. Tra một lần rồi nhớ.
_TABLES_WITH_ID: set[str] | None = None
_tables_lock = threading.Lock()


def _tables_with_id(conn: Any) -> set[str]:
    global _TABLES_WITH_ID
    if _TABLES_WITH_ID is None:
        with _tables_lock:
            if _TABLES_WITH_ID is None:
                cur = conn.cursor()
                cur.execute(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'id'"
                )
                _TABLES_WITH_ID = {
                    (r["table_name"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()
                }
    return _TABLES_WITH_ID


def reset_table_cache() -> None:
    """Quên bộ nhớ đệm sau khi schema đổi (tạo bảng, chạy migration)."""
    global _TABLES_WITH_ID
    with _tables_lock:
        _TABLES_WITH_ID = None


class PostgresConnection:
    """Kết nối PostgreSQL nói được giao diện mà mã hiện tại đang gọi."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> _PgCursor:
        translated = dialect.to_postgres(sql)
        args = tuple(params or ())

        # `lastrowid` không có trong Postgres. Với INSERT chưa có RETURNING, thêm
        # `RETURNING id` để lấy khoá vừa sinh — 18 chỗ trong mã dựa vào giá trị này.
        match = _INSERT_RE.match(translated)
        want_id = bool(match) and not _HAS_RETURNING.search(translated)
        if want_id and match is not None:
            want_id = match.group(1).lower() in _tables_with_id(self._conn)
        if want_id:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"

        cur = self._conn.cursor()
        try:
            cur.execute(translated, args)
        except Exception as exc:                       # noqa: BLE001 — cần gắn thêm ngữ cảnh
            raise _with_sql_context(exc, translated) from exc

        new_id: int | None = None
        if want_id:
            row = cur.fetchone()
            if row is not None:
                new_id = row["id"] if isinstance(row, dict) else row[0]
        return _PgCursor(cur, new_id)

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> None:
        cur = self._conn.cursor()
        cur.executemany(dialect.to_postgres(sql), list(seq))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _with_sql_context(exc: Exception, sql: str) -> Exception:
    """Gắn câu SQL đã dịch vào lỗi.

    Không kèm tham số: chúng có thể chứa nội dung tài liệu khách hàng, và thông báo lỗi
    thì đi vào log của nền tảng (spec §7 — không ghi nội dung tài liệu ra stdout).
    """
    one_line = " ".join(sql.split())[:400]
    return type(exc)(f"{exc}\n  SQL đã dịch: {one_line}")


# ============================== Chọn driver ==============================

_pool: Any = None
_pool_lock = threading.Lock()


def database_url() -> str | None:
    from backend.config import settings

    return settings.database_url


def is_postgres() -> bool:
    return bool(database_url())


def _get_pool() -> Any:
    """Pool kết nối. Mở kết nối mới cho mỗi request thì độ trễ tới Supabase cộng dồn."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                from psycopg.rows import dict_row

                _pool = ConnectionPool(
                    conninfo=database_url() or "",
                    min_size=1,
                    max_size=8,
                    kwargs={"row_factory": dict_row, "autocommit": False},
                    open=True,
                )
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def connect_sqlite() -> sqlite3.Connection:
    from backend.config import settings

    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def is_unique_violation(exc: BaseException) -> bool:
    """Lỗi trùng khoá, nhận diện được trên cả hai cơ sở dữ liệu.

    `except sqlite3.IntegrityError` chỉ đúng trên SQLite. Trên PostgreSQL, psycopg ném
    `UniqueViolation` — cùng ý nghĩa, khác lớp hoàn toàn. Bắt nhầm lớp thì lỗi trùng tên
    hồ sơ biến thành 500 thay vì 409, và người dùng nhận được thông báo vô nghĩa.
    """
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    # Không import psycopg ở đầu tệp: bản chạy trên máy cá nhân không cài nó.
    try:
        from psycopg import errors as pg_errors
    except ImportError:
        return False
    return isinstance(exc, pg_errors.UniqueViolation)
