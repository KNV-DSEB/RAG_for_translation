"""C16 / ST — kho tài liệu riêng: khoá do máy chủ dựng, chốt kiểm lại, xoá nói thật.

  ST1   tên tệp độc hại bị làm sạch, không thoát ra ngoài thư mục kho
  ST2   khoá mang sẵn ranh giới sở hữu (user + workspace + document)
  ST3   client KHÔNG khai được nơi ghi
  ST4   luồng đủ ba bước chạy được: giấy phép → tải lên → chốt
  ST5   chốt mà kho chưa có tệp thì TỪ CHỐI, không đánh dấu là đã lên
  ST6   chốt tự tính SHA256 từ nội dung THẬT, không tin client
  ST7   giấy phép dùng một lần, hết hạn, và có trần dung lượng
  ST8   người B không xin được giấy phép trên hồ sơ của A
  ST9   nhật ký kho tách bạch với nhật ký gửi ra bên thứ ba
  ST10  xoá thất bại thì KHÔNG được báo là đã xoá
  ST11  kiểu tệp ngoài danh sách cho phép bị từ chối

Chạy trên `LocalStorage` — kho THẬT của bản chạy trên máy, không phải bản giả lập
Supabase. Nó chứng minh LUỒNG đúng; nó KHÔNG chứng minh Supabase hành xử như tài liệu
mô tả. Chuyện đó cần credential thật, và máy phát triển không có.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

OWNER = "7c1e4a92-3b58-4f60-8d21-9a5e0c3b7f14"


@pytest.fixture()
def as_user(temp_data_dir):
    """Gắn một danh tính đã xác minh vào request hiện tại, và kho tạm."""
    from backend.auth.context import set_request_identity
    from backend.auth.verify import AuthUser
    from backend.storage import reset_backend

    reset_backend()
    set_request_identity(AuthUser(user_id=OWNER, email="expert@example.test"), "phien-1")
    try:
        yield OWNER
    finally:
        set_request_identity(None, None)
        reset_backend()


# ============================== ST1 · ST2 · ST3 ==============================


def test_st1_ten_tep_doc_hai_bi_lam_sach():
    from backend.storage.paths import UnsafeName, sanitize_filename

    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\Windows\system32\cmd.exe") == "cmd.exe"
    assert sanitize_filename("Kế hoạch tổng thể(en).docx") == "Ke-hoach-tong-the-en.docx"
    assert sanitize_filename("zPHÁT BIỂU 22 6.doc") == "zPHAT-BIEU-22-6.doc"
    # Dấu tiếng Việt chuyển sang không dấu, KHÔNG bị xoá — mất hết chữ thì tên vô nghĩa.
    assert sanitize_filename("Đề án 2024.PDF") == "De-an-2024.pdf"
    for bad in ("", "  ", "..", "."):
        with pytest.raises(UnsafeName):
            sanitize_filename(bad)


def test_st2_khoa_mang_san_ranh_gioi_so_huu():
    from backend.storage.paths import document_key

    key = document_key(OWNER, 3, 22, "báo cáo.docx")
    assert key == f"users/{OWNER}/workspaces/3/documents/22/bao-cao.docx"
    # Ba mảnh danh tính nằm trong đường dẫn nên chính sách của kho chặn được theo tiền tố.
    assert key.startswith(f"users/{OWNER}/")
    assert "/workspaces/3/" in key and "/documents/22/" in key


def test_st3_khong_khai_duoc_noi_ghi():
    """Mọi mảnh độc hại phải bị chặn hoặc trung hoà, không ghép được thành đường thoát."""
    from backend.storage.paths import UnsafeName, document_key

    with pytest.raises(UnsafeName):
        document_key("../../evil", 3, 22, "x.doc")
    with pytest.raises(UnsafeName):
        document_key("", 3, 22, "x.doc")

    # Tên tệp độc hại KHÔNG được đẩy khoá ra khỏi tiền tố sở hữu.
    key = document_key(OWNER, 3, 22, "../../../../root/.ssh/authorized_keys")
    assert key.startswith(f"users/{OWNER}/workspaces/3/documents/22/")
    assert ".." not in key


def test_st3b_kho_chan_khoa_thoat_ra_ngoai(tmp_path):
    """Chốt thứ hai đặt ngay chỗ ghi đĩa, không phụ thuộc việc gọi đúng hàm dựng khoá."""
    from backend.storage.base import StorageError
    from backend.storage.local import LocalStorage

    store = LocalStorage(tmp_path / "objects")
    with pytest.raises(StorageError):
        store.stat("../../thoat-ra-ngoai.txt")


# ============================== ST4 · ST5 · ST6 ==============================


def _new_workspace(name: str) -> int:
    from backend.db import get_conn

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO workspaces (name, owner_user_id) VALUES (?, ?)",
            (f"{name} {uuid.uuid4().hex[:6]}", OWNER),
        )
    return int(cur.lastrowid or 0)


def test_st4_luong_ba_buoc_chay_duoc(as_user):
    """giấy phép → tải lên → chốt, đi hết bằng đúng các hàm mà route gọi."""
    from backend.db import get_conn
    from backend.storage import get_backend
    from backend.storage.service import create_intent, finalize

    ws = _new_workspace("Hồ sơ ST4")
    data = "Tổng giá trị tài trợ là 6.780.000.000 đồng.".encode("utf-8")

    intent = create_intent(ws, "báo cáo tổng kết.docx", len(data))
    assert intent.storage_key.startswith(f"users/{OWNER}/workspaces/{ws}/documents/")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT storage_state, storage_key FROM documents WHERE id = ?",
            (intent.document_id,),
        ).fetchone()
    assert row["storage_state"] == "awaiting_upload", (
        "trước khi tệp lên kho, tài liệu phải ở trạng thái chờ — không được coi là sẵn sàng"
    )

    token = intent.ticket.url.rsplit("/", 1)[-1]
    get_backend().consume_ticket(token, data)

    result = finalize(intent.document_id)
    assert result["storage_state"] == "uploaded"
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["size_bytes"] == len(data)
    assert result["declared_size_matched"] is True


def test_st5_chot_khi_kho_chua_co_tep_thi_tu_choi(as_user):
    """Trình duyệt báo xong mà kho trống → phải TỪ CHỐI, giữ nguyên trạng thái chờ."""
    from backend.db import get_conn
    from backend.storage.service import UploadRejected, create_intent, finalize

    ws = _new_workspace("Hồ sơ ST5")
    intent = create_intent(ws, "chua-tai.docx", 100)

    with pytest.raises(UploadRejected):
        finalize(intent.document_id)

    with get_conn() as conn:
        state = conn.execute(
            "SELECT storage_state FROM documents WHERE id = ?", (intent.document_id,)
        ).fetchone()["storage_state"]
    assert state == "awaiting_upload", (
        f"trạng thái thành `{state}` dù kho chưa có tệp — một tài liệu 'sẵn sàng' mà mở "
        "ra thì rỗng còn tệ hơn một tài liệu báo lỗi"
    )


def test_st6_chot_tu_tinh_sha256_khong_tin_client(as_user):
    """Client tải lên NỘI DUNG KHÁC với cỡ đã khai → máy chủ phải ghi theo nội dung thật."""
    from backend.storage import get_backend
    from backend.storage.service import create_intent, finalize

    ws = _new_workspace("Hồ sơ ST6")
    khai_bao = b"noi dung ngan"
    thuc_te = b"noi dung THUC TE dai hon han so voi thu da khai bao truoc do"

    intent = create_intent(ws, "tep.txt", len(khai_bao))
    token = intent.ticket.url.rsplit("/", 1)[-1]
    get_backend().consume_ticket(token, thuc_te)

    result = finalize(intent.document_id)
    assert result["sha256"] == hashlib.sha256(thuc_te).hexdigest(), (
        "SHA256 tính theo nội dung khai báo chứ không phải nội dung thật"
    )
    assert result["size_bytes"] == len(thuc_te)
    assert result["declared_size_matched"] is False, (
        "lệch cỡ so với lúc khai mà không báo — đó là dấu hiệu lần tải lên không trọn vẹn"
    )


# ============================== ST7 ==============================


def test_st7_giay_phep_dung_mot_lan_va_co_tran(as_user):
    from backend.storage import get_backend
    from backend.storage.base import StorageError
    from backend.storage.service import create_intent

    ws = _new_workspace("Hồ sơ ST7")
    data = b"x" * 50
    intent = create_intent(ws, "a.txt", len(data))
    token = intent.ticket.url.rsplit("/", 1)[-1]

    get_backend().consume_ticket(token, data)
    with pytest.raises(StorageError, match="đã dùng"):
        get_backend().consume_ticket(token, data)

    intent2 = create_intent(ws, "b.txt", 100)
    token2 = intent2.ticket.url.rsplit("/", 1)[-1]
    with pytest.raises(StorageError, match="vượt mức"):
        get_backend().consume_ticket(token2, b"y" * 999_999)

    with pytest.raises(StorageError):
        get_backend().consume_ticket("token-bia-ra", b"z")


# ============================== ST9 · ST10 · ST11 ==============================


def test_st9_nhat_ky_kho_tach_bach_voi_nhat_ky_ben_thu_ba(as_user):
    """Lưu tệp vào kho của ứng dụng KHÔNG được sinh dòng nào trong `egress_log`.

    Nếu nó sinh, chuyên gia mở màn Bảo mật lên sẽ thấy hàng chục dòng "đã gửi dữ liệu ra
    ngoài" cho những việc thật ra chỉ là lưu tệp — và lần gửi THẬT cho Gemini chìm giữa
    chúng. Nhật ký mất tác dụng đúng lúc cần nhất.
    """
    from backend.db import get_conn
    from backend.storage import get_backend
    from backend.storage.service import create_intent, finalize

    ws = _new_workspace("Hồ sơ ST9")
    with get_conn() as conn:
        egress_truoc = int(
            conn.execute("SELECT COUNT(*) AS n FROM egress_log").fetchone()["n"]
        )

    data = b"noi dung tai lieu"
    intent = create_intent(ws, "tai-lieu.txt", len(data))
    get_backend().consume_ticket(intent.ticket.url.rsplit("/", 1)[-1], data)
    finalize(intent.document_id)

    with get_conn() as conn:
        egress_sau = int(conn.execute("SELECT COUNT(*) AS n FROM egress_log").fetchone()["n"])
        su_kien = [
            dict(r)
            for r in conn.execute(
                "SELECT event, object_key, sha256 FROM storage_events "
                "WHERE workspace_id = ? ORDER BY id",
                (ws,),
            ).fetchall()
        ]

    assert egress_sau == egress_truoc, (
        f"lưu tệp sinh ra {egress_sau - egress_truoc} dòng trong `egress_log` — kho của "
        "chính ứng dụng không phải bên thứ ba"
    )
    assert [e["event"] for e in su_kien] == ["upload_intent", "uploaded"], (
        f"vòng đời dữ liệu không được ghi đủ: {[e['event'] for e in su_kien]}"
    )
    assert su_kien[-1]["sha256"] == hashlib.sha256(data).hexdigest()


def test_st10_xoa_that_bai_khong_duoc_bao_la_da_xoa(as_user, monkeypatch):
    """Kho và cơ sở dữ liệu không chung giao dịch — xoá hỏng thì phải NÓI là hỏng."""
    from backend.db import get_conn
    from backend.storage import get_backend
    from backend.storage.base import StorageError
    from backend.storage.service import create_intent, delete_document_object, finalize

    ws = _new_workspace("Hồ sơ ST10")
    data = b"tai lieu se bi xoa"
    intent = create_intent(ws, "xoa.txt", len(data))
    get_backend().consume_ticket(intent.ticket.url.rsplit("/", 1)[-1], data)
    finalize(intent.document_id)

    def kho_tu_choi(_key: str) -> bool:
        raise StorageError("kho lưu trữ đang không truy cập được")

    monkeypatch.setattr(get_backend(), "delete", kho_tu_choi)
    ket_qua = delete_document_object(intent.document_id)

    assert ket_qua["deleted"] is False, (
        "kho từ chối xoá mà vẫn báo đã xoá — nói với chuyên gia rằng tài liệu khách hàng "
        "đã biến mất trong khi nó vẫn nằm trên kho"
    )
    with get_conn() as conn:
        state = conn.execute(
            "SELECT storage_state FROM documents WHERE id = ?", (intent.document_id,)
        ).fetchone()["storage_state"]
        events = [
            r["event"]
            for r in conn.execute(
                "SELECT event FROM storage_events WHERE document_id = ? ORDER BY id",
                (intent.document_id,),
            ).fetchall()
        ]
    assert state == "delete_failed", f"trạng thái là `{state}`, phải là `delete_failed`"
    assert "delete_failed" in events, "lần xoá hỏng không để lại dấu vết nào"


def test_st10b_xoa_thanh_cong_thi_tep_bien_mat_that(as_user):
    from backend.storage import get_backend
    from backend.storage.service import create_intent, delete_document_object, finalize

    ws = _new_workspace("Hồ sơ ST10b")
    data = b"tai lieu"
    intent = create_intent(ws, "that.txt", len(data))
    get_backend().consume_ticket(intent.ticket.url.rsplit("/", 1)[-1], data)
    finalize(intent.document_id)

    key = intent.storage_key
    assert get_backend().stat(key) is not None

    ket_qua = delete_document_object(intent.document_id)
    assert ket_qua["deleted"] is True
    assert get_backend().stat(key) is None, "báo đã xoá nhưng tệp vẫn còn trên kho"


def test_st11_kieu_tep_ngoai_danh_sach_bi_tu_choi(as_user):
    """Danh sách CHO PHÉP, không phải danh sách cấm — quên chặn thì không ai biết."""
    from backend.storage.service import ALLOWED_EXT, UploadRejected, create_intent

    ws = _new_workspace("Hồ sơ ST11")
    for ten in ("virus.exe", "script.js", "trang.html", "khong-duoi", "anh.png"):
        with pytest.raises(UploadRejected):
            create_intent(ws, ten, 100)

    for ext in ALLOWED_EXT:
        intent = create_intent(ws, f"hop-le{ext}", 100)
        assert intent.document_id > 0


def test_st11b_tep_rong_va_tep_qua_lon_bi_tu_choi(as_user):
    from backend.config import settings
    from backend.storage.service import UploadRejected, create_intent

    ws = _new_workspace("Hồ sơ ST11b")
    with pytest.raises(UploadRejected, match="rỗng"):
        create_intent(ws, "a.txt", 0)
    with pytest.raises(UploadRejected, match="vượt mức"):
        create_intent(ws, "a.txt", settings.max_upload_mb * 1024 * 1024 + 1)


# ============================== ST8 ==============================


def test_st8_nguoi_b_khong_xin_duoc_giay_phep_tren_ho_so_cua_a(temp_data_dir):
    """Xin giấy phép trên hồ sơ người khác phải bị chặn Ở ROUTE, trước khi tới kho.

    Kiểm qua HTTP thật chứ không gọi thẳng hàm: chốt quyền nằm ở `workspace_guard`, và
    gọi thẳng hàm sẽ đi vòng qua đúng thứ cần kiểm.
    """
    import time

    import jwt
    from fastapi.testclient import TestClient

    from backend.config import settings
    from backend.storage import reset_backend

    SECRET = "khoa-thu-nghiem-chi-dung-trong-test-32bytes"
    reset_backend()
    override = {
        "supabase_jwt_secret": SECRET,
        "supabase_jwt_jwks": "",
        "supabase_jwt_audience": "authenticated",
        "supabase_jwt_issuer": "",
        "allowed_user_emails": ("expert@example.test",),
    }
    saved = {k: getattr(settings, k) for k in override}
    for k, v in override.items():
        object.__setattr__(settings, k, v)

    def token(sub: str) -> dict[str, str]:
        now = int(time.time())
        raw = jwt.encode(
            {"sub": sub, "email": "expert@example.test", "iat": now, "exp": now + 600,
             "aud": "authenticated"},
            SECRET, algorithm="HS256",
        )
        return {"Authorization": "Bearer " + raw}

    try:
        from backend.main import app

        with TestClient(app) as client:
            a, b = str(uuid.uuid4()), str(uuid.uuid4())
            created = client.post(
                "/workspaces", headers=token(a),
                json={"name": "Cua A " + uuid.uuid4().hex[:6], "is_confidential": True},
            )
            assert created.status_code == 201, created.text[:200]
            ws = created.json()["id"]

            r = client.post(
                "/documents/upload-intent", headers=token(b),
                json={"workspace_id": ws, "filename": "trom.docx", "size_bytes": 100},
            )
            assert r.status_code in (403, 404), (
                f"B xin được giấy phép tải tệp vào hồ sơ của A (nhận {r.status_code}) — "
                "kho sẽ có tệp của B nằm dưới tiền tố sở hữu của A"
            )

            r2 = client.get(f"/documents/storage-events?workspace_id={ws}", headers=token(b))
            assert r2.status_code in (403, 404), "B đọc được nhật ký kho của A"
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)
        reset_backend()
