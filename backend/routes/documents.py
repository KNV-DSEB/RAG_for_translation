"""Routes Module 1: nạp tài liệu, xem trước, xoá, và hỏi đáp có trích dẫn.

Input:  tệp tải lên (multipart) hoặc câu hỏi.
Output: trạng thái từng tệp, hoặc câu trả lời kèm trích dẫn.

Một tệp lỗi không làm hỏng cả lô (spec A1.9): mỗi tệp trả về trạng thái riêng.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from backend.config import settings
from backend.db import get_conn
from backend.rag import ingest, qa
from backend.rag.extractors import SUPPORTED_EXTENSIONS
from backend.rag.language import classify

router = APIRouter(prefix="/documents", tags=["documents"])


def _require_workspace(workspace_id: int) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")


@router.get("")
def list_documents(workspace_id: int = Query(...)) -> list[dict[str, Any]]:
    _require_workspace(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, ext, size_bytes, language, language_source,
                   extraction_quality, extractor, status, error_message,
                   n_chars, n_chunks, created_at
            FROM documents WHERE workspace_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (workspace_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/upload")
async def upload_documents(
    workspace_id: int = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Nạp một hoặc nhiều tệp. Trả về kết quả riêng cho từng tệp."""
    _require_workspace(workspace_id)

    results: list[dict[str, Any]] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024

    for upload in files:
        name = upload.filename or "tai-lieu"
        ext = Path(name).suffix.lower()

        # --- Chặn sớm: định dạng không hỗ trợ ---
        if ext not in SUPPORTED_EXTENSIONS:
            results.append(
                {
                    "filename": name,
                    "status": "error",
                    "error": (
                        f"Chưa hỗ trợ định dạng '{ext}'. Các định dạng nhận được: "
                        f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}."
                    ),
                }
            )
            continue

        data = await upload.read()

        if not data:
            results.append(
                {"filename": name, "status": "error", "error": f"Tệp '{name}' rỗng (0 byte)."}
            )
            continue

        if len(data) > max_bytes:
            results.append(
                {
                    "filename": name,
                    "status": "error",
                    "error": (
                        f"Tệp '{name}' nặng {len(data) / 1024 / 1024:.1f} MB, vượt ngưỡng "
                        f"{settings.max_upload_mb} MB. Hãy tách nhỏ tệp rồi nạp lại."
                    ),
                }
            )
            continue

        stored_path = ingest.save_upload(workspace_id, name, data)

        # --- Trùng nội dung: hỏi thay vì âm thầm nhân đôi (spec A1.10) ---
        duplicate = ingest.find_duplicate(workspace_id, ingest._content_hash(stored_path))
        if duplicate:
            stored_path.unlink(missing_ok=True)
            results.append(
                {
                    "filename": name,
                    "status": "duplicate",
                    "error": (
                        f"Nội dung tệp này trùng với '{duplicate['filename']}' đã nạp trước đó. "
                        "Bỏ qua để tránh câu trả lời bị lặp. Muốn thay thế thì xoá tệp cũ trước."
                    ),
                }
            )
            continue

        result = ingest.ingest_file(workspace_id, stored_path, name)
        results.append(
            {
                "document_id": result.document_id,
                "filename": result.filename,
                "status": result.status,
                "language": result.language,
                "language_label": result.language_label,
                "extractor": result.extractor,
                "quality": result.quality,
                "n_chars": result.n_chars,
                "n_chunks": result.n_chunks,
                "warnings": result.warnings,
                "error": result.error,
            }
        )

    n_ok = sum(1 for r in results if r.get("status") == "ready")
    return {
        "results": results,
        "n_total": len(results),
        "n_ready": n_ok,
        "n_failed": len(results) - n_ok,
    }


@router.get("/{document_id}/preview")
def preview_document(document_id: int, max_chunks: int = Query(default=12, ge=1, le=200)) -> dict[str, Any]:
    """Xem nội dung đã trích xuất — để chuyên gia tự đánh giá chất lượng trích xuất."""
    with get_conn() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu này.")
        chunks = conn.execute(
            """
            SELECT id, chunk_index, locator, lang, text FROM document_chunks
            WHERE document_id = ? ORDER BY chunk_index LIMIT ?
            """,
            (document_id, max_chunks),
        ).fetchall()

    return {
        "document": dict(doc),
        "chunks": [dict(c) for c in chunks],
        "showing": len(chunks),
        "total_chunks": int(doc["n_chunks"]),
    }


@router.patch("/{document_id}/language")
def set_language(document_id: int, language: str = Query(...)) -> dict[str, Any]:
    """Đổi nhãn ngôn ngữ thủ công khi máy nhận sai (edge case §4.1 của spec)."""
    allowed = {"vi", "en", "parallel", "mixed", "unknown"}
    if language not in allowed:
        raise HTTPException(
            status_code=400, detail=f"Nhãn ngôn ngữ phải là một trong: {', '.join(sorted(allowed))}."
        )
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE documents SET language = ?, language_source = 'manual' WHERE id = ?",
            (language, document_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu này.")
    return {"document_id": document_id, "language": language, "language_source": "manual"}


@router.post("/{document_id}/reindex")
def reindex_document(document_id: int) -> dict[str, Any]:
    """Nạp lại một tệp đã có (dùng khi lần trước lỗi, hoặc sau khi đổi nhãn ngôn ngữ)."""
    with get_conn() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu này.")

    path = Path(str(doc["stored_path"]))
    if not path.exists():
        raise HTTPException(
            status_code=410,
            detail=f"Tệp gốc '{doc['filename']}' không còn trên đĩa. Hãy tải lên lại.",
        )

    workspace_id = int(doc["workspace_id"])
    ingest.delete_document(document_id)
    result = ingest.ingest_file(workspace_id, path, str(doc["filename"]))
    return {
        "document_id": result.document_id,
        "status": result.status,
        "language": result.language,
        "n_chunks": result.n_chunks,
        "error": result.error,
        "warnings": result.warnings,
    }


@router.delete("/{document_id}")
def delete_document(document_id: int) -> dict[str, Any]:
    if not ingest.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu này.")
    return {"deleted": document_id, "message": "Đã xoá tài liệu và toàn bộ chỉ mục của nó."}


@router.post("/ask")
def ask_documents(payload: dict[str, Any]) -> dict[str, Any]:
    """Hỏi đáp trên tài liệu. Câu trả lời luôn kèm trích dẫn hoặc nói rõ không tìm thấy."""
    workspace_id = payload.get("workspace_id")
    question = str(payload.get("question", "")).strip()
    document_ids = payload.get("document_ids") or None

    if not workspace_id:
        raise HTTPException(status_code=400, detail="Thiếu hồ sơ khách hàng.")
    if not question:
        raise HTTPException(status_code=400, detail="Câu hỏi đang để trống.")

    _require_workspace(int(workspace_id))

    answer = qa.ask(
        workspace_id=int(workspace_id), question=question, document_ids=document_ids
    )
    return {
        "question": answer.question,
        "answer": answer.answer,
        "found": answer.found,
        "confidence": answer.confidence,
        "inference": answer.inference,
        "key_figures": answer.key_figures,
        "warnings": answer.warnings,
        "citations": [
            {
                "document_id": c.document_id,
                "filename": c.filename,
                "locator": c.locator,
                "snippet": c.snippet,
                "chunk_id": c.chunk_id,
            }
            for c in answer.citations
        ],
    }


@router.get("/qa-history")
def qa_history(workspace_id: int = Query(...), limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    _require_workspace(workspace_id)
    return qa.history(workspace_id, limit=limit)
