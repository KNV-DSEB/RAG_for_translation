"""Lớp truy cập SQLite: kết nối, schema, và tiện ích truy vấn.

Input:  không (đọc đường dẫn DB từ `config.settings`).
Output: connection đã bật foreign_keys + WAL, và hàm `init_db()` tạo đủ bảng.

Thiết kế: ChromaDB giữ vector, còn SQLite giữ TOÀN BỘ văn bản gốc + vị trí trích dẫn.
Nhờ vậy trích dẫn luôn trỏ được về đúng đoạn trong đúng tệp (spec A1.3) mà không
phụ thuộc vào metadata của vector store.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from backend.config import settings

# Mỗi phần tử là một câu CREATE. Chạy tuần tự, idempotent.
_SCHEMA: tuple[str, ...] = (
    # ================= Hồ sơ khách hàng & buổi làm việc =================
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        name             TEXT    NOT NULL UNIQUE,
        industry         TEXT,
        -- Cờ mật: bật thì mọi lần gửi dữ liệu ra ngoài phải xin đồng ý trước (spec §7.2)
        is_confidential  INTEGER NOT NULL DEFAULT 0,
        notes            TEXT,
        created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS engagements (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id  INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        topic         TEXT    NOT NULL,
        partners      TEXT,   -- JSON: danh sách tên đối tác
        event_date    TEXT,
        notes         TEXT,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ================= Module 1: tài liệu =================
    """
    CREATE TABLE IF NOT EXISTS documents (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id        INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        filename            TEXT    NOT NULL,
        stored_path         TEXT    NOT NULL,
        ext                 TEXT    NOT NULL,
        size_bytes          INTEGER NOT NULL DEFAULT 0,
        content_hash        TEXT,   -- chống nạp trùng cùng nội dung
        -- 'vi' | 'en' | 'parallel' (song ngữ song song) | 'mixed' | 'unknown'
        language            TEXT    NOT NULL DEFAULT 'unknown',
        language_source     TEXT    NOT NULL DEFAULT 'auto',   -- 'auto' | 'manual'
        -- 'ok' | 'low': lớp fallback đọc .doc cho ra chất lượng thấp thì phải cảnh báo
        extraction_quality  TEXT    NOT NULL DEFAULT 'ok',
        extractor           TEXT,   -- word_com | ole_fallback | pypdf | python_docx | plain
        -- pending | extracting | chunking | indexing | ready | error
        status              TEXT    NOT NULL DEFAULT 'pending',
        error_message       TEXT,
        n_chars             INTEGER NOT NULL DEFAULT 0,
        n_chunks            INTEGER NOT NULL DEFAULT 0,
        created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        workspace_id  INTEGER NOT NULL,
        chunk_index   INTEGER NOT NULL,
        text          TEXT    NOT NULL,
        locator       TEXT,   -- ví dụ "trang 3" hoặc "đoạn 12" — dùng để hiện trích dẫn
        lang          TEXT,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_ws ON document_chunks(workspace_id)",
    """
    CREATE TABLE IF NOT EXISTS qa_history (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id   INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        question       TEXT    NOT NULL,
        answer         TEXT,
        citations      TEXT,   -- JSON: [{document_id, filename, locator, snippet}]
        inference_part TEXT,   -- phần suy luận, tách khỏi phần có trong tài liệu (spec A1.6)
        confidence     TEXT,   -- 'ok' | 'weak_context' | 'not_found'
        created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ================= Module 2: research & glossary =================
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id   INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        engagement_id  INTEGER REFERENCES engagements(id) ON DELETE SET NULL,
        client_name    TEXT    NOT NULL,
        partner_names  TEXT,   -- JSON
        topic          TEXT    NOT NULL,
        industry       TEXT,
        extra_notes    TEXT,
        queries_used   TEXT,   -- JSON: các truy vấn đã thực sự gửi đi
        n_queries      INTEGER NOT NULL DEFAULT 0,
        n_sources      INTEGER NOT NULL DEFAULT 0,
        n_terms        INTEGER NOT NULL DEFAULT 0,
        status         TEXT    NOT NULL DEFAULT 'running',  -- running|done|partial|error
        error_message  TEXT,
        created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profiles (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id     INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        research_run_id  INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
        entity_name      TEXT    NOT NULL,
        entity_role      TEXT    NOT NULL,  -- 'client' | 'partner'
        created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    -- Mỗi TRƯỜNG là một dòng riêng để gắn nguồn riêng cho từng thông tin (spec A2.4).
    CREATE TABLE IF NOT EXISTS profile_fields (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id       INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        field_key        TEXT    NOT NULL,
        value            TEXT,
        is_verified      INTEGER NOT NULL DEFAULT 0,  -- 0 = chưa xác minh, phải đánh dấu rõ
        is_expert_edited INTEGER NOT NULL DEFAULT 0,  -- sửa tay thì lần research sau không ghi đè
        created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile_sources (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_field_id  INTEGER NOT NULL REFERENCES profile_fields(id) ON DELETE CASCADE,
        url               TEXT    NOT NULL,
        title             TEXT,
        published_at      TEXT,   -- hiện ngày nguồn để chuyên gia tự đánh giá độ mới
        snippet           TEXT,
        -- Trạng thái mở được của liên kết, kiểm ngay lúc nghiên cứu:
        -- 'ok' | 'dead' (không truy cập được) | 'unchecked'.
        -- Link chết làm mất tính truy vết, nên phải nói trước thay vì để chuyên gia
        -- bấm vào giữa lúc chuẩn bị mới phát hiện (spec A2.4).
        reachable         TEXT    NOT NULL DEFAULT 'unchecked'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS glossary (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id   INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        term_vi        TEXT    NOT NULL,
        term_vi_norm   TEXT    NOT NULL,  -- chuẩn hoá để chống trùng
        term_en        TEXT    NOT NULL,
        pronunciation  TEXT,   -- cách đọc tên riêng/viết tắt (Q6), dùng cho cả TTS
        definition     TEXT,
        category       TEXT,
        -- 'human_translated' (từ tài liệu song ngữ) | 'machine_guess'
        confidence     TEXT    NOT NULL DEFAULT 'machine_guess',
        -- 'auto' (tự nhận, dùng được ngay - Q9) | 'expert_edited' | 'skipped'
        status         TEXT    NOT NULL DEFAULT 'auto',
        source_type    TEXT,   -- 'document' | 'web' | 'expert'
        source_ref     TEXT,   -- tên tệp + vị trí, hoặc URL
        frequency      INTEGER NOT NULL DEFAULT 1,
        created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at     TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE (workspace_id, term_vi_norm)
    )
    """,
    """
    -- Bản dịch mới khác bản cũ thì KHÔNG ghi đè, mà lưu ở đây cho chuyên gia chọn (spec A2.13).
    CREATE TABLE IF NOT EXISTS glossary_conflicts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        glossary_id         INTEGER NOT NULL REFERENCES glossary(id) ON DELETE CASCADE,
        proposed_term_en    TEXT    NOT NULL,
        proposed_definition TEXT,
        source_ref          TEXT,
        confidence          TEXT,
        resolved            INTEGER NOT NULL DEFAULT 0,
        created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ================= Module 3: mock buổi dịch =================
    """
    CREATE TABLE IF NOT EXISTS mock_sessions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        engagement_id   INTEGER REFERENCES engagements(id) ON DELETE SET NULL,
        mode            TEXT    NOT NULL DEFAULT 'consecutive',  -- consecutive|simultaneous
        difficulty      TEXT    NOT NULL DEFAULT 'medium',       -- basic|medium|hard
        n_turns         INTEGER NOT NULL DEFAULT 8,
        hide_script     INTEGER NOT NULL DEFAULT 1,              -- mặc định ẩn (Q10)
        glossary_scope  TEXT    NOT NULL DEFAULT 'all',
        script_json     TEXT,
        gen_warnings    TEXT,   -- JSON: ghi chú nếu sinh lại vẫn chưa đạt tiêu chí
        status          TEXT    NOT NULL DEFAULT 'generated',    -- generated|in_progress|completed|abandoned
        overall_score   REAL,
        started_at      TEXT,
        completed_at    TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mock_turns (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id             INTEGER NOT NULL REFERENCES mock_sessions(id) ON DELETE CASCADE,
        turn_index             INTEGER NOT NULL,
        speaker_name           TEXT,
        speaker_role           TEXT,
        source_lang            TEXT    NOT NULL,  -- 'vi' | 'en'
        target_lang            TEXT    NOT NULL,
        source_text            TEXT    NOT NULL,
        reference_translation  TEXT,
        -- 'human' (bản dịch người thật từ tài liệu song ngữ) | 'expert_pinned' | 'ai'
        reference_tier         TEXT    NOT NULL DEFAULT 'ai',
        terms_used             TEXT,   -- JSON: các glossary_id được dùng trong lượt
        tts_path               TEXT,   -- cache audio, nghe lại không sinh lại (A4.7)
        est_duration_sec       REAL,
        UNIQUE (session_id, turn_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS turn_attempts (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        turn_id            INTEGER NOT NULL REFERENCES mock_turns(id) ON DELETE CASCADE,
        session_id         INTEGER NOT NULL,
        recording_path     TEXT,   -- lưu lâu dài, có cơ chế xoá chủ động (Q11)
        transcript_raw     TEXT,
        transcript_edited  TEXT,   -- chấm theo bản ĐÃ SỬA (spec A3.14)
        input_mode         TEXT    NOT NULL DEFAULT 'speech',  -- 'speech' | 'typed'
        stt_quality        TEXT    NOT NULL DEFAULT 'ok',      -- 'ok' | 'low'
        replay_count       INTEGER NOT NULL DEFAULT 0,
        response_time_sec  REAL,
        created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scores (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id          INTEGER NOT NULL REFERENCES turn_attempts(id) ON DELETE CASCADE,
        -- Thang 10 điểm mỗi tiêu chí (Q3), trọng số bằng nhau ở mặc định
        score_meaning       REAL,
        score_terminology   REAL,
        score_completeness  REAL,
        score_expression    REAL,
        score_overall       REAL,
        comment             TEXT,
        term_verdicts       TEXT,   -- JSON: [{term_vi, expected_en, used, ok}]
        created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ================= §6: vòng phản hồi =================
    """
    -- Nhận định của chuyên gia về điểm AI đã chấm. Đây là dữ liệu hiệu chỉnh (spec §6).
    CREATE TABLE IF NOT EXISTS expert_verdicts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id          INTEGER NOT NULL REFERENCES turn_attempts(id) ON DELETE CASCADE,
        workspace_id        INTEGER NOT NULL,
        action              TEXT    NOT NULL,  -- agree|adjust|note|pin_translation
        score_meaning       REAL,
        score_terminology   REAL,
        score_completeness  REAL,
        score_expression    REAL,
        score_overall       REAL,
        note                TEXT,   -- chỉ nhận định CÓ lý do mới dùng để hiệu chỉnh
        related_category    TEXT,   -- để chọn lại theo phân loại thuật ngữ
        related_term_id     INTEGER REFERENCES glossary(id) ON DELETE SET NULL,
        pinned_translation  TEXT,   -- nâng bản dịch của chuyên gia thành tham chiếu ⭐⭐
        created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_verdicts_ws ON expert_verdicts(workspace_id)",
    # ================= §7: bảo mật =================
    """
    -- Ghi MỌI lần dữ liệu rời khỏi máy. Chuyên gia dùng bảng này để tự kiểm chứng
    -- cam kết "chỉ gửi đoạn ngữ cảnh, không gửi cả tài liệu" (spec A7.2, A7.3).
    CREATE TABLE IF NOT EXISTS egress_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id  INTEGER,
        module        TEXT    NOT NULL,
        destination   TEXT    NOT NULL,  -- 'llm' | 'search'
        endpoint      TEXT,
        n_chars       INTEGER NOT NULL DEFAULT 0,
        summary       TEXT,   -- tóm lược nội dung, KHÔNG chứa API key
        consented     INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_egress_ws ON egress_log(workspace_id, created_at)",
    """
    -- Vé đồng ý cho hồ sơ mật. Mặc định phạm vi 'session' để không hỏi lại liên tục (câu mở O3).
    CREATE TABLE IF NOT EXISTS consent_tickets (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id  INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        scope         TEXT    NOT NULL DEFAULT 'session',  -- 'session' | 'once'
        destination   TEXT,   -- NULL = áp dụng cho mọi đích
        granted_at    TEXT    NOT NULL DEFAULT (datetime('now')),
        expires_at    TEXT,
        used          INTEGER NOT NULL DEFAULT 0
    )
    """,
)


def connect() -> sqlite3.Connection:
    """Mở connection mới: bật foreign keys, WAL, và trả row dạng dict-like."""
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Context manager: tự commit khi thoát êm, rollback khi có lỗi."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Cột thêm sau khi bảng đã tồn tại. `CREATE TABLE IF NOT EXISTS` không thêm cột mới cho
# cơ sở dữ liệu cũ, nên cần bổ sung tay ở đây.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("profile_sources", "reachable", "TEXT NOT NULL DEFAULT 'unchecked'"),
)


def _ensure_columns(conn: sqlite3.Connection) -> list[str]:
    """Thêm các cột còn thiếu vào cơ sở dữ liệu đã tồn tại. Trả về danh sách cột vừa thêm."""
    added: list[str] = []
    for table, column, definition in _ADDED_COLUMNS:
        existing = {
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not existing:
            continue  # bảng chưa tồn tại, CREATE TABLE ở trên đã lo
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            added.append(f"{table}.{column}")
    return added


def init_db() -> list[str]:
    """Tạo toàn bộ bảng nếu chưa có. Trả về danh sách tên bảng hiện có để nghiệm thu."""
    with get_conn() as conn:
        for statement in _SCHEMA:
            conn.execute(statement)
        _ensure_columns(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [row["name"] for row in rows]


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(sql: str, params: tuple[Any, ...] = ()) -> int:
    """Chạy INSERT/UPDATE/DELETE. Trả lastrowid (INSERT) hoặc số dòng bị ảnh hưởng."""
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid if cur.lastrowid else cur.rowcount
