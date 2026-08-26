"""Routes hồ sơ khách hàng — đơn vị tổ chức chính của toàn hệ thống (spec §1.5).

Input:  WorkspaceCreate / WorkspaceUpdate.
Output: WorkspaceOut kèm số liệu tổng hợp (số tài liệu, số thuật ngữ, số buổi mock).

Xoá hồ sơ = xoá vĩnh viễn mọi thứ thuộc hồ sơ đó (spec A7.6). Foreign key ON DELETE CASCADE
lo phần SQLite; phần tệp trên đĩa và chỉ mục vector sẽ được các module tương ứng dọn ở GĐ 1.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from backend.db import get_conn
from backend.rag import ingest
from backend.schemas import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# Đếm sẵn số liệu để Dashboard không phải gọi nhiều lần (spec A6.4: tối đa 2 lần bấm).
_SELECT_WITH_COUNTS = """
    SELECT w.*,
           (SELECT COUNT(*) FROM documents     d WHERE d.workspace_id = w.id) AS n_documents,
           (SELECT COUNT(*) FROM glossary      g WHERE g.workspace_id = w.id
                                                  AND g.status <> 'skipped')  AS n_terms,
           (SELECT COUNT(*) FROM mock_sessions s WHERE s.workspace_id = w.id) AS n_sessions
    FROM workspaces w
"""


def _to_out(row: dict[str, object]) -> WorkspaceOut:
    return WorkspaceOut(
        id=int(row["id"]),
        name=str(row["name"]),
        industry=row.get("industry"),  # type: ignore[arg-type]
        is_confidential=bool(row["is_confidential"]),
        notes=row.get("notes"),  # type: ignore[arg-type]
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        n_documents=int(row.get("n_documents") or 0),
        n_terms=int(row.get("n_terms") or 0),
        n_sessions=int(row.get("n_sessions") or 0),
    )


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces() -> list[WorkspaceOut]:
    with get_conn() as conn:
        rows = conn.execute(_SELECT_WITH_COUNTS + " ORDER BY w.updated_at DESC").fetchall()
    return [_to_out(dict(r)) for r in rows]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(payload: WorkspaceCreate) -> WorkspaceOut:
    try:
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO workspaces (name, industry, is_confidential, notes)
                VALUES (?, ?, ?, ?)
                """,
                (
                    payload.name.strip(),
                    payload.industry,
                    int(payload.is_confidential),
                    payload.notes,
                ),
            )
            new_id = int(cur.lastrowid or 0)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Đã có hồ sơ tên '{payload.name}'. Chọn tên khác hoặc mở hồ sơ cũ.",
        ) from exc
    return get_workspace(new_id)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: int) -> WorkspaceOut:
    with get_conn() as conn:
        row = conn.execute(_SELECT_WITH_COUNTS + " WHERE w.id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")
    return _to_out(dict(row))


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(workspace_id: int, payload: WorkspaceUpdate) -> WorkspaceOut:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return get_workspace(workspace_id)

    if "is_confidential" in fields:
        fields["is_confidential"] = int(bool(fields["is_confidential"]))

    assignments = ", ".join(f"{key} = ?" for key in fields)
    params = tuple(fields.values()) + (workspace_id,)

    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE workspaces SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            params,
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")
    return get_workspace(workspace_id)


@router.get("/{workspace_id}/delete-preview")
def delete_preview(workspace_id: int) -> dict[str, object]:
    """Xác nhận bước 1: nói rõ sẽ mất những gì trước khi xoá (spec A7.6, edge case §4.6)."""
    with get_conn() as conn:
        row = conn.execute("SELECT name FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")

        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM documents      WHERE workspace_id = ?) AS n_documents,
              (SELECT COALESCE(SUM(size_bytes),0) FROM documents WHERE workspace_id = ?) AS bytes_documents,
              (SELECT COUNT(*) FROM glossary       WHERE workspace_id = ?) AS n_terms,
              (SELECT COUNT(*) FROM mock_sessions  WHERE workspace_id = ?) AS n_sessions,
              (SELECT COUNT(*) FROM qa_history     WHERE workspace_id = ?) AS n_qa,
              (SELECT COUNT(*) FROM research_runs  WHERE workspace_id = ?) AS n_research
            """,
            (workspace_id,) * 6,
        ).fetchone()

    data = dict(counts)
    return {
        "workspace_id": workspace_id,
        "name": str(row["name"]),
        **{k: int(v or 0) for k, v in data.items()},
        "warning": (
            "Xoá vĩnh viễn: tài liệu, chỉ mục, bảng thuật ngữ, audio lời thoại đã sinh, và toàn bộ "
            "lịch sử của hồ sơ này. Không hoàn tác được."
        ),
    }


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: int, confirm: bool = False) -> dict[str, object]:
    """Xác nhận bước 2. Bắt buộc `confirm=true` để tránh xoá do bấm nhầm."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Cần xác nhận: gọi lại với confirm=true sau khi đã xem delete-preview.",
        )

    # Dọn tệp trên đĩa và chỉ mục vector TRƯỚC khi xoá bản ghi — xoá bản ghi trước thì
    # mất luôn đường lần ra chúng, để lại rác không dọn được (spec A7.6).
    ingest.delete_workspace_data(workspace_id)

    with get_conn() as conn:
        cur = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")
    return {"deleted": workspace_id, "message": "Đã xoá vĩnh viễn hồ sơ và toàn bộ dữ liệu liên quan."}
