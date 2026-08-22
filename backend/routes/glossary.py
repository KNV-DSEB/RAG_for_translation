"""Routes Module 2 — phần bảng thuật ngữ: xem, sửa, thêm tay, giải quyết xung đột, xuất CSV.

Input:  workspace_id, và các thao tác sửa của chuyên gia.
Output: danh sách thuật ngữ kèm trạng thái/độ tin, hoặc tệp CSV.

Sửa tay một dòng thì dòng đó chuyển sang `expert_edited` và được ưu tiên tuyệt đối về sau —
lần nghiên cứu tiếp theo không bao giờ ghi đè (spec A2.13).
"""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.db import get_conn
from backend.research.terminology import CATEGORIES, normalize_term

router = APIRouter(prefix="/glossary", tags=["glossary"])


class TermCreate(BaseModel):
    workspace_id: int
    term_vi: str = Field(min_length=1)
    term_en: str = Field(min_length=1)
    pronunciation: str | None = None
    definition: str | None = None
    category: str = "chuyên ngành"


class TermUpdate(BaseModel):
    term_vi: str | None = None
    term_en: str | None = None
    pronunciation: str | None = None
    definition: str | None = None
    category: str | None = None


@router.get("")
def list_terms(
    workspace_id: int = Query(...),
    include_skipped: bool = Query(default=False),
    category: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Bảng thuật ngữ, sắp xếp: dòng chuyên gia sửa trước, rồi bản dịch người thật, rồi tần suất."""
    sql = "SELECT * FROM glossary WHERE workspace_id = ?"
    params: list[Any] = [workspace_id]
    if not include_skipped:
        sql += " AND status <> 'skipped'"
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += """
        ORDER BY CASE status WHEN 'expert_edited' THEN 0 ELSE 1 END,
                 CASE confidence WHEN 'human_translated' THEN 0 ELSE 1 END,
                 frequency DESC, term_vi COLLATE NOCASE
    """

    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            conflicts = conn.execute(
                """
                SELECT id, proposed_term_en, proposed_definition, source_ref, confidence
                FROM glossary_conflicts WHERE glossary_id = ? AND resolved = 0
                """,
                (int(row["id"]),),
            ).fetchall()
            item["conflicts"] = [dict(c) for c in conflicts]
            items.append(item)
    return items


@router.get("/stats")
def stats(workspace_id: int = Query(...)) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status = 'expert_edited' THEN 1 ELSE 0 END) AS expert_edited,
              SUM(CASE WHEN confidence = 'human_translated' THEN 1 ELSE 0 END) AS human_translated,
              SUM(CASE WHEN pronunciation IS NOT NULL AND pronunciation <> '' THEN 1 ELSE 0 END)
                  AS with_pronunciation,
              SUM(CASE WHEN source_type = 'web' THEN 1 ELSE 0 END) AS from_web,
              SUM(CASE WHEN source_type = 'document' THEN 1 ELSE 0 END) AS from_document
            FROM glossary WHERE workspace_id = ? AND status <> 'skipped'
            """,
            (workspace_id,),
        ).fetchone()
        conflicts = conn.execute(
            """
            SELECT COUNT(*) AS n FROM glossary_conflicts c
            JOIN glossary g ON g.id = c.glossary_id
            WHERE g.workspace_id = ? AND c.resolved = 0
            """,
            (workspace_id,),
        ).fetchone()
        categories = conn.execute(
            """
            SELECT category, COUNT(*) AS n FROM glossary
            WHERE workspace_id = ? AND status <> 'skipped'
            GROUP BY category ORDER BY n DESC
            """,
            (workspace_id,),
        ).fetchall()

    data = {k: int(v or 0) for k, v in dict(row).items()}
    data["conflicts"] = int(conflicts["n"] or 0)
    data["by_category"] = [dict(c) for c in categories]
    return data


@router.post("", status_code=201)
def create_term(payload: TermCreate) -> dict[str, Any]:
    """Chuyên gia thêm thuật ngữ thủ công → vào luôn trạng thái `expert_edited`."""
    key = normalize_term(payload.term_vi)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM glossary WHERE workspace_id = ? AND term_vi_norm = ?",
            (payload.workspace_id, key),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Thuật ngữ '{payload.term_vi}' đã có trong bảng. Hãy sửa dòng đó.",
            )
        term_id = int(
            conn.execute(
                """
                INSERT INTO glossary
                    (workspace_id, term_vi, term_vi_norm, term_en, pronunciation, definition,
                     category, confidence, status, source_type, source_ref, frequency)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'human_translated', 'expert_edited', 'expert',
                        'chuyên gia nhập', 1)
                """,
                (
                    payload.workspace_id, payload.term_vi.strip(), key, payload.term_en.strip(),
                    payload.pronunciation, payload.definition, payload.category,
                ),
            ).lastrowid
            or 0
        )
    return {"id": term_id, "message": "Đã thêm thuật ngữ."}


@router.patch("/{term_id}")
def update_term(term_id: int, payload: TermUpdate) -> dict[str, Any]:
    """Sửa một thuật ngữ. Sửa rồi thì dòng đó được ưu tiên tuyệt đối về sau."""
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Không có gì để sửa.")

    if "term_vi" in fields:
        fields["term_vi_norm"] = normalize_term(str(fields["term_vi"]))

    assignments = ", ".join(f"{key} = ?" for key in fields)
    params = tuple(fields.values()) + (term_id,)

    with get_conn() as conn:
        cursor = conn.execute(
            f"""
            UPDATE glossary
            SET {assignments}, status = 'expert_edited', updated_at = datetime('now')
            WHERE id = ?
            """,
            params,
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy thuật ngữ này.")
    return {"id": term_id, "status": "expert_edited", "message": "Đã lưu bản sửa của bạn."}


@router.post("/{term_id}/skip")
def skip_term(term_id: int) -> dict[str, Any]:
    """Bỏ qua một thuật ngữ (không xoá hẳn, để lần sau không đề xuất lại)."""
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE glossary SET status = 'skipped', updated_at = datetime('now') WHERE id = ?",
            (term_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy thuật ngữ này.")
    return {"id": term_id, "message": "Đã bỏ qua thuật ngữ này."}


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: int, accept: bool = Query(...)) -> dict[str, Any]:
    """Giải quyết xung đột bản dịch: nhận bản mới, hoặc giữ bản cũ."""
    with get_conn() as conn:
        conflict = conn.execute(
            "SELECT * FROM glossary_conflicts WHERE id = ?", (conflict_id,)
        ).fetchone()
        if conflict is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy xung đột này.")

        if accept:
            conn.execute(
                """
                UPDATE glossary
                SET term_en = ?,
                    definition = COALESCE(NULLIF(?, ''), definition),
                    status = 'expert_edited', updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    str(conflict["proposed_term_en"]),
                    conflict["proposed_definition"] or "",
                    int(conflict["glossary_id"]),
                ),
            )
        else:
            # Giữ bản cũ, nhưng đánh dấu là quyết định của chuyên gia.
            conn.execute(
                "UPDATE glossary SET status = 'expert_edited', updated_at = datetime('now') WHERE id = ?",
                (int(conflict["glossary_id"]),),
            )

        conn.execute("UPDATE glossary_conflicts SET resolved = 1 WHERE id = ?", (conflict_id,))

    return {
        "conflict_id": conflict_id,
        "accepted": accept,
        "message": "Đã dùng bản dịch mới." if accept else "Đã giữ bản dịch cũ.",
    }


@router.get("/export")
def export_csv(workspace_id: int = Query(...)) -> StreamingResponse:
    """Xuất bảng thuật ngữ ra CSV để mang đi buổi dịch thật.

    Dùng BOM utf-8-sig để Excel trên Windows mở đúng chữ tiếng Việt có dấu (spec A2.16).
    """
    with get_conn() as conn:
        workspace = conn.execute(
            "SELECT name FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")
        rows = conn.execute(
            """
            SELECT term_vi, term_en, pronunciation, definition, category,
                   confidence, status, source_type, source_ref, frequency
            FROM glossary WHERE workspace_id = ? AND status <> 'skipped'
            ORDER BY category, term_vi COLLATE NOCASE
            """,
            (workspace_id,),
        ).fetchall()

    buffer = io.StringIO()
    buffer.write("﻿")  # BOM cho Excel
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Thuật ngữ (VI)", "Thuật ngữ (EN)", "Cách đọc", "Định nghĩa", "Phân loại",
            "Độ tin", "Trạng thái", "Loại nguồn", "Nguồn", "Tần suất",
        ]
    )
    label = {"human_translated": "người dịch", "machine_guess": "máy suy đoán"}
    status_label = {"auto": "tự nhận", "expert_edited": "chuyên gia sửa", "skipped": "bỏ qua"}
    for row in rows:
        writer.writerow(
            [
                row["term_vi"], row["term_en"], row["pronunciation"] or "",
                row["definition"] or "", row["category"] or "",
                label.get(str(row["confidence"]), row["confidence"]),
                status_label.get(str(row["status"]), row["status"]),
                row["source_type"] or "", row["source_ref"] or "", row["frequency"],
            ]
        )

    buffer.seek(0)
    filename = f"glossary-{workspace_id}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/categories")
def categories() -> list[str]:
    return CATEGORIES
