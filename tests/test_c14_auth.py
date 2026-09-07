"""C14 — xác thực và quyền sở hữu: chặn thật, không chỉ có mặt.

Vì sao phải có người dùng B giả
-------------------------------
Bản chạy thử chỉ có một chuyên gia. Nếu phân quyền "hoạt động" chỉ vì cơ sở dữ liệu
đang có đúng một người thì đó không phải nền tảng cho nhiều người dùng — nó là một sự
trùng hợp. Mọi test cách ly dưới đây dựng HAI danh tính thật và kiểm rằng B không chạm
được vào bất cứ thứ gì của A.

  AUTH1  không token                          -> 401
  AUTH2  token hỏng / hết hạn / alg=none      -> 401
  AUTH3  chuyên gia trong danh sách           -> vào được
  AUTH4  đăng nhập được nhưng ngoài danh sách -> 403
  AUTH5  B không đọc/sửa/xoá/hỏi RAG hồ sơ A
  C14a   mọi router đều được gắn workspace_guard
  C14b   danh sách đường công khai bị khoá
  C14c   không route nào tự định nghĩa lại hàm kiểm hồ sơ
"""

from __future__ import annotations

import ast
import pathlib
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "khoa-thu-nghiem-chi-dung-trong-test-32bytes"
EXPERT_EMAIL = "expert@example.test"
OUTSIDER_EMAIL = "nguoi-la@example.test"


def _token(sub, email, *, ttl=600, key=SECRET, alg="HS256"):
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "email": email, "iat": now, "exp": now + ttl, "aud": "authenticated"},
        key,
        algorithm=alg,
    )


@pytest.fixture()
def auth_app(temp_data_dir):
    """Ứng dụng THẬT với xác thực bật. Không mock middleware, không mock kiểm chữ ký.

    `Settings` là frozen dataclass — cố ý, để mã chạy không đổi cấu hình giữa chừng.
    Test là ngoại lệ hợp lệ duy nhất nên đi cửa sau có chủ đích, và trả lại nguyên trạng
    sau khi xong để không rò cấu hình sang test khác.
    """
    from backend.config import settings

    override = {
        "supabase_jwt_secret": SECRET,
        "supabase_jwt_jwks": "",
        "supabase_jwt_audience": "authenticated",
        "supabase_jwt_issuer": "",
        "allowed_user_emails": (EXPERT_EMAIL.lower(),),
    }
    saved = {k: getattr(settings, k) for k in override}
    for k, v in override.items():
        object.__setattr__(settings, k, v)

    from backend.main import app

    try:
        with TestClient(app) as client:
            yield client
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)


@pytest.fixture()
def expert():
    return {"id": str(uuid.uuid4()), "email": EXPERT_EMAIL}


@pytest.fixture()
def user_b():
    """Người dùng thứ hai — cũng trong danh sách, nhưng KHÁC người."""
    return {"id": str(uuid.uuid4()), "email": EXPERT_EMAIL}


def _h(user):
    return {"Authorization": "Bearer " + _token(user["id"], user["email"])}


# ============================== AUTH1-AUTH4 ==============================


def test_auth1_khong_token_bi_chan(auth_app):
    for path in ("/workspaces", "/security/egress-log", "/dashboard"):
        r = auth_app.get(path)
        assert r.status_code == 401, f"{path} cho qua khi KHONG co token (nhan {r.status_code})"


def test_auth2_token_hong_bi_chan(auth_app, expert):
    now = int(time.time())
    bad = {
        "chu ky sai": _token(expert["id"], expert["email"], key="khoa-khac-hoan-toan"),
        "het han": _token(expert["id"], expert["email"], ttl=-100),
        "alg none": jwt.encode({"sub": "x", "exp": now + 600}, None, algorithm="none"),
        "rac": "khong.phai.jwt",
        "thieu Bearer": _token(expert["id"], expert["email"]),
    }
    for name, token in bad.items():
        header = token if name == "thieu Bearer" else "Bearer " + token
        r = auth_app.get("/workspaces", headers={"Authorization": header})
        assert r.status_code == 401, f"token [{name}] lot qua (nhan {r.status_code})"


def test_auth3_chuyen_gia_trong_danh_sach_vao_duoc(auth_app, expert):
    r = auth_app.get("/workspaces", headers=_h(expert))
    assert r.status_code == 200, f"chuyen gia hop le bi chan: {r.status_code} {r.text[:200]}"


def test_auth4_ngoai_danh_sach_bi_tu_choi(auth_app):
    """Token hợp lệ hoàn toàn, chữ ký đúng — nhưng email ngoài danh sách thử nghiệm."""
    outsider = {"id": str(uuid.uuid4()), "email": OUTSIDER_EMAIL}
    r = auth_app.get("/workspaces", headers=_h(outsider))
    assert r.status_code == 403, (
        f"nguoi ngoai danh sach vao duoc (nhan {r.status_code}) — "
        "xac thuc duoc khong co nghia la duoc dung"
    )
    assert r.json().get("error") == "not_in_pilot"


# ============================== AUTH5: cách ly hai người ==============================


def test_auth5_b_khong_cham_duoc_ho_so_cua_a(auth_app, expert, user_b):
    """Người B không đọc, sửa, xoá, hay hỏi RAG được trên hồ sơ của A."""
    created = auth_app.post(
        "/workspaces",
        headers=_h(expert),
        json={"name": "Khach cua A " + uuid.uuid4().hex[:6], "is_confidential": True},
    )
    assert created.status_code == 201, created.text[:200]
    ws = created.json()["id"]

    mine = auth_app.get("/workspaces", headers=_h(expert)).json()
    assert any(w["id"] == ws for w in mine), "A khong thay ho so vua tao"

    theirs = auth_app.get("/workspaces", headers=_h(user_b)).json()
    assert not any(w["id"] == ws for w in theirs), (
        "B thay ho so cua A trong danh sach — rieng ten to chuc khach hang da la ro ri"
    )

    probes = [
        ("GET", "/workspaces/%d" % ws, None),
        ("PATCH", "/workspaces/%d" % ws, {"notes": "B sua trom"}),
        ("DELETE", "/workspaces/%d" % ws, None),
        ("GET", "/documents?workspace_id=%d" % ws, None),
        ("GET", "/glossary?workspace_id=%d" % ws, None),
        ("GET", "/security/egress-log?workspace_id=%d" % ws, None),
        ("GET", "/dashboard?workspace_id=%d" % ws, None),
        ("GET", "/simulate/context?workspace_id=%d" % ws, None),
        ("POST", "/documents/ask", {"workspace_id": ws, "question": "Tai tro bao nhieu?"}),
        ("POST", "/research/run", {"workspace_id": ws, "client_name": "X"}),
    ]
    lot_qua = []
    for method, path, body in probes:
        r = auth_app.request(method, path, headers=_h(user_b), json=body)
        # 404 la dung (khong xac nhan ho so ton tai). 401/403 cung chan. 422 la sai kieu
        # du lieu, tuc chua toi duoc lop phan quyen — van chua lot.
        if r.status_code not in (401, 403, 404, 422):
            lot_qua.append("%s %s -> %d" % (method, path, r.status_code))

    assert not lot_qua, "B cham duoc vao ho so cua A:\n  " + "\n  ".join(lot_qua)


def test_auth5b_khong_doi_duoc_chu_bang_than_request(auth_app, expert, user_b):
    """Gửi `owner_user_id` trong thân request không đổi được chủ sở hữu."""
    created = auth_app.post(
        "/workspaces",
        headers=_h(user_b),
        json={
            "name": "Cua B " + uuid.uuid4().hex[:6],
            "is_confidential": False,
            "owner_user_id": expert["id"],
        },
    )
    assert created.status_code == 201, created.text[:200]
    ws = created.json()["id"]

    from backend.db import get_conn

    with get_conn() as conn:
        row = conn.execute("SELECT owner_user_id FROM workspaces WHERE id = ?", (ws,)).fetchone()
    assert row["owner_user_id"] == user_b["id"], (
        "chu so huu lay theo than request thay vi theo `sub` trong JWT da xac minh"
    )


# ============================== C14a-C14c: invariant ==============================

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_c14a_moi_router_deu_duoc_gan_workspace_guard():
    """Router nào quên guard thì mọi endpoint của nó không có kiểm quyền sở hữu."""
    tree = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))

    thieu = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "include_router":
            continue
        deps = [k for k in node.keywords if k.arg == "dependencies"]
        if not deps or "workspace_guard" not in ast.unparse(deps[0]):
            thieu.append(ast.unparse(node.args[0]) if node.args else "?")

    assert not thieu, (
        "Router thieu `workspace_guard` — moi endpoint cua no cham ho so ma khong kiem "
        "chu so huu:\n  " + "\n  ".join(thieu)
    )


def test_c14b_danh_sach_duong_cong_khai_bi_khoa():
    """Nới danh sách công khai phải là thay đổi CÓ CHỦ ĐÍCH, thấy được trong diff."""
    from backend.auth.middleware import (
        PUBLIC_EXACT,
        PUBLIC_PREFIXES,
        PUBLIC_SUFFIXES,
        is_public,
    )

    assert PUBLIC_EXACT == frozenset(
        {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/favicon.ico"}
    ), "danh sach duong cong khai da doi — neu co y thi sua ca test nay kem ly do"
    # `/storage/upload/` và `/storage/download/` được thêm CÓ CHỦ ĐÍCH ở Phase 7.
    # Chúng là bản tương đương của URL ký sẵn Supabase phát ra: trình duyệt gửi tệp tới
    # đó mà không kèm JWT. Thứ cấp quyền là GIẤY PHÉP — token ngẫu nhiên 32 byte, dùng
    # một lần, hết hạn 15 phút, khoá đích khoá cứng trong giấy phép từ lúc phát. Cầm
    # token chỉ ghi được ĐÚNG MỘT tệp vào ĐÚNG MỘT chỗ đã định.
    assert PUBLIC_PREFIXES == (
        "/static/", "/js/", "/css/", "/storage/upload/", "/storage/download/",
    ), "danh sách tiền tố công khai đã đổi — nếu cố ý thì sửa cả test này kèm lý do"

    # Đường xin giấy phép và đường chốt thì KHÔNG được công khai: chúng tạo dòng dữ liệu
    # và đọc dữ liệu hồ sơ, nên phải qua xác thực đầy đủ.
    for path in ("/documents/upload-intent", "/documents/12/finalize", "/storage"):
        assert not is_public(path), f"{path} bị coi là công khai"
    assert PUBLIC_SUFFIXES == (".html",)

    for path in ("/workspaces", "/documents/ask", "/security/egress-log", "/simulate/context"):
        assert not is_public(path), f"{path} bi coi la cong khai"


def test_c14c_khong_route_nao_tu_dinh_nghia_lai_kiem_ho_so():
    """Ba bản `_require_workspace` sao chép nhau từng là chỗ dễ bỏ quên nhất.

    Giữ lại tên hàm thì được, nhưng thân nó phải gọi `ownership.require_workspace` chứ
    không được tự truy vấn bảng `workspaces` rồi tự quyết.
    """
    vi_pham = []
    for path in sorted((ROOT / "backend" / "routes").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "require_workspace" not in node.name:
                continue
            if "ownership.require_workspace" not in ast.unparse(node):
                vi_pham.append(f"{path.name}:{node.lineno} {node.name}")

    assert not vi_pham, (
        "Co ham kiem ho so tu viet, khong di qua chokepoint chung:\n  " + "\n  ".join(vi_pham)
    )


def test_auth6_chu_so_huu_dung_duoc_moi_endpoint_theo_ho_so(auth_app, expert):
    """Đường chạy HỢP LỆ của chính chủ phải chạy được, không 500.

    Vì sao cần test này bên cạnh AUTH5: AUTH5 kiểm người B BỊ CHẶN, nên nó dừng ở lớp
    phân quyền và không bao giờ chạm tới truy vấn thật. Một lỗi trong chính truy vấn đó
    sẽ bị lớp phân quyền che hoàn toàn.

    Đã xảy ra thật: `ORDER BY term_vi COLLATE NOCASE` hợp lệ trên SQLite nhưng
    PostgreSQL không có collation tên `nocase`. Lỗi chỉ lộ ra khi tạm gỡ guard — nghĩa
    là với chính chủ thì màn Thuật ngữ sẽ hỏng ngay lần mở đầu tiên trên cloud.
    """
    created = auth_app.post(
        "/workspaces",
        headers=_h(expert),
        json={"name": "Ho so cua chinh chu " + uuid.uuid4().hex[:6], "is_confidential": False},
    )
    assert created.status_code == 201, created.text[:200]
    ws = created.json()["id"]

    endpoints = [
        "/workspaces/%d" % ws,
        "/documents?workspace_id=%d" % ws,
        "/glossary?workspace_id=%d" % ws,
        "/glossary/stats?workspace_id=%d" % ws,
        "/glossary/export.csv?workspace_id=%d" % ws,
        "/security/egress-log?workspace_id=%d" % ws,
        "/security/egress-summary?workspace_id=%d" % ws,
        "/security/consent/%d" % ws,
        "/dashboard?workspace_id=%d" % ws,
        "/simulate/context?workspace_id=%d" % ws,
        "/simulate/sessions?workspace_id=%d" % ws,
        "/feedback/verdicts?workspace_id=%d" % ws,
        "/research/profile?workspace_id=%d" % ws,
        "/speech/storage?workspace_id=%d" % ws,
    ]

    hong = []
    for path in endpoints:
        r = auth_app.get(path, headers=_h(expert))
        if r.status_code >= 500:
            hong.append("%s -> %d  %s" % (path, r.status_code, r.text[:120]))

    assert not hong, (
        "Chính chủ mở endpoint của mình mà lỗi máy chủ:\n  " + "\n  ".join(hong)
    )
