"""C1a · C1b · C1c — ba invariant giữ cho `security/gateway.py` là CỬA DUY NHẤT ra ngoài.

Vào:  cây mã nguồn `backend/` (C1a, C1b quét AST) và gateway đang chạy (C1c).
Ra:   assert. Không gọi mạng, không đụng DB thật.

Vì sao cần cả ba (xem plan §A0):
  C1a  cấm module ngoài `providers/` giữ client mạng
  C1b  cấm module ngoài `gateway.py` chạm tới `providers/`
  C1c  cấm gọi `gateway.execute()` khi KHÔNG có thao tác nào đang mở

C1a + C1b là kiểm TĨNH — chúng chỉ chặn được việc *cầm* client mạng. Chỉ C1c chặn được
lỗi thật sự dễ mắc: quên bọc `gateway.operation(...)`. Thiếu C1c thì "phải mở thao tác
trước khi gọi" chỉ là quy ước, mà quy ước thì có ngày quên.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"

# Thư viện nói chuyện với thế giới bên ngoài. Giữ nguyên tên gốc lúc import.
NETWORK_LIBS = {"httpx", "requests", "urllib3", "aiohttp", "socket",
                "gtts", "edge_tts", "ddgs", "duckduckgo_search"}

PROVIDERS_PKG = "backend.security.providers"


def _modules() -> list[tuple[pathlib.Path, ast.Module]]:
    out = []
    for path in sorted(BACKEND.rglob("*.py")):
        out.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    return out


def _imported_roots(tree: ast.Module) -> set[str]:
    """Mọi tên module được import, cả `import x.y` lẫn `from x.y import z`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:      # import tương đối — không thể là thư viện ngoài
                continue
            if node.module:
                names.add(node.module)
                for alias in node.names:
                    names.add(f"{node.module}.{alias.name}")
    return names


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(BACKEND.parent).as_posix()


def test_c1a_only_providers_may_import_network_clients() -> None:
    """C1a — chỉ `backend/security/providers/**` được cầm client mạng."""
    offenders: list[str] = []
    for path, tree in _modules():
        if "security/providers" in path.as_posix():
            continue
        for name in _imported_roots(tree):
            root = name.split(".")[0]
            if root in NETWORK_LIBS or name.startswith("google.genai") or name == "google":
                offenders.append(f"{_rel(path)} → {name}")

    if offenders:
        pytest.fail(
            "Client mạng phải nằm trong backend/security/providers/ để egress có đúng một cửa.\n"
            "Vi phạm:\n  " + "\n  ".join(offenders)
            , pytrace=False,
        )


# Hai cửa, mỗi cửa một hạng mục. Danh sách này là TOÀN BỘ ngoại lệ của C1b — thêm mục
# vào đây là một thay đổi có chủ đích, nhìn thấy được trong diff, kèm lý do.
#
#   security/gateway.py       cửa ra BÊN THỨ BA (Gemini, DDGS, edge-tts, gTTS).
#                             Nhật ký `egress_log`. Hồ sơ mật phải xin phép trước.
#   storage/cloud.py          cửa vào KHO CỦA CHÍNH ỨNG DỤNG (Supabase Storage).
#                             Nhật ký `storage_events`. Cùng hạng với kết nối PostgreSQL.
#
# Vì sao không dùng chung một cửa: hai thứ cần hai câu trả lời khác nhau cho câu hỏi
# "dữ liệu này có rời khỏi tổ chức không?" — với Gemini là CÓ, với kho riêng là KHÔNG.
# Ép chung thì hoặc mỗi lần lưu tệp lại hỏi xin phép gửi ra ngoài (vô nghĩa, và làm
# chuyên gia quen tay bấm đồng ý), hoặc nhật ký gửi-ra-ngoài đầy dòng lưu trữ nội bộ
# khiến việc gửi cho Gemini chìm trong đó.
DOOR_MODULES: tuple[str, ...] = (
    "security/gateway.py",
    "storage/cloud.py",
)


def test_c1b_only_doors_may_import_providers() -> None:
    """C1b — chỉ `security/gateway.py` được chạm tới `providers/`.

    Thiếu invariant này thì C1a vẫn xanh trong khi ai đó gọi thẳng
    `providers.tts_edge.synthesize(...)` và đi vòng qua toàn bộ consent + nhật ký.
    """
    offenders: list[str] = []
    for path, tree in _modules():
        posix = path.as_posix()
        if any(posix.endswith(d) for d in DOOR_MODULES) or "security/providers" in posix:
            continue
        for name in _imported_roots(tree):
            if name.startswith(PROVIDERS_PKG) or name.endswith(".providers"):
                offenders.append(f"{_rel(path)} → {name}")

    if offenders:
        pytest.fail(
            "Chỉ những cửa đã khai báo được import backend.security.providers:\n  "
            + "\n  ".join(DOOR_MODULES)
            + "\nVi phạm:\n  " + "\n  ".join(offenders),
            pytrace=False,
        )


def test_c1c_execute_outside_operation_is_blocked() -> None:
    """C1c — RUNTIME: gọi `execute()` ngoài `operation()` phải bị chặn TRƯỚC khi chạm mạng.

    Đây là invariant duy nhất trong ba cái bắt được lỗi quên bọc thao tác.
    Provider giả dưới đây sẽ ném nếu nó bị gọi — nghĩa là cửa đã hở.
    """
    from backend.security import gateway

    called: list[str] = []

    def exploding_provider(**_kwargs: object) -> None:
        called.append("provider đã bị gọi")

    original = gateway._REGISTRY.get(("llm", "gemini"))
    gateway._REGISTRY[("llm", "gemini")] = exploding_provider
    try:
        request = gateway.EgressRequest(
            module="test.c1c",
            destination="llm",
            provider="gemini",
            payload_text="nội dung thử",
            summary="thử gọi ngoài thao tác",
            workspace_id=None,
        )
        with pytest.raises(gateway.NoActiveOperation):
            gateway.execute(request)
    finally:
        if original is None:
            gateway._REGISTRY.pop(("llm", "gemini"), None)
        else:
            gateway._REGISTRY[("llm", "gemini")] = original

    assert not called, "execute() đã gọi provider dù không có thao tác nào đang mở"


def test_c1e_cua_kho_khong_duoc_dang_ky_vao_gateway() -> None:
    """C1e — kho lưu trữ KHÔNG được nằm trong bảng đăng ký của gateway.

    Nếu nó lọt vào `_REGISTRY`, mỗi lần lưu một tệp sẽ trở thành một dòng "đã gửi dữ liệu
    ra ngoài" trong màn Bảo mật. Chuyên gia mở nhật ký lên sẽ thấy hàng chục dòng gửi ra
    ngoài cho những việc thật ra chỉ là lưu tệp vào kho của chính ứng dụng — và lần gửi
    thật cho Gemini chìm giữa chúng.

    Ngược lại cũng phải đúng: `storage_events` không được chứa lần gọi bên thứ ba nào.
    """
    from backend.security import gateway

    dang_ky = {p for _dest, p in gateway._REGISTRY}
    assert "supabase_storage" not in dang_ky, (
        "Kho lưu trữ bị đăng ký vào gateway. Nó là hạ tầng của chính ứng dụng, cùng hạng "
        "với kết nối PostgreSQL — không phải bên thứ ba."
    )
    assert dang_ky == {"gemini", "ddgs", "edge", "gtts"}, (
        f"Danh sách nhà cung cấp BÊN THỨ BA đã đổi: {sorted(dang_ky)}. "
        "Thêm một dịch vụ bên thứ ba là thay đổi lớn — sửa cả test này kèm lý do."
    )
