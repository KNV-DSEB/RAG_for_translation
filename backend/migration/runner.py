"""Chuyển dữ liệu bền từ SQLite trên máy sang PostgreSQL + pgvector.

Vào:  SQLite nguồn (chỉ đọc) + `owner_user_id` là UUID thật của Supabase Auth.
Ra:   dữ liệu trên PostgreSQL, vector trong pgvector, một dòng trong sổ cái.

Bốn tính chất phải giữ, và cách giữ chúng
-----------------------------------------
**Không phá nguồn.** SQLite mở bằng `mode=ro` nên hệ điều hành tự chặn, không dựa vào
việc mã không viết lệnh ghi nào. Tệp tài liệu không bị đụng tới.

**Chạy lại được.** Mỗi bảng ghi bằng UPSERT theo khoá chính, GIỮ NGUYÊN id gốc. Chạy
lần hai cho đúng số dòng của lần một, không nhân đôi. Không dùng "có rồi thì bỏ qua":
kiểu đó bỏ sót thay đổi ở nguồn, và im lặng để lại dữ liệu cũ trên cloud.

**Hỏng thì dừng, không hỏng nửa vời im lặng.** Mỗi bảng nằm trong một giao dịch riêng.
Hỏng giữa chừng thì những bảng đã xong vẫn đúng, sổ cái ghi `failed`, và chạy lại tiếp
tục được vì UPSERT không quan tâm dòng đã có hay chưa.

**Không diễn giải lại dữ liệu.** Nhãn tin cậy (`has_source`, `is_expert_edited`,
`reference_tier`, `confidence`) và trạng thái nhật ký (`blocked`, `attempt_succeeded`,
`attempt_failed`) chuyển nguyên trạng. Nâng `has_source` thành "đã xác minh", hay đổi
`attempt_failed` thành `blocked`, đều là tuyên bố một điều không ai chứng minh được.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.database import driver
from backend.db import get_conn
from backend.migration import inventory, ledger
from backend.migration.spec import DURABLE, RUNTIME_SKIPPED, Entity


class MigrationError(RuntimeError):
    pass


@dataclass
class TableResult:
    table: str
    source_rows: int
    written: int
    skipped: int = 0
    note: str = ""


@dataclass
class MigrationResult:
    run_id: int | None
    fingerprint: str
    owner_user_id: str
    dry_run: bool
    tables: list[TableResult] = field(default_factory=list)
    chunks_embedded: int = 0
    documents_inventoried: int = 0
    runtime_skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "fingerprint": self.fingerprint,
            "owner_user_id": self.owner_user_id,
            "dry_run": self.dry_run,
            "tables": [
                {"table": t.table, "source": t.source_rows, "written": t.written,
                 "skipped": t.skipped, "note": t.note}
                for t in self.tables
            ],
            "chunks_embedded": self.chunks_embedded,
            "documents_inventoried": self.documents_inventoried,
            # Tệp nhị phân KHÔNG được tải lên ở giai đoạn này. Con số 0 là sự thật, và
            # phải hiện ra trong báo cáo chứ không được ngầm hiểu.
            "documents_cloud_uploaded": 0,
            "runtime_skipped": self.runtime_skipped,
            "warnings": self.warnings,
        }


def _source_columns(src: sqlite3.Connection, table: str) -> list[str]:
    return [str(r["name"]) for r in src.execute(f"PRAGMA table_info({table})")]


def _target_columns(table: str) -> set[str]:
    from backend.database import introspect

    with get_conn() as conn:
        return introspect.table_columns(conn, table)


def _resync_sequence(table: str, pk: str) -> None:
    """Đưa bộ đếm khoá chính vượt qua id lớn nhất vừa chèn.

    Chèn id tường minh vào cột `BIGSERIAL` KHÔNG làm bộ đếm nhích lên. Bỏ qua bước này
    thì dòng mới đầu tiên do ứng dụng tạo sẽ đâm vào một id đã tồn tại — và lỗi chỉ nổ
    ra khi chuyên gia bấm "tạo hồ sơ", tức là sau khi đã bàn giao.
    """
    if not driver.is_postgres():
        return
    with get_conn() as conn:
        conn.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', '{pk}'), "
            f"COALESCE((SELECT MAX({pk}) FROM {table}), 0) + 1, false)"
        )


def _copy_table(
    src: sqlite3.Connection,
    ent: Entity,
    *,
    owner_user_id: str,
    dry_run: bool,
) -> TableResult:
    """Chép một bảng bằng UPSERT theo khoá chính, giữ nguyên id gốc."""
    cols_src = _source_columns(src, ent.table)
    if not cols_src:
        return TableResult(ent.table, 0, 0, note="không có ở nguồn")

    cols_dst = _target_columns(ent.table)
    # Chỉ chép cột có ở CẢ HAI bên. Cột chỉ có ở đích (`owner_user_id`, `user_id`) được
    # điền riêng bên dưới; cột chỉ có ở nguồn là tàn dư của schema cũ, bỏ qua có chủ đích.
    cols = [c for c in cols_src if c in cols_dst]
    dropped = [c for c in cols_src if c not in cols_dst]

    rows = src.execute(f'SELECT * FROM "{ent.table}" ORDER BY "{ent.pk}"').fetchall()
    if dry_run:
        note = f"bỏ cột không có ở đích: {', '.join(dropped)}" if dropped else ""
        return TableResult(ent.table, len(rows), 0, note=note)
    if not rows:
        return TableResult(ent.table, 0, 0)

    # `workspaces.owner_user_id` do MIGRATION đặt, không lấy từ nguồn — bản chạy local
    # không có khái niệm chủ sở hữu.
    extra: dict[str, Any] = {}
    if ent.table == "workspaces" and "owner_user_id" in cols_dst:
        extra["owner_user_id"] = owner_user_id

    # Cột do migration đặt phải bị LOẠI khỏi danh sách chép từ nguồn. Nguồn cũng có thể
    # đã có cột đó (cơ sở dữ liệu local đã nâng cấp lên schema mới), và khi đó nó sẽ xuất
    # hiện hai lần trong câu INSERT — PostgreSQL từ chối, migration dừng giữa chừng.
    # Giá trị ở nguồn luôn bị bỏ qua: chủ sở hữu do lần chuyển này quyết định, không phải
    # thứ thừa hưởng từ bản chạy trên máy.
    cols = [c for c in cols if c not in extra]

    insert_cols = cols + list(extra)
    placeholders = ", ".join("?" for _ in insert_cols)
    col_list = ", ".join(f'"{c}"' for c in insert_cols)
    updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in insert_cols if c != ent.pk)

    if driver.is_postgres():
        sql = (
            f'INSERT INTO "{ent.table}" ({col_list}) VALUES ({placeholders}) '
            f'ON CONFLICT ("{ent.pk}") DO UPDATE SET {updates} RETURNING {ent.pk}'
        )
    else:
        sql = (
            f'INSERT INTO "{ent.table}" ({col_list}) VALUES ({placeholders}) '
            f'ON CONFLICT ("{ent.pk}") DO UPDATE SET {updates}'
        )

    written = 0
    # Một giao dịch cho MỘT bảng. Hỏng ở giữa thì bảng đó không có dòng nào lửng lơ, mà
    # các bảng đã xong vẫn giữ nguyên — chạy lại là tiếp tục được.
    with get_conn() as conn:
        for row in rows:
            values = [row[c] for c in cols] + [extra[c] for c in extra]
            conn.execute(sql, tuple(values))
            written += 1

    _resync_sequence(ent.table, ent.pk)
    note = f"bỏ cột không có ở đích: {', '.join(dropped)}" if dropped else ""
    return TableResult(ent.table, len(rows), written, note=note)


def _embed_chunks(src: sqlite3.Connection, *, dry_run: bool) -> tuple[int, list[str]]:
    """Dựng LẠI vector từ văn bản chunk chuẩn, không xuất biểu diễn nội bộ của Chroma.

    Vì sao dựng lại: kết quả tái lập được, kiểm chứng được, và không phụ thuộc vào định
    dạng lưu trữ của kho vector cũ. Xuất vector thô từ Chroma thì phải tin rằng chúng
    được tạo bởi đúng model đó, mà không có gì chứng minh điều đó.
    """
    warnings: list[str] = []
    rows = src.execute(
        "SELECT id, text FROM document_chunks WHERE text IS NOT NULL AND text <> '' ORDER BY id"
    ).fetchall()
    if dry_run or not rows:
        return len(rows), warnings

    from backend.config import settings
    from backend.rag import pgvector_store, store

    ids = [int(r["id"]) for r in rows]
    texts = [str(r["text"]) for r in rows]
    vectors = store.embed_texts(texts)

    dim = len(vectors[0])
    if dim != pgvector_store.EMBEDDING_DIM:
        raise MigrationError(
            f"Model sinh vector {dim} chiều nhưng cột `embedding` khai báo "
            f"{pgvector_store.EMBEDDING_DIM}. Dừng lại: ghi tiếp là ghi vào cột sai kích thước."
        )

    pgvector_store.upsert(ids, vectors, settings.embedding_model)
    return len(ids), warnings


def migrate(
    *,
    owner_user_id: str,
    dry_run: bool = False,
    fault_after: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> MigrationResult:
    """Chạy một lần chuyển dữ liệu.

    `fault_after` chỉ dùng cho test: ném lỗi ngay sau khi chép xong bảng có tên đó, để
    dựng lại cảnh hỏng nửa chừng rồi kiểm việc chạy lại. Không có đường nào từ CLI đặt
    được tham số này.
    """
    say = progress or (lambda _msg: None)

    if not dry_run and not driver.is_postgres():
        raise MigrationError(
            "Chưa đặt DATABASE_URL nên đích đến vẫn là SQLite trên máy này. "
            "Chuyển dữ liệu vào chính nó thì không có nghĩa gì."
        )

    inv = inventory.collect()
    result = MigrationResult(
        run_id=None,
        fingerprint=inv.fingerprint,
        owner_user_id=owner_user_id,
        dry_run=dry_run,
        documents_inventoried=len(inv.documents),
        runtime_skipped=dict(inv.skipped_counts),
        warnings=list(inv.warnings),
    )

    if not dry_run:
        result.run_id = ledger.start(inv.fingerprint, inv.git_commit, owner_user_id)

    src = inventory.open_source_readonly()
    try:
        for ent in DURABLE:
            say(f"  {ent.table}")
            result.tables.append(
                _copy_table(src, ent, owner_user_id=owner_user_id, dry_run=dry_run)
            )
            if fault_after and ent.table == fault_after:
                raise MigrationError(f"lỗi dựng sẵn sau khi chép `{ent.table}`")

        say("  vector")
        n, warns = _embed_chunks(src, dry_run=dry_run)
        result.chunks_embedded = n
        result.warnings.extend(warns)
    except BaseException as exc:
        if result.run_id is not None:
            ledger.fail(result.run_id, exc, result.to_dict())
        raise
    finally:
        src.close()

    if result.run_id is not None:
        ledger.finish(result.run_id, result.to_dict())
    return result
