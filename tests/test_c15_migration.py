"""C15 / MIG — chuyển dữ liệu từ máy cá nhân lên PostgreSQL: đúng, lặp lại được, kiểm được.

Nguồn dùng trong bộ test này là một SQLite DỰNG RIÊNG, không phải `data/app.db` thật:
test không được đụng tới hồ sơ khách hàng, và một nguồn dựng sẵn thì kiểm được cả những
ca mà dữ liệu thật tình cờ không có (nhãn tin cậy đủ loại, ba trạng thái nhật ký, hồ sơ
thứ hai, quyền đồng ý còn sống).

  MIG1   chạy thử không ghi gì vào đích
  MIG2   lần chuyển đầu giữ đúng số dòng dữ liệu bền
  MIG3   lần chuyển thứ hai không sinh dòng trùng
  MIG4   nguồn hỏng khoá ngoại thì DỪNG, không ghi nửa vời
  MIG5   `owner_user_id` được gắn đúng
  MIG6   quyền đồng ý và trạng thái chạy KHÔNG được mang sang
  MIG7   trạng thái nhật ký lịch sử giữ nguyên, không diễn giải lại
  MIG8   số chunk và metadata giữ nguyên
  MIG9   số chiều vector đúng
  MIG10  verify độc lập bắt được dòng thiếu và dòng bị sửa ở đích
  MIG11  manifest tài liệu có SHA256 và CHỈ ở trạng thái pending_upload
  MIG12  nguồn SQLite và tệp tài liệu không đổi
  MIG13  hỏng nửa chừng thì chạy lại phục hồi được
"""

from __future__ import annotations

import hashlib
import pathlib
import sqlite3
import uuid

import pytest

from tests.conftest import use_postgres

pytestmark = pytest.mark.skipif(
    not use_postgres(), reason="MIG cần PostgreSQL — chạy với RAG_TEST_POSTGRES=1"
)

OWNER = "3f2b1c9e-7a41-4d58-9b06-2e5c8a1d4f77"


def _seed_source(path: pathlib.Path, docs_dir: pathlib.Path) -> dict:
    """Dựng một SQLite nguồn có đủ các ca cần kiểm."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Dùng chính schema của ứng dụng để nguồn giống thật, không tự chế bảng.
    from backend.db import _SCHEMA

    for stmt in _SCHEMA:
        conn.execute(stmt)
    for table, column, definition in __import__(
        "backend.db", fromlist=["_ADDED_COLUMNS"]
    )._ADDED_COLUMNS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    ws1 = conn.execute(
        "INSERT INTO workspaces (name, is_confidential, notes) VALUES ('Hồ sơ A', 1, 'ghi chú A')"
    ).lastrowid
    ws2 = conn.execute(
        "INSERT INTO workspaces (name, is_confidential) VALUES ('Hồ sơ B', 0)"
    ).lastrowid

    doc_file = docs_dir / "tai-lieu.txt"
    doc_file.write_text("Nội dung tài liệu thử nghiệm.", encoding="utf-8")
    size = doc_file.stat().st_size
    doc = conn.execute(
        "INSERT INTO documents (workspace_id, filename, stored_path, ext, size_bytes, "
        "content_hash, language, status, n_chunks) "
        "VALUES (?, 'tai-lieu.txt', ?, '.txt', ?, 'abc123', 'vi', 'ready', 2)",
        (ws1, str(doc_file), size),
    ).lastrowid

    chunks = []
    for i, text in enumerate(
        ["Dự án hỗ trợ 113 hộ dân tại xã Thu Cúc.",
         "Tổng giá trị tài trợ là 6.780.000.000 đồng."]
    ):
        chunks.append(
            conn.execute(
                "INSERT INTO document_chunks (document_id, workspace_id, chunk_index, text, "
                "locator, lang) VALUES (?, ?, ?, ?, ?, 'vi')",
                (doc, ws1, i, text, f"đoạn {i + 1}"),
            ).lastrowid
        )

    # Ba mức tin cậy khác nhau — chuyển xong phải còn nguyên ba mức đó.
    for term, conf, status in [
        ("hộ nghèo", "aligned_from_parallel", "expert_edited"),
        ("tài trợ", "machine_guess", "auto"),
        ("bàn giao", "machine_guess", "skipped"),
    ]:
        conn.execute(
            "INSERT INTO glossary (workspace_id, term_vi, term_en, term_vi_norm, "
            "confidence, status) VALUES (?, ?, ?, ?, ?, ?)",
            (ws1, term, term.upper(), term.lower(), conf, status),
        )

    run = conn.execute(
        "INSERT INTO research_runs (workspace_id, client_name, topic, status, n_sources) "
        "VALUES (?, 'Latter-Day Saint Charities', 'Lễ bàn giao nhà ở', 'completed', 12)",
        (ws1,),
    ).lastrowid
    prof = conn.execute(
        "INSERT INTO profiles (workspace_id, research_run_id, entity_name, entity_role) "
        "VALUES (?, ?, 'LDSC', 'client')",
        (ws1, run),
    ).lastrowid
    # has_source / is_expert_edited là NHÃN TIN CẬY: cả bốn tổ hợp phải qua được nguyên vẹn.
    for key, val, has_src, edited in [
        ("nganh", "nhân đạo", 1, 0),
        ("quy_mo", "toàn cầu", 0, 1),
        ("tru_so", "Hoa Kỳ", 1, 1),
        ("doan", "máy suy đoán", 0, 0),
    ]:
        f = conn.execute(
            "INSERT INTO profile_fields (profile_id, field_key, value, has_source, "
            "is_expert_edited) VALUES (?, ?, ?, ?, ?)",
            (prof, key, val, has_src, edited),
        ).lastrowid
        if has_src:
            conn.execute(
                "INSERT INTO profile_sources (profile_field_id, url, title) "
                "VALUES (?, 'https://vi.dụ/1', 'Nguồn')",
                (f,),
            )
    # Chuỗi buổi mock: session -> turn -> attempt -> score -> nhận định chuyên gia.
    # Cần đủ chuỗi này để kiểm rằng thứ tự chèn theo khoá ngoại là đúng, và `reference_tier`
    # qua được nguyên vẹn.
    sess = conn.execute(
        "INSERT INTO mock_sessions (workspace_id, mode, difficulty, n_turns, status, "
        "overall_score) VALUES (?, 'consecutive', 'medium', 2, 'completed', 6.5)",
        (ws1,),
    ).lastrowid
    turn = conn.execute(
        "INSERT INTO mock_turns (session_id, turn_index, speaker_name, speaker_role, "
        "source_lang, target_lang, source_text, reference_translation, reference_tier) "
        "VALUES (?, 0, 'Ông Walker', 'partner', 'vi', 'en', 'Xin kính chào quý vị.', "
        "'Good morning, distinguished guests.', 'ai')",
        (sess,),
    ).lastrowid
    attempt = conn.execute(
        "INSERT INTO turn_attempts (turn_id, session_id, transcript_edited, input_mode, "
        "response_time_sec) VALUES (?, ?, 'Good morning everyone.', 'typed', 42.5)",
        (turn, sess),
    ).lastrowid
    conn.execute(
        "INSERT INTO scores (attempt_id, score_meaning, score_terminology, "
        "score_completeness, score_expression, score_overall, comment) "
        "VALUES (?, 8, 7, 9, 8, 8.0, 'Sát nghĩa, thiếu sắc thái trang trọng.')",
        (attempt,),
    )
    # Điểm chuyên gia lưu RIÊNG, không ghi đè điểm máy chấm (spec §6).
    conn.execute(
        "INSERT INTO expert_verdicts (attempt_id, workspace_id, action, score_overall, note, "
        "related_category) VALUES (?, ?, 'adjust_score', 7.0, 'Chấm cao quá.', 'nghi_thuc')",
        (attempt, ws1),
    )
    conn.execute(
        "INSERT INTO qa_history (workspace_id, question, answer, confidence) "
        "VALUES (?, 'Tổng tài trợ bao nhiêu?', '6.780.000.000 đồng', 'grounded')",
        (ws1,),
    )

    conn.commit()
    conn.close()
    return {"ws1": ws1, "ws2": ws2, "doc": doc, "chunks": chunks,
            "session": sess, "turn": turn, "attempt": attempt,
            "doc_file": doc_file, "doc_sha": hashlib.sha256(doc_file.read_bytes()).hexdigest()}


def _seed_runtime_and_audit(path: pathlib.Path, ws: int) -> None:
    """Thêm trạng thái chạy (quyền đồng ý, thao tác) và nhật ký lịch sử ba trạng thái."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    op = "op-local-" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO operations (id, workspace_id, operation_kind, request_fingerprint, "
        "declares, expires_at) VALUES (?, ?, 'documents.ask', 'fp', '[]', "
        "datetime('now', '+15 minutes'))",
        (op, ws),
    )
    conn.execute(
        "INSERT INTO operation_calls (operation_id, destination, provider, allowed_calls, "
        "used_calls) VALUES (?, 'llm', 'gemini', 15, 3)",
        (op,),
    )
    conn.execute(
        "INSERT INTO consent_grants (workspace_id, operation_id, scope, destination, provider, "
        "expires_at) VALUES (?, NULL, 'session', 'llm', 'gemini', datetime('now', '+8 hours'))",
        (ws,),
    )
    conn.execute(
        "INSERT INTO pending_consents (id, operation_id, workspace_id, expires_at) "
        "VALUES (?, ?, ?, datetime('now', '+10 minutes'))",
        ("pc-" + uuid.uuid4().hex[:8], op, ws),
    )
    # Ba trạng thái nhật ký. `attempt_failed` KHÔNG được biến thành `blocked` khi chuyển:
    # nhà cung cấp ném lỗi không chứng minh dữ liệu chưa rời máy.
    for status, err in [("blocked", "ConsentRequired"),
                        ("attempt_succeeded", None),
                        ("attempt_failed", "NoAudioReceived")]:
        conn.execute(
            "INSERT INTO egress_log (workspace_id, module, destination, provider, endpoint, "
            "n_chars, summary, consented, status, error_class) "
            "VALUES (?, 'test.mod', 'llm', 'gemini', 'gemini:x', 100, 'tóm lược', ?, ?, ?)",
            (ws, 0 if status == "blocked" else 1, status, err),
        )
    conn.commit()
    conn.close()


def _reset_target() -> None:
    """Xoá sạch dữ liệu ở đích, kể cả sổ cái, trước mỗi test."""
    from backend.db import get_conn
    from backend.migration import ledger
    from backend.migration.spec import DURABLE, RUNTIME_SKIPPED

    ledger.ensure_table()
    with get_conn() as conn:
        # Xoá ngược thứ tự khoá ngoại: con trước, cha sau.
        for ent in reversed(DURABLE):
            conn.execute(f'DELETE FROM "{ent.table}"')
        for table in RUNTIME_SKIPPED:
            conn.execute(f'DELETE FROM "{table}"')
        conn.execute("DELETE FROM migration_runs")


@pytest.fixture()
def source(tmp_path, temp_data_dir):
    """Nguồn SQLite dựng sẵn + đích PostgreSQL sạch."""
    from backend.config import settings

    # Đích phải SẠCH ở đầu mỗi test. Cả bộ dùng chung một schema PostgreSQL, nên dòng
    # còn lại từ test trước sẽ làm những khẳng định kiểu "bảng này chưa tới lượt" sai —
    # và sai theo chiều báo đạt, tức là che mất lỗi thật.
    _reset_target()

    src_db = tmp_path / "source.db"
    ids = _seed_source(src_db, tmp_path / "documents")
    _seed_runtime_and_audit(src_db, ids["ws1"])

    saved = settings.db_path
    object.__setattr__(settings, "db_path", src_db)   # nguồn cho `inventory`
    try:
        yield {"db": src_db, **ids}
    finally:
        object.__setattr__(settings, "db_path", saved)


def _target_counts(tables: list[str]) -> dict[str, int]:
    from backend.db import get_conn

    with get_conn() as conn:
        return {
            t: int(conn.execute(f'SELECT COUNT(*) AS n FROM "{t}"').fetchone()["n"])
            for t in tables
        }


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ============================== MIG1 ==============================


def test_mig1_chay_thu_khong_ghi_gi_vao_dich(source):
    from backend.migration import runner
    from backend.migration.spec import durable_tables

    before = _target_counts(list(durable_tables()))
    result = runner.migrate(owner_user_id=OWNER, dry_run=True)
    after = _target_counts(list(durable_tables()))

    assert before == after, f"chạy thử đã ghi vào đích: {before} -> {after}"
    assert result.run_id is None, "chạy thử không được ghi cả vào sổ cái"
    assert all(t.written == 0 for t in result.tables)
    assert sum(t.source_rows for t in result.tables) > 0, "chạy thử phải ĐỌC được nguồn"


# ============================== MIG2 · MIG3 ==============================


def test_mig2_lan_dau_giu_dung_so_dong(source):
    from backend.migration import inventory, runner
    from backend.migration.spec import durable_tables

    inv = inventory.collect(measure_embedding=False)
    runner.migrate(owner_user_id=OWNER)
    target = _target_counts(list(durable_tables()))

    thieu = {t: (inv.row_counts.get(t, 0), target[t])
             for t in durable_tables()
             if target[t] < inv.row_counts.get(t, 0)}
    assert not thieu, f"đích thiếu dòng so với nguồn: {thieu}"


def test_mig3_lan_hai_khong_sinh_dong_trung(source):
    from backend.migration import runner
    from backend.migration.spec import durable_tables

    runner.migrate(owner_user_id=OWNER)
    sau_lan_1 = _target_counts(list(durable_tables()))
    runner.migrate(owner_user_id=OWNER)
    sau_lan_2 = _target_counts(list(durable_tables()))

    assert sau_lan_1 == sau_lan_2, (
        "chạy lần hai làm đổi số dòng — UPSERT theo khoá chính đang không giữ được id gốc:\n"
        f"  lần 1: {sau_lan_1}\n  lần 2: {sau_lan_2}"
    )


# ============================== MIG4 ==============================


def test_mig4_nguon_hong_khoa_ngoai_thi_dung_lai(source):
    """Nguồn có dòng trỏ tới khoá ngoại không tồn tại thì phải DỪNG, không ghi nửa vời."""
    from backend.migration import runner

    conn = sqlite3.connect(source["db"])
    conn.execute("PRAGMA foreign_keys = OFF")   # ép nguồn vào trạng thái hỏng
    conn.execute(
        "INSERT INTO document_chunks (document_id, workspace_id, chunk_index, text) "
        "VALUES (999999, ?, 99, 'mồ côi')",
        (source["ws1"],),
    )
    conn.commit()
    conn.close()

    with pytest.raises(Exception) as exc:
        runner.migrate(owner_user_id=OWNER)
    assert "foreign key" in str(exc.value).lower() or "violat" in str(exc.value).lower(), (
        f"dừng vì lý do khác chứ không phải khoá ngoại: {exc.value}"
    )

    from backend.migration import ledger

    lich_su = ledger.history()
    assert lich_su and lich_su[0]["status"] == "failed", (
        "lần chạy hỏng phải được ghi là `failed`, không được lẫn với `completed`"
    )


# ============================== MIG5 ==============================


def test_mig5_gan_dung_chu_so_huu(source):
    from backend.db import get_conn
    from backend.migration import runner

    runner.migrate(owner_user_id=OWNER)
    with get_conn() as conn:
        rows = conn.execute("SELECT id, name, owner_user_id FROM workspaces").fetchall()

    assert rows, "không có hồ sơ nào được chuyển"
    sai = [dict(r) for r in rows if str(r["owner_user_id"]) != OWNER]
    assert not sai, f"hồ sơ gắn sai chủ: {sai}"


def test_mig5b_tu_choi_uuid_dien_tam(source):
    """UUID đúng dạng nhưng là chỗ điền tạm thì phải bị chặn ở CLI."""
    import scripts.migrate_local_to_cloud as cli

    for bad in ("00000000-0000-0000-0000-000000000000", "user-1", "test-user"):
        with pytest.raises(SystemExit):
            cli._require_owner(bad, dry_run=False)
    with pytest.raises(SystemExit):
        cli._require_owner(None, dry_run=False)
    assert cli._require_owner(OWNER, dry_run=False) == OWNER


# ============================== MIG6 ==============================


def test_mig6_khong_mang_quyen_dong_y_va_trang_thai_chay(source):
    """Đồng ý trên máy cá nhân KHÔNG phải đồng ý cho máy chủ ở nơi khác."""
    from backend.db import get_conn
    from backend.migration import inventory, runner
    from backend.migration.spec import RUNTIME_SKIPPED

    inv = inventory.collect(measure_embedding=False)
    assert inv.skipped_counts.get("consent_grants", 0) > 0, "nguồn phải CÓ quyền để test có nghĩa"
    assert inv.skipped_counts.get("operations", 0) > 0

    runner.migrate(owner_user_id=OWNER)

    with get_conn() as conn:
        for table in RUNTIME_SKIPPED:
            n = int(conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"])
            assert n == 0, (
                f"`{table}` có {n} dòng ở đích — trạng thái bảo mật lúc chạy đã bị mang sang. "
                f"Lý do không được mang: {RUNTIME_SKIPPED[table][:90]}"
            )


# ============================== MIG7 ==============================


def test_mig7_trang_thai_nhat_ky_giu_nguyen(source):
    """Ba trạng thái nhật ký phải qua được nguyên vẹn, KHÔNG diễn giải lại."""
    from backend.db import get_conn
    from backend.migration import runner

    runner.migrate(owner_user_id=OWNER)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, error_class FROM egress_log ORDER BY id"
        ).fetchall()

    trang_thai = sorted(str(r["status"]) for r in rows)
    assert trang_thai == ["attempt_failed", "attempt_succeeded", "blocked"], (
        f"trạng thái nhật ký đã bị đổi khi chuyển: {trang_thai}"
    )
    failed = [r for r in rows if r["status"] == "attempt_failed"]
    assert failed and failed[0]["error_class"] == "NoAudioReceived", (
        "`attempt_failed` mất lớp lỗi, hoặc bị đổi thành `blocked` — nói rằng dữ liệu chưa "
        "rời máy trong khi không ai chứng minh được điều đó"
    )


def test_mig7b_nhan_tin_cay_giu_nguyen(source):
    """`has_source`, `is_expert_edited`, `confidence` chuyển nguyên trạng, không tự nâng."""
    from backend.db import get_conn
    from backend.migration import runner

    runner.migrate(owner_user_id=OWNER)
    with get_conn() as conn:
        fields = conn.execute(
            "SELECT field_key, has_source, is_expert_edited FROM profile_fields ORDER BY field_key"
        ).fetchall()
        conf = sorted(
            str(r["confidence"]) for r in conn.execute("SELECT confidence FROM glossary")
        )

    thuc = {str(r["field_key"]): (int(r["has_source"]), int(r["is_expert_edited"]))
            for r in fields}
    assert thuc == {
        "doan": (0, 0), "nganh": (1, 0), "quy_mo": (0, 1), "tru_so": (1, 1)
    }, f"nhãn tin cậy bị đổi khi chuyển: {thuc}"
    assert conf == ["aligned_from_parallel", "machine_guess", "machine_guess"], (
        f"mức tin cậy của thuật ngữ bị đổi: {conf}"
    )


# ============================== MIG8 · MIG9 ==============================


def test_mig8_chunk_va_metadata_giu_nguyen(source):
    from backend.db import get_conn
    from backend.migration import runner

    runner.migrate(owner_user_id=OWNER)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, document_id, workspace_id, chunk_index, text, locator, lang "
            "FROM document_chunks ORDER BY chunk_index"
        ).fetchall()

    assert len(rows) == 2, f"số chunk sai: {len(rows)}"
    assert [int(r["id"]) for r in rows] == source["chunks"], "id chunk không được giữ nguyên"
    assert [str(r["locator"]) for r in rows] == ["đoạn 1", "đoạn 2"], "mất vị trí trích dẫn"
    assert "6.780.000.000" in str(rows[1]["text"]), "văn bản chunk bị đổi"
    assert all(int(r["document_id"]) == source["doc"] for r in rows), "mất liên kết tài liệu"


def test_mig9_so_chieu_vector_dung(source):
    from backend.db import get_conn
    from backend.migration import runner
    from backend.rag import pgvector_store

    result = runner.migrate(owner_user_id=OWNER)
    assert result.chunks_embedded == 2, f"dựng lại {result.chunks_embedded} vector, mong đợi 2"
    assert pgvector_store.count() == 2

    with get_conn() as conn:
        dim = int(
            conn.execute(
                "SELECT vector_dims(embedding) AS d FROM document_chunks "
                "WHERE embedding IS NOT NULL LIMIT 1"
            ).fetchone()["d"]
        )
    assert dim == pgvector_store.EMBEDDING_DIM, (
        f"vector {dim} chiều nhưng schema khai {pgvector_store.EMBEDDING_DIM}"
    )


# ============================== MIG10 ==============================


def test_mig10_verify_doc_lap_bat_duoc_dong_thieu(source):
    """`verify` phải đọc lại từ đích, không tin kết quả trong bộ nhớ của `migrate`."""
    from backend.db import get_conn
    from backend.migration import runner, verify

    runner.migrate(owner_user_id=OWNER)
    assert verify.run(owner_user_id=OWNER).ok, "verify đỏ ngay sau khi chuyển xong"

    with get_conn() as conn:
        conn.execute("DELETE FROM glossary WHERE id = (SELECT MIN(id) FROM glossary)")

    res = verify.run(owner_user_id=OWNER)
    assert not res.ok, "xoá một dòng ở đích mà verify vẫn báo đạt"
    assert any(f.area == "glossary" and "thiếu" in f.detail for f in res.findings), (
        f"verify đỏ nhưng không chỉ ra đúng chỗ: {[f.detail for f in res.findings]}"
    )


def test_mig10b_verify_bat_duoc_dong_bi_sua(source):
    """Đếm bằng nhau CHƯA ĐỦ — sửa nội dung một dòng phải bị bắt."""
    from backend.db import get_conn
    from backend.migration import runner, verify

    runner.migrate(owner_user_id=OWNER)

    with get_conn() as conn:
        # Đúng loại thay đổi nguy hiểm nhất: nâng mức tin cậy của một thuật ngữ.
        conn.execute(
            "UPDATE glossary SET confidence = 'aligned_from_parallel' "
            "WHERE confidence = 'machine_guess'"
        )

    res = verify.run(owner_user_id=OWNER)
    assert not res.ok, "sửa nội dung dòng mà verify vẫn báo đạt — chỉ đếm là không đủ"
    assert any("confidence" in f.detail for f in res.findings), (
        f"verify không chỉ ra cột bị sửa: {[f.detail for f in res.findings]}"
    )


# ============================== MIG11 ==============================


def test_mig11_manifest_tai_lieu_chi_o_trang_thai_cho_tai_len(source):
    """Phase 6 chỉ kiểm kê tệp. Ghi bất kỳ trạng thái nào khác là tuyên bố việc chưa xảy ra."""
    from backend.migration import inventory

    inv = inventory.collect(measure_embedding=False)
    assert inv.documents, "không kiểm kê được tài liệu nào"

    for d in inv.documents:
        assert d.cloud_status == "pending_upload", (
            f"tài liệu #{d.document_id} mang trạng thái `{d.cloud_status}` — "
            "chưa có tệp nào được tải lên kho riêng ở giai đoạn này"
        )
        assert d.sha256 and len(d.sha256) == 64, "thiếu SHA256"
        assert d.exists and d.size_matches_db

    assert inv.documents[0].sha256 == source["doc_sha"], "SHA256 không khớp tệp thật"
    assert len(inv.document_manifest_sha256) == 64
    assert len(inv.fingerprint) == 64


def test_mig11b_bao_cao_khong_noi_da_tai_len(source):
    from backend.migration import runner

    result = runner.migrate(owner_user_id=OWNER, dry_run=True)
    d = result.to_dict()
    assert d["documents_cloud_uploaded"] == 0
    assert d["documents_inventoried"] == 1


# ============================== MIG12 ==============================


def test_mig12_nguon_khong_bi_dung_toi(source):
    """Bản chạy local là điểm quay lui DUY NHẤT. Migration không được ghi vào nó."""
    from backend.migration import runner

    db_truoc = _sha(source["db"])
    tep_truoc = _sha(source["doc_file"])

    runner.migrate(owner_user_id=OWNER)

    assert _sha(source["db"]) == db_truoc, (
        "SHA256 của SQLite nguồn đã đổi — migration đã ghi vào bản gốc"
    )
    assert _sha(source["doc_file"]) == tep_truoc, "tệp tài liệu nguồn đã bị đụng tới"


def test_mig12b_nguon_mo_o_che_do_chi_doc(source):
    """Chặn bằng hệ điều hành, không dựa vào việc mã không viết lệnh ghi nào."""
    from backend.migration import inventory

    conn = inventory.open_source_readonly(source["db"])
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE workspaces SET name = 'bị sửa' WHERE id = ?", (source["ws1"],))
    finally:
        conn.close()


# ============================== MIG13 ==============================


def test_mig13_hong_nua_chung_thi_chay_lai_phuc_hoi_duoc(source):
    """Hỏng sau `documents`, trước `glossary` — chạy lại phải xong, không nhân đôi."""
    from backend.migration import ledger, runner, verify
    from backend.migration.spec import durable_tables

    with pytest.raises(runner.MigrationError):
        runner.migrate(owner_user_id=OWNER, fault_after="documents")

    giua_chung = _target_counts(list(durable_tables()))
    assert giua_chung["workspaces"] > 0, "bảng chép xong trước lúc hỏng phải còn nguyên"
    assert giua_chung["glossary"] == 0, "bảng chưa tới lượt không được có dòng nào"

    lich_su = ledger.history()
    assert lich_su[0]["status"] == "failed" and lich_su[0]["error_class"] == "MigrationError", (
        f"sổ cái không ghi đúng lần chạy hỏng: {lich_su[0]}"
    )

    runner.migrate(owner_user_id=OWNER)
    sau_khi_lai = _target_counts(list(durable_tables()))

    assert sau_khi_lai["workspaces"] == giua_chung["workspaces"], "chạy lại làm nhân đôi hồ sơ"
    assert sau_khi_lai["glossary"] == 3, "chạy lại không hoàn tất phần còn dở"
    assert verify.run(owner_user_id=OWNER).ok, "sau khi phục hồi, verify vẫn không đạt"

    trang_thai = [h["status"] for h in ledger.history()]
    assert trang_thai[:2] == ["completed", "failed"], (
        f"sổ cái phải phân biệt lần hỏng với lần xong: {trang_thai[:2]}"
    )


# ============================== Vân tay ==============================


def test_mig14_van_tay_doi_khi_nguon_doi(source):
    """Vân tay phải trả lời được: trạng thái cloud này dựng từ ảnh chụp local nào."""
    from backend.migration import inventory

    a = inventory.collect(measure_embedding=False).fingerprint

    conn = sqlite3.connect(source["db"])
    conn.execute("INSERT INTO qa_history (workspace_id, question, answer) VALUES (?, 'x', 'y')",
                 (source["ws1"],))
    conn.commit()
    conn.close()

    b = inventory.collect(measure_embedding=False).fingerprint
    assert a != b, "thêm dòng vào nguồn mà vân tay không đổi — không phân biệt được ảnh chụp"
