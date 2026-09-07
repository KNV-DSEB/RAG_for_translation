"""C17 / UP — đồng ý tải lên: hai lớp tách bạch, câu chữ sinh từ nơi dữ liệu thật sự nằm.

Ranh giới tin cậy MỚI mà bản chạy trên máy không có
---------------------------------------------------
Trên máy cá nhân, "tải tệp lên" nghĩa là chép từ thư mục này sang thư mục khác trên cùng
cái máy đó. Trên web, nó nghĩa là tệp RỜI KHỎI thiết bị của chuyên gia sang một máy chủ ở
nơi khác. Hai việc hoàn toàn khác nhau mang cùng một cái tên.

  Lớp A  "tệp có rời khỏi thiết bị của tôi sang kho của ứng dụng không?"
  Lớp B  "dữ liệu có sang Gemini / DuckDuckGo / Microsoft / Google không?"

  UP1  lớp A nói ĐÚNG ở từng chế độ (local: không rời máy; cloud: rời thiết bị)
  UP2  lớp A KHÔNG dựng hộp thoại gửi-ra-ngoài, và không sinh dòng `egress_log`
  UP3  lớp B nói rõ dữ liệu đi TỪ ĐÂU — kiểm CẢ HAI chế độ, không bỏ qua chiều nào
  UP4  bản đồ dữ liệu sinh từ cấu hình, không viết cứng
  UP5  bản đồ KHÔNG nhắc tới tính năng đã bị gỡ khỏi dự án
  UP6  không còn chuỗi hiển thị nào viết cứng "rời khỏi máy này"
  UP7  người B không xem được bản đồ/thông báo của hồ sơ A
"""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OWNER = "b4d7e219-6c30-4a85-9f12-7e3a0d5c8b46"


@pytest.fixture()
def as_user(temp_data_dir):
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


def _ws(name: str) -> int:
    from backend.db import get_conn

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO workspaces (name, owner_user_id, is_confidential) VALUES (?, ?, 1)",
            (f"{name} {uuid.uuid4().hex[:6]}", OWNER),
        )
    return int(cur.lastrowid or 0)


def _as_cloud_storage():
    """Ép cấu hình sang chế độ kho cloud, KHÔNG gọi mạng."""
    from backend.config import settings
    from backend.storage import reset_backend

    # `Settings` là frozen dataclass — cố ý, để mã chạy không đổi cấu hình giữa chừng.
    # Test là ngoại lệ hợp lệ duy nhất, và `monkeypatch.undo` trả lại nguyên trạng.
    saved = {k: getattr(settings, k) for k in
             ("supabase_url", "supabase_service_key", "supabase_bucket")}
    for k, v in (("supabase_url", "https://vidu.supabase.co"),
                 ("supabase_service_key", "khoa-gia-chi-de-doi-che-do"),
                 ("supabase_bucket", "documents")):
        object.__setattr__(settings, k, v)
    reset_backend()

    def khoi_phuc() -> None:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)
        reset_backend()

    return khoi_phuc


# ============================== UP1 ==============================


def test_up1_lop_a_noi_dung_o_tung_che_do(as_user):
    """Bản local: tệp KHÔNG rời máy. Bản cloud: tệp RỜI thiết bị. Câu chữ phải khác nhau."""
    from backend.storage.service import upload_notice

    ws = _ws("Hồ sơ UP1")
    local = upload_notice(ws, "báo cáo.docx", 1024)

    assert local["leaves_device"] is False
    assert local["requires_acknowledgement"] is False
    assert local["boundary"] == "device"
    assert "không rời khỏi máy" in local["headline"].lower()
    assert local["third_party_involved"] is False


def test_up1b_che_do_cloud_noi_thang_la_roi_thiet_bi(as_user):
    from backend.storage.service import upload_notice

    ws = _ws("Hồ sơ UP1b")
    khoi_phuc = _as_cloud_storage()
    try:
        cloud = upload_notice(ws, "báo cáo.docx", 1024)
    finally:
        khoi_phuc()

    assert cloud["leaves_device"] is True, (
        "chế độ cloud mà vẫn báo tệp không rời thiết bị — chuyên gia sẽ tin rằng tài liệu "
        "khách hàng vẫn trong tầm tay mình"
    )
    assert cloud["requires_acknowledgement"] is True
    assert cloud["boundary"] == "app_cloud"
    assert "rời khỏi thiết bị" in cloud["headline"].lower()
    # Nhưng KHÔNG được nói là đã gửi cho bên thứ ba — đó là chuyện khác hẳn.
    assert cloud["third_party_involved"] is False
    for ten in ("gemini", "google", "duckduckgo", "microsoft"):
        assert ten not in cloud["headline"].lower(), (
            f"thông báo tải lên nhắc tới `{ten}` — gộp lớp A với lớp B"
        )
    assert "vẫn phải xin phép" in cloud["after_note"]


def test_up1c_thong_bao_hien_du_bon_thong_tin(as_user):
    """Tên tệp, cỡ, hồ sơ, và nơi đến — thiếu mục nào thì chuyên gia không quyết được."""
    from backend.storage.service import upload_notice

    ws = _ws("Hồ sơ UP1c")
    n = upload_notice(ws, "Kế hoạch tổng thể.docx", 67871)
    assert n["filename"] == "Kế hoạch tổng thể.docx"
    assert n["size_bytes"] == 67871
    assert n["workspace_id"] == ws and n["workspace_name"].startswith("Hồ sơ UP1c")
    assert n["destination"]
    assert n["is_confidential"] is True


# ============================== UP2 · UP3 ==============================


def test_up2_lop_a_khong_dung_hop_thoai_gui_ra_ngoai(as_user):
    """Xem thông báo tải lên KHÔNG được sinh dòng `egress_log` hay challenge đồng ý.

    Nếu nó sinh, mỗi lần chọn tệp lại hiện hộp thoại "gửi dữ liệu ra ngoài" — và chuyên
    gia sẽ quen tay bấm đồng ý, đúng lúc hộp thoại thật sự quan trọng xuất hiện.
    """
    from backend.db import get_conn
    from backend.storage.service import upload_notice

    ws = _ws("Hồ sơ UP2")
    khoi_phuc = _as_cloud_storage()

    with get_conn() as conn:
        truoc = {
            t: int(conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"])
            for t in ("egress_log", "pending_consents", "operations", "consent_grants")
        }

    upload_notice(ws, "tai-lieu.docx", 2048)

    with get_conn() as conn:
        sau = {
            t: int(conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"])
            for t in truoc
        }

    khoi_phuc()
    assert sau == truoc, (
        f"xem thông báo tải lên đã đụng vào trạng thái của lớp B: {truoc} -> {sau}"
    )


def test_up3_lop_b_noi_ro_du_lieu_di_tu_dau(as_user):
    """Trên cloud, "rời khỏi máy này" là sai — tài liệu đã ở kho riêng từ trước."""
    from backend.security import gateway

    ws = _ws("Hồ sơ UP3")
    declares = (
        gateway.OperationDeclaration(
            destination="llm", provider="gemini", unit_calls=1, retries_each=0
        ),
    )

    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(ws, kind="test.up3", declares=declares, fingerprint="fp-up3"):
            pass
    preview = exc.value.preview

    # Kiểm CẢ HAI chiều, không bỏ qua chế độ nào. Chỉ kiểm một chiều thì không phân biệt
    # được "câu chữ theo đúng chế độ" với "câu chữ viết cứng tình cờ đúng ở chế độ này".
    from backend.database import driver

    d = preview.as_dict()
    if driver.is_postgres():
        assert preview.origin_phrase != "ra ngoài", (
            "chạy trên cloud mà câu chữ vẫn nói `ra ngoài` như bản chạy trên máy — dữ "
            "liệu đi TỪ kho riêng của ứng dụng, không phải từ máy chuyên gia"
        )
        assert "kho riêng của ứng dụng" in preview.scope_note
        assert "bên thứ ba" in preview.scope_note
        assert "rời khỏi máy này" not in d["payload_origin_label"], (
            "nhãn nội dung vẫn nói `rời khỏi máy này` trong khi tài liệu đã ở máy chủ khác"
        )
    else:
        assert preview.origin_phrase == "ra ngoài", (
            "chạy trên máy cá nhân mà lại nói dữ liệu đi từ kho riêng — vòng vo một cách "
            "vô ích, và sai: tài liệu đang nằm ngay trên máy chuyên gia"
        )
        assert "rời khỏi máy này" in d["payload_origin_label"]


# ============================== UP4 · UP5 · UP6 ==============================


def test_up4_ban_do_du_lieu_sinh_tu_cau_hinh(as_user):
    """Bản đồ phải ĐỔI khi cấu hình đổi. Không đổi nghĩa là nó viết cứng."""
    from backend.security import datamap

    khoi_phuc = _as_cloud_storage()
    try:
        cloud_rows = {r["what"]: r for r in datamap.data_map()}
        cloud_head = datamap.headline()
    finally:
        khoi_phuc()

    # Kiểm CẢ BA dòng đổi được theo cấu hình, không chỉ dòng tệp tài liệu.
    #
    # Bản đầu của test này chỉ kiểm "Tệp tài liệu". Một phép thử phá hoại — ép dòng cơ sở
    # dữ liệu luôn báo `device` — vẫn cho test xanh, vì dòng tệp tài liệu che mất. Đúng
    # dòng "Cơ sở dữ liệu" mới là khẳng định từng sai trên cloud, nên bỏ sót nó là bỏ
    # sót đúng thứ cần canh.
    from backend.database import driver

    mong_doi = "app_cloud" if driver.is_postgres() else "device"
    assert cloud_rows["Cơ sở dữ liệu"]["boundary"] == mong_doi, (
        f"dòng `Cơ sở dữ liệu` báo `{cloud_rows['Cơ sở dữ liệu']['boundary']}` nhưng "
        f"cơ sở dữ liệu thật đang ở `{mong_doi}`"
    )
    assert cloud_rows["Chỉ mục ngữ nghĩa"]["boundary"] == mong_doi, (
        "dòng `Chỉ mục ngữ nghĩa` không theo cơ sở dữ liệu thật"
    )
    assert cloud_rows["Tệp tài liệu"]["boundary"] == "app_cloud"
    assert "Supabase" in cloud_rows["Tệp tài liệu"]["where"]
    assert "KHÔNG còn chỉ ở máy bạn" in cloud_head, (
        f"câu tóm tắt không nói thẳng dữ liệu đã rời máy: {cloud_head!r}"
    )

    local_rows = {r["what"]: r for r in datamap.data_map()}
    assert local_rows["Tệp tài liệu"]["boundary"] == "device", (
        "bản đồ không đổi khi cấu hình kho đổi — nó đang viết cứng"
    )

    # Embedding luôn ở `device` ở CẢ HAI chế độ, và đó là sự thật: model chạy trong chính
    # tiến trình backend, không gọi dịch vụ nào.
    assert local_rows["Tạo vector (embedding)"]["boundary"] == "device"
    assert cloud_rows["Tạo vector (embedding)"]["boundary"] == "device"


def test_up5_ban_do_khong_nhac_tinh_nang_da_go(as_user):
    """Câu cũ nhắc "nhận dạng giọng nói" — thứ đã bị gỡ khỏi dự án từ lâu.

    Sai ngay cả trên bản chạy local. Một câu viết tay không tự đúng lên được khi tính
    năng biến mất.
    """
    from backend.security import datamap

    text = " ".join(
        f"{r['what']} {r['detail']} {r['where']}" for r in datamap.data_map()
    ).lower()
    text += " " + datamap.headline().lower()

    for da_go in ("nhận dạng giọng nói", "whisper", "ghi âm", "streamlit"):
        assert da_go not in text, (
            f"bản đồ dữ liệu nhắc tới `{da_go}` — tính năng này đã bị gỡ khỏi dự án"
        )


def test_up6_khong_con_chuoi_viet_cung_noi_doi_tren_cloud():
    """Không màn hình nào được viết cứng câu chỉ đúng với bản chạy trên máy.

    Quét nguồn JS chứ không quét kết quả render: một chuỗi viết cứng vẫn nằm im trong mã
    cho tới đúng lúc nó được hiện ra, và lúc đó thì đã muộn.
    """
    cam = {
        "rời khỏi máy này": "trên cloud, dữ liệu đã ở máy chủ khác từ trước",
        "đều chạy trên máy này": "trên cloud, cơ sở dữ liệu và vector ở Supabase",
        "có đúng ba đường dữ liệu ra ngoài": (
            "trên cloud còn kết nối PostgreSQL và kho lưu trữ — xem CLAUDE.md §Bảo mật"
        ),
    }
    vi_pham: list[str] = []
    for path in sorted((ROOT / "web" / "js").rglob("*.js")):
        for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            # Chỉ soi chuỗi hiển thị, bỏ qua chú thích — chú thích giải thích LỊCH SỬ
            # của mấy câu này thì được phép nhắc lại chúng.
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for cum, ly_do in cam.items():
                if cum in line:
                    vi_pham.append(f"{path.name}:{n} “{cum}” — {ly_do}")

    assert not vi_pham, (
        "Chuỗi hiển thị viết cứng, chỉ đúng với bản chạy trên máy:\n  " + "\n  ".join(vi_pham)
    )


def test_up7_nguoi_b_khong_xem_duoc_thong_bao_cua_ho_so_a(temp_data_dir):
    """Thông báo tải lên để lộ TÊN hồ sơ — phải qua kiểm quyền như mọi đường khác."""
    import time

    import jwt
    from fastapi.testclient import TestClient

    from backend.config import settings
    from backend.storage import reset_backend

    SECRET = "khoa-thu-nghiem-chi-dung-trong-test-32bytes"
    reset_backend()
    override = {
        "supabase_jwt_secret": SECRET, "supabase_jwt_jwks": "",
        "supabase_jwt_audience": "authenticated", "supabase_jwt_issuer": "",
        "allowed_user_emails": ("expert@example.test",),
    }
    saved = {k: getattr(settings, k) for k in override}
    for k, v in override.items():
        object.__setattr__(settings, k, v)

    def tok(sub: str) -> dict[str, str]:
        now = int(time.time())
        return {"Authorization": "Bearer " + jwt.encode(
            {"sub": sub, "email": "expert@example.test", "iat": now, "exp": now + 600,
             "aud": "authenticated"}, SECRET, algorithm="HS256")}

    try:
        from backend.main import app

        with TestClient(app) as client:
            a, b = str(uuid.uuid4()), str(uuid.uuid4())
            created = client.post("/workspaces", headers=tok(a),
                                  json={"name": "Cua A " + uuid.uuid4().hex[:6]})
            assert created.status_code == 201, created.text[:200]
            ws = created.json()["id"]

            r = client.post("/documents/upload-notice", headers=tok(b),
                            json={"workspace_id": ws, "filename": "x.docx", "size_bytes": 100})
            assert r.status_code in (403, 404), (
                f"B xem được thông báo tải lên của hồ sơ A (nhận {r.status_code}) — "
                "thông báo có chứa TÊN hồ sơ, tức là tên tổ chức khách hàng"
            )
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)
        reset_backend()
