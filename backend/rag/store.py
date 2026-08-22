"""Vector store (ChromaDB) + mô hình embedding chạy local.

Input:  các đoạn văn bản đã cắt, hoặc câu truy vấn.
Output: id đoạn khớp nhất kèm khoảng cách.

Phân vai rõ ràng:
    - ChromaDB giữ VECTOR + metadata tối thiểu (chunk_id, document_id, workspace_id).
    - SQLite giữ VĂN BẢN GỐC + vị trí trích dẫn, và là nguồn sự thật khi dựng trích dẫn.
Nhờ vậy trích dẫn luôn trỏ đúng đoạn trong đúng tệp, không phụ thuộc metadata vector store.

Embedding chạy hoàn toàn trên máy — KHÔNG tính là dữ liệu gửi ra ngoài (spec §7.1).
Model nạp lười vì máy chỉ có 7.8 GB RAM.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Sequence

from backend.config import settings

COLLECTION_NAME = "documents"

_embedder: Any = None
_embedder_lock = threading.Lock()
_client: Any = None
_client_lock = threading.Lock()


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    distance: float


def get_embedder() -> Any:
    """Nạp mô hình embedding một lần duy nhất (nạp lười, giữ suốt phiên)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer

                _embedder = SentenceTransformer(settings.embedding_model, device="cpu")
    return _embedder


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Tạo vector cho danh sách văn bản. Chạy local, không rời khỏi máy."""
    if not texts:
        return []
    model = get_embedder()
    vectors = model.encode(
        list(texts),
        batch_size=16,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


def _get_client() -> Any:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import chromadb

                settings.ensure_dirs()
                _client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return _client


def get_collection() -> Any:
    """Một collection duy nhất cho toàn hệ thống, lọc theo workspace_id qua metadata.

    Một collection dễ dọn hơn nhiều collection: xoá hồ sơ chỉ là xoá theo điều kiện
    metadata, không phải quản lý vòng đời từng collection.
    """
    return _get_client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(
    workspace_id: int,
    document_id: int,
    chunk_ids: Sequence[int],
    texts: Sequence[str],
) -> int:
    """Thêm các đoạn vào chỉ mục. `chunk_ids` là id dòng trong bảng SQLite."""
    if not chunk_ids:
        return 0

    embeddings = embed_texts(texts)
    get_collection().upsert(
        ids=[str(cid) for cid in chunk_ids],
        embeddings=embeddings,
        documents=list(texts),
        metadatas=[
            {"workspace_id": workspace_id, "document_id": document_id, "chunk_id": cid}
            for cid in chunk_ids
        ],
    )
    return len(chunk_ids)


def _round_robin_by_document(candidates: list[SearchHit], k: int) -> list[SearchHit]:
    """Chọn k đoạn nhưng chia lượt giữa các tài liệu, thay vì lấy thẳng top-k.

    Vì sao cần: một tài liệu dài (ví dụ kế hoạch 64 đoạn) sẽ chiếm gần hết top-k và
    đè mất tài liệu ngắn nhưng đúng trọng tâm (ví dụ bài phát biểu 8 đoạn chứa số tiền
    tài trợ). Đo thực tế trên bộ tài liệu LDSC: lấy thẳng top-10 thì đoạn chứa
    "6.780.000.000 đồng" không lọt vào ngữ cảnh, khiến câu trả lời thiếu số liệu.

    Chia lượt vẫn giữ thứ tự hạng trong từng tài liệu, nên đoạn tốt nhất của mỗi tài
    liệu luôn được ưu tiên trước đoạn thứ hai của tài liệu khác.
    """
    grouped: dict[int, list[SearchHit]] = {}
    for hit in candidates:
        grouped.setdefault(hit.document_id, []).append(hit)

    # Thứ tự tài liệu theo đoạn khớp nhất của nó.
    order = sorted(grouped, key=lambda doc_id: grouped[doc_id][0].distance)

    selected: list[SearchHit] = []
    depth = 0
    while len(selected) < k:
        added = False
        for doc_id in order:
            bucket = grouped[doc_id]
            if depth < len(bucket):
                selected.append(bucket[depth])
                added = True
                if len(selected) >= k:
                    break
        if not added:
            break
        depth += 1

    return sorted(selected, key=lambda h: h.distance)


def search(
    workspace_id: int,
    query: str,
    top_k: int | None = None,
    document_ids: Sequence[int] | None = None,
) -> list[SearchHit]:
    """Tìm các đoạn gần nghĩa nhất trong phạm vi một hồ sơ khách hàng."""
    k = top_k or settings.retrieval_top_k

    where: dict[str, Any] = {"workspace_id": workspace_id}
    if document_ids:
        # Thu hẹp phạm vi khi chuyên gia chỉ muốn hỏi trên vài tài liệu được chọn.
        where = {
            "$and": [
                {"workspace_id": workspace_id},
                {"document_id": {"$in": list(document_ids)}},
            ]
        }

    # Lấy dư rồi mới chia lượt — cần đủ ứng viên của từng tài liệu để chọn.
    pool_size = max(k * 4, 24)

    result = get_collection().query(
        query_embeddings=embed_texts([query]),
        n_results=pool_size,
        where=where,
        include=["metadatas", "distances"],
    )

    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    candidates: list[SearchHit] = [
        SearchHit(
            chunk_id=int(meta["chunk_id"]),
            document_id=int(meta["document_id"]),
            distance=float(distance),
        )
        for meta, distance in zip(metadatas, distances)
    ]

    return _round_robin_by_document(candidates, k)


def delete_document(document_id: int) -> None:
    """Xoá toàn bộ vector của một tài liệu (spec A1.8: xoá rồi thì không còn xuất hiện)."""
    get_collection().delete(where={"document_id": document_id})


def delete_workspace(workspace_id: int) -> None:
    """Xoá toàn bộ vector của một hồ sơ khách hàng (spec A7.6)."""
    get_collection().delete(where={"workspace_id": workspace_id})


def count(workspace_id: int | None = None) -> int:
    collection = get_collection()
    if workspace_id is None:
        return int(collection.count())
    result = collection.get(where={"workspace_id": workspace_id}, include=[])
    return len(result.get("ids") or [])
