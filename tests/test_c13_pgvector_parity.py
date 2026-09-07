"""C13 — pgvector phải cho cùng kết quả truy hồi như Chroma, ĐO trên dữ liệu thật.

Vì sao không được suy từ lý thuyết
----------------------------------
Vector đã chuẩn hoá L2 nên về mặt toán học, cosine distance của Chroma và toán tử `<=>`
của pgvector đều là `1 − cos_sim` — cùng thang đo, và ngưỡng `WEAK_CONTEXT_DISTANCE =
0.75` lẽ ra giữ nguyên được.

Nhưng "lẽ ra" không phải bằng chứng. Cùng một công thức vẫn lệch được vì kiểu số thực
khác nhau (pgvector lưu float32, Python trả float64), vì thứ tự khi hai khoảng cách bằng
nhau, hoặc vì một chỉ mục xấp xỉ lặng lẽ đổi tập ứng viên. Bộ test này đo:

  C13a  chiều vector đúng bằng con số mã nguồn khai báo
  C13b  cách ly hồ sơ là ĐIỀU KIỆN TRUY VẤN, không phải lọc sau khi lấy về
  C13c  xếp hạng của pgvector khớp cosine tính tay trên cùng vector đó
  C13d  khoảng cách khớp tới sai số của float32
  C13e  xoá tài liệu là vector biến mất
  C13f  ngưỡng 0.75 vẫn phân biệt đúng ngữ cảnh mạnh/yếu trên thang của pgvector

Chạy trên PostgreSQL thật (`pgserver`). Bỏ qua khi bộ test đang chạy trên SQLite.
"""

from __future__ import annotations

import math

import pytest

from tests.conftest import use_postgres

pytestmark = pytest.mark.skipif(
    not use_postgres(), reason="C13 cần PostgreSQL — chạy với RAG_TEST_POSTGRES=1"
)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return 1.0 - dot / (na * nb)


@pytest.fixture()
def indexed(workspace: int):
    """Nạp vài đoạn có nội dung thật vào một hồ sơ, kèm vector."""
    from backend.config import settings
    from backend.db import get_conn
    from backend.rag import pgvector_store, store

    texts = [
        "Dự án hỗ trợ kinh phí xây nhà cho 113 hộ dân có hoàn cảnh khó khăn tại xã Thu Cúc.",
        "Tổng giá trị tài trợ của dự án là 6.780.000.000 đồng, tương đương sáu tỷ bảy trăm tám mươi triệu.",
        "Latter-Day Saint Charities là tổ chức nhân đạo của Giáo hội Các Thánh hữu Ngày sau.",
        "Lễ tổng kết và bàn giao công trình được tổ chức tại Ủy ban nhân dân xã Thu Cúc.",
        "The interpreter must render numerical figures precisely in both directions.",
    ]
    with get_conn() as conn:
        doc = conn.execute(
            "INSERT INTO documents (workspace_id, filename, stored_path, ext, status) "
            "VALUES (?, ?, ?, ?, 'ready')",
            (workspace, "ldsc-thu-cuc.doc", "/tmp/x.doc", ".doc"),
        ).lastrowid
        chunk_ids = []
        for i, text in enumerate(texts):
            cur = conn.execute(
                "INSERT INTO document_chunks (document_id, workspace_id, chunk_index, text, lang) "
                "VALUES (?, ?, ?, ?, 'vi')",
                (doc, workspace, i, text),
            )
            chunk_ids.append(int(cur.lastrowid or 0))

    vectors = store.embed_texts(texts)
    pgvector_store.upsert(chunk_ids, vectors, settings.embedding_model)
    return {
        "workspace": workspace,
        "document": int(doc or 0),
        "chunk_ids": chunk_ids,
        "texts": texts,
        "vectors": vectors,
    }


def test_c13a_chieu_vector_dung_nhu_khai_bao(indexed):
    """Chiều vector phải khớp con số mã nguồn khai báo — đo, không tin tài liệu."""
    from backend.rag import pgvector_store

    measured = len(indexed["vectors"][0])
    assert measured == pgvector_store.EMBEDDING_DIM, (
        f"Model sinh vector {measured} chiều nhưng schema khai báo "
        f"{pgvector_store.EMBEDDING_DIM}. Đổi model mà quên đổi schema là hỏng im lặng."
    )


def test_c13b_cach_ly_ho_so_la_dieu_kien_truy_van(indexed, secret_workspace: int):
    """Hồ sơ khác không được thấy vector của hồ sơ này, kể cả khi truy vấn khớp hoàn toàn."""
    from backend.rag import pgvector_store, store

    query_vector = store.embed_texts(["tổng giá trị tài trợ bao nhiêu"])[0]

    mine = pgvector_store.query(indexed["workspace"], query_vector, pool_size=10)
    assert mine, "hồ sơ của chính mình phải tìm được đoạn"

    other = pgvector_store.query(secret_workspace, query_vector, pool_size=10)
    assert other == [], (
        "Hồ sơ khác đọc được vector — cách ly phải nằm trong mệnh đề WHERE, "
        "không phải lọc sau khi đã lấy về."
    )


def test_c13c_xep_hang_khop_cosine_tinh_tay(indexed):
    """Thứ tự pgvector trả về phải giống hệt cosine tính tay trên cùng bộ vector."""
    from backend.rag import pgvector_store, store

    qv = store.embed_texts(["Dự án tài trợ bao nhiêu tiền cho các hộ dân?"])[0]

    rows = pgvector_store.query(indexed["workspace"], qv, pool_size=10)
    pg_order = [int(r["chunk_id"]) for r in rows]

    by_hand = sorted(
        zip(indexed["chunk_ids"], indexed["vectors"]),
        key=lambda pair: _cosine_distance(qv, pair[1]),
    )
    hand_order = [cid for cid, _ in by_hand]

    assert pg_order == hand_order, (
        "pgvector xếp hạng khác cosine tính tay.\n"
        f"  pgvector : {pg_order}\n"
        f"  tính tay : {hand_order}"
    )


def test_c13d_khoang_cach_khop_toi_sai_so_float32(indexed):
    """Khoảng cách phải khớp tới sai số float32 — pgvector lưu float32, Python dùng float64."""
    from backend.rag import pgvector_store, store

    qv = store.embed_texts(["Latter-Day Saint Charities là tổ chức gì?"])[0]
    rows = pgvector_store.query(indexed["workspace"], qv, pool_size=10)
    lookup = dict(zip(indexed["chunk_ids"], indexed["vectors"]))

    worst = 0.0
    for row in rows:
        expected = _cosine_distance(qv, lookup[int(row["chunk_id"])])
        worst = max(worst, abs(expected - float(row["distance"])))

    assert worst < 1e-5, f"lệch khoảng cách lớn nhất {worst:.3e} — quá lớn cho float32"


def test_c13e_xoa_tai_lieu_la_vector_bien_mat(indexed):
    """Spec A1.8: xoá rồi thì không còn xuất hiện trong truy hồi."""
    from backend.db import get_conn
    from backend.rag import pgvector_store, store

    ws = indexed["workspace"]
    assert pgvector_store.count(ws) == len(indexed["chunk_ids"])

    # Xoá TÀI LIỆU, không gọi hàm xoá vector: cascade của Postgres phải tự lo. Đây chính
    # là điểm hơn của việc đặt vector cùng bảng — không có cửa sổ nào vector còn sống
    # sau khi văn bản đã chết.
    with get_conn() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (indexed["document"],))

    assert pgvector_store.count(ws) == 0, "vector còn sót sau khi xoá tài liệu"
    qv = store.embed_texts(["tài trợ"])[0]
    assert pgvector_store.query(ws, qv, pool_size=10) == []


def test_c13f_nguong_075_van_phan_biet_dung(indexed):
    """Ngưỡng ngữ cảnh yếu 0.75 phải còn nghĩa trên thang đo của pgvector.

    Không đủ để nói "cùng công thức nên giữ nguyên": phải thấy nó thật sự tách được câu
    hỏi có trong tài liệu khỏi câu hỏi không liên quan.
    """
    from backend.rag import pgvector_store, store
    from backend.rag.qa import WEAK_CONTEXT_DISTANCE

    ws = indexed["workspace"]

    on_topic = store.embed_texts(["Tổng giá trị tài trợ của dự án là bao nhiêu đồng?"])[0]
    best_on = min(float(r["distance"]) for r in pgvector_store.query(ws, on_topic, 10))

    off_topic = store.embed_texts(
        ["Công thức nấu phở bò truyền thống Hà Nội gồm những gia vị nào?"]
    )[0]
    best_off = min(float(r["distance"]) for r in pgvector_store.query(ws, off_topic, 10))

    assert best_on < WEAK_CONTEXT_DISTANCE, (
        f"câu hỏi CÓ trong tài liệu lại bị coi là ngữ cảnh yếu "
        f"(khoảng cách {best_on:.3f} ≥ ngưỡng {WEAK_CONTEXT_DISTANCE})"
    )
    assert best_off > best_on, (
        f"câu hỏi lạc đề {best_off:.3f} không xa hơn câu đúng chủ đề {best_on:.3f}"
    )
