"""Luồng nạp tài liệu đầu–cuối: lưu tệp → trích xuất → nhận ngôn ngữ → cắt đoạn → lập chỉ mục.

Input:  workspace_id + tệp đã tải lên.
Output: bản ghi `documents` với trạng thái cuối cùng ('ready' hoặc 'error' kèm lý do cụ thể).

Nguyên tắc xử lý lỗi (spec A1.9): một tệp hỏng KHÔNG được làm hỏng cả lô. Mỗi tệp có
trạng thái riêng, lỗi riêng, và nạp lại riêng được.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings
from backend.db import get_conn
from backend.rag import store
from backend.rag.chunker import chunk_document
from backend.rag.extractors import ExtractionError, extract
from backend.rag.language import classify


@dataclass
class IngestResult:
    document_id: int
    filename: str
    status: str
    language: str
    language_label: str
    extractor: str | None
    quality: str
    n_chars: int
    n_chunks: int
    warnings: list[str]
    error: str | None = None


def _safe_filename(name: str) -> str:
    """Giữ nguyên chữ tiếng Việt có dấu, chỉ bỏ ký tự không hợp lệ cho tên tệp Windows."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "tai-lieu"


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def find_duplicate(workspace_id: int, content_hash: str) -> dict[str, object] | None:
    """Tệp trùng NỘI DUNG (không chỉ trùng tên) đã nạp trước đó chưa."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, filename FROM documents
            WHERE workspace_id = ? AND content_hash = ? AND status = 'ready'
            """,
            (workspace_id, content_hash),
        ).fetchone()
    return dict(row) if row else None


def save_upload(workspace_id: int, filename: str, data: bytes) -> Path:
    """Lưu tệp tải lên vào thư mục dữ liệu của hồ sơ."""
    folder = settings.documents_dir / str(workspace_id)
    folder.mkdir(parents=True, exist_ok=True)

    target = folder / _safe_filename(filename)
    # Trùng tên thì thêm hậu tố, không âm thầm ghi đè tệp cũ.
    if target.exists():
        stem, suffix = target.stem, target.suffix
        index = 2
        while target.exists():
            target = folder / f"{stem} ({index}){suffix}"
            index += 1

    target.write_bytes(data)
    return target


def ingest_file(workspace_id: int, stored_path: Path, original_name: str) -> IngestResult:
    """Nạp một tệp đã lưu. Luôn trả về kết quả, không ném lỗi ra ngoài."""
    ext = stored_path.suffix.lower()
    size = stored_path.stat().st_size
    content_hash = _content_hash(stored_path)

    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents
                (workspace_id, filename, stored_path, ext, size_bytes, content_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, 'extracting')
            """,
            (workspace_id, original_name, str(stored_path), ext, size, content_hash),
        )
        document_id = int(cursor.lastrowid or 0)

    def fail(message: str) -> IngestResult:
        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET status = 'error', error_message = ? WHERE id = ?",
                (message, document_id),
            )
        return IngestResult(
            document_id=document_id,
            filename=original_name,
            status="error",
            language="unknown",
            language_label="chưa xác định",
            extractor=None,
            quality="ok",
            n_chars=0,
            n_chunks=0,
            warnings=[],
            error=message,
        )

    # ---- 1. Trích xuất văn bản ----
    try:
        extraction = extract(stored_path)
    except ExtractionError as exc:
        return fail(str(exc))
    except Exception as exc:  # lỗi ngoài dự kiến vẫn phải nói được là tệp nào hỏng
        return fail(f"Lỗi không lường trước khi đọc '{original_name}': {type(exc).__name__}.")

    # ---- 2. Nhận diện ngôn ngữ (gồm cả song ngữ song song) ----
    language_info = classify(extraction.blocks)

    # ---- 3. Cắt đoạn, giữ vị trí trích dẫn ----
    chunks = chunk_document(extraction.blocks, language_info.block_languages)
    if not chunks:
        return fail(f"Tệp '{original_name}' không có nội dung chữ để lập chỉ mục.")

    with get_conn() as conn:
        conn.execute("UPDATE documents SET status = 'indexing' WHERE id = ?", (document_id,))
        chunk_ids: list[int] = []
        for index, chunk in enumerate(chunks):
            cursor = conn.execute(
                """
                INSERT INTO document_chunks
                    (document_id, workspace_id, chunk_index, text, locator, lang)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (document_id, workspace_id, index, chunk.text, chunk.locator, chunk.lang),
            )
            chunk_ids.append(int(cursor.lastrowid or 0))

    # ---- 4. Lập chỉ mục vector (chạy local) ----
    try:
        store.add_chunks(
            workspace_id=workspace_id,
            document_id=document_id,
            chunk_ids=chunk_ids,
            texts=[c.text for c in chunks],
        )
    except Exception as exc:
        return fail(
            f"Đã đọc được '{original_name}' nhưng lập chỉ mục thất bại "
            f"({type(exc).__name__}). Thử Nạp lại tệp này."
        )

    warnings = list(extraction.warnings) + list(language_info.notes)

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE documents
            SET status = 'ready', language = ?, extraction_quality = ?, extractor = ?,
                n_chars = ?, n_chunks = ?, error_message = NULL
            WHERE id = ?
            """,
            (
                language_info.language,
                extraction.quality,
                extraction.extractor,
                extraction.n_chars,
                len(chunks),
                document_id,
            ),
        )

    return IngestResult(
        document_id=document_id,
        filename=original_name,
        status="ready",
        language=language_info.language,
        language_label=language_info.label_vi,
        extractor=extraction.extractor,
        quality=extraction.quality,
        n_chars=extraction.n_chars,
        n_chunks=len(chunks),
        warnings=warnings,
    )


def delete_document(document_id: int) -> bool:
    """Xoá tài liệu: vector, đoạn văn bản, tệp trên đĩa, và bản ghi (spec A1.8)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    if row is None:
        return False

    try:
        store.delete_document(document_id)
    except Exception:
        # Chỉ mục lỗi cũng vẫn phải xoá được bản ghi, nếu không tài liệu sẽ mắc kẹt.
        pass

    path = Path(str(row["stored_path"]))
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass

    with get_conn() as conn:
        # document_chunks có ON DELETE CASCADE nên xoá theo.
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return True


def delete_workspace_data(workspace_id: int) -> None:
    """Dọn sạch tệp và chỉ mục của một hồ sơ trước khi xoá bản ghi (spec A7.6)."""
    try:
        store.delete_workspace(workspace_id)
    except Exception:
        pass
    folder = settings.documents_dir / str(workspace_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
