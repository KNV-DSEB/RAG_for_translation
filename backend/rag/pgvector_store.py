"""Lưu vector trong PostgreSQL + pgvector — bản thay thế Chroma khi chạy trên cloud.

Vào:  chunk_id + vector đã tạo (embedding vẫn chạy trên máy chủ, không gọi API ngoài).
Ra:   danh sách chunk gần nghĩa nhất kèm khoảng cách.

Vì sao vector nằm ngay trong `document_chunks`
----------------------------------------------
Chroma là kho riêng, nên xoá tài liệu phải nhớ xoá ở hai nơi — và spec A1.8/A7.6 đòi
xoá là mất sạch. Đặt cột `embedding` ngay trên `document_chunks` thì `ON DELETE CASCADE`
của Postgres lo phần đó: xoá tài liệu là vector biến mất trong cùng một giao dịch, không
có cửa sổ nào mà vector còn sống sau khi văn bản đã chết.

Vẫn giữ nguyên phân vai cũ: cột `text` là nguồn dựng trích dẫn, vector chỉ để tìm.

Thang đo
--------
Vector do `sentence-transformers` tạo ra đã chuẩn hoá L2 (đo được: norm = 1.000000).
Với vector đơn vị, cosine distance của Chroma và toán tử `<=>` của pgvector đều là
`1 − cos_sim`, tức CÙNG thang. Ngưỡng `WEAK_CONTEXT_DISTANCE = 0.75` vì vậy có cơ sở
để giữ nguyên — nhưng cơ sở lý thuyết không thay cho phép đo, nên
`tests/test_c13_pgvector_parity.py` đo lại trên bộ tài liệu thật.
"""

from __future__ import annotations

from typing import Any, Sequence

from backend.db import get_conn

# 384 là chiều của paraphrase-multilingual-MiniLM-L12-v2 — ĐO được, không lấy từ tài liệu.
# `test_c13` kiểm lại con số này mỗi lần chạy để nó không lệch âm thầm khi đổi model.
EMBEDDING_DIM = 384

# DDL chỉ dùng cho PostgreSQL. Chạy lại nhiều lần vẫn an toàn.
SCHEMA: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    f"ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM})",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT",
    # Lọc theo hồ sơ trước rồi mới xếp hạng — với dữ liệu một chuyên gia thì quét tuần tự
    # đã đủ nhanh, và quét tuần tự cho kết quả CHÍNH XÁC.
    "CREATE INDEX IF NOT EXISTS ix_chunks_ws_embed ON document_chunks (workspace_id) "
    "WHERE embedding IS NOT NULL",
)


def ensure_schema() -> None:
    with get_conn() as conn:
        for statement in SCHEMA:
            conn.execute(statement)


def _to_literal(vector: Sequence[float]) -> str:
    """pgvector nhận dạng chuỗi `[1,2,3]`. Không cần đăng ký adapter riêng."""
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def upsert(
    chunk_ids: Sequence[int],
    embeddings: Sequence[Sequence[float]],
    model_name: str,
) -> int:
    """Ghi vector vào đúng dòng chunk đã có. Không tạo dòng mới."""
    if not chunk_ids:
        return 0
    with get_conn() as conn:
        for chunk_id, vector in zip(chunk_ids, embeddings):
            conn.execute(
                "UPDATE document_chunks SET embedding = ?::vector, embedding_model = ? "
                "WHERE id = ?",
                (_to_literal(vector), model_name, chunk_id),
            )
    return len(chunk_ids)


def query(
    workspace_id: int,
    query_vector: Sequence[float],
    pool_size: int,
    document_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """Các chunk gần nhất trong PHẠM VI một hồ sơ, kèm khoảng cách cosine.

    `workspace_id` luôn nằm trong mệnh đề WHERE — cách ly hồ sơ là điều kiện truy vấn,
    không phải việc lọc sau khi đã lấy về.
    """
    sql = """
        SELECT id AS chunk_id, document_id, (embedding <=> ?::vector) AS distance
        FROM document_chunks
        WHERE workspace_id = ? AND embedding IS NOT NULL
    """
    params: list[Any] = [_to_literal(query_vector), workspace_id]

    if document_ids:
        sql += " AND document_id = ANY(?)"
        params.append(list(document_ids))

    sql += " ORDER BY distance ASC LIMIT ?"
    params.append(pool_size)

    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def delete_document(document_id: int) -> None:
    """Chỉ xoá vector, giữ lại văn bản.

    Dùng khi đánh chỉ mục lại. Xoá hẳn tài liệu thì `ON DELETE CASCADE` đã lo, không cần
    gọi hàm này — và đó chính là điểm hơn so với kho vector tách rời.
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE document_chunks SET embedding = NULL WHERE document_id = ?", (document_id,)
        )


def delete_workspace(workspace_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE document_chunks SET embedding = NULL WHERE workspace_id = ?", (workspace_id,)
        )


def count(workspace_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM document_chunks WHERE embedding IS NOT NULL"
    params: tuple[Any, ...] = ()
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params = (workspace_id,)
    with get_conn() as conn:
        return int(conn.execute(sql, params).fetchone()["n"])
