"""C2 · C3 · C4 · C7x — quyền, xem trước, và nhật ký.

Vào:  gateway + một cơ sở dữ liệu tạm (xem conftest).
Ra:   assert. KHÔNG có lệnh gọi mạng nào — provider bị thay bằng hàm giả.

Nhóm này khoá lại đúng những lời hứa mà giao diện nói với chuyên gia:
  • xem trước là TOÀN BỘ nội dung, không phải trích đoạn        (C4)
  • đồng ý cho đích này KHÔNG mở luôn đích khác                 (C2)
  • bị chặn thì có dấu vết trong nhật ký                        (C3)
  • quyền của thao tác A không dùng được cho thao tác B         (C7)
  • máy chủ không tin giao diện khai đích/nhà cung cấp          (C7b)
  • "cho tới khi đóng ứng dụng" đúng nghĩa đen                  (C7c)
  • lần gửi hỏng vẫn tính là ĐÃ CỐ gửi                          (C7d)
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

import pytest

from backend.db import get_conn
from backend.security import gateway


@contextlib.contextmanager
def fake_provider(
    destination: str = "llm", provider: str = "gemini", raises: Exception | None = None
) -> Iterator[list[dict[str, Any]]]:
    """Thay nhà cung cấp thật bằng hàm giả. Trả về danh sách các lần nó bị gọi."""
    calls: list[dict[str, Any]] = []

    def stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        if raises is not None:
            raise raises
        return "ok"

    key = (destination, provider)
    original = gateway._REGISTRY.get(key)
    gateway._REGISTRY[key] = stub
    try:
        yield calls
    finally:
        if original is None:
            gateway._REGISTRY.pop(key, None)
        else:
            gateway._REGISTRY[key] = original


def declares(unit_calls: int = 3, provider: str = "gemini", destination: str = "llm"):
    return [gateway.OperationDeclaration(destination, provider, unit_calls=unit_calls)]


def request_for(workspace_id: int, provider: str = "gemini", destination: str = "llm",
                payload: str = "nội dung thử") -> gateway.EgressRequest:
    return gateway.EgressRequest(
        module="test", destination=destination, provider=provider,
        payload_text=payload, summary="thử", workspace_id=workspace_id,
    )


def log_rows(workspace_id: int) -> list[dict[str, Any]]:
    return gateway.recent_log(workspace_id=workspace_id, limit=100)


def grant(preview: gateway.OperationPreview, scope: str = "operation") -> None:
    gateway.grant_from_pending(preview.consent_request_id, scope)


# ============================== C4 ==============================


def test_c4_preview_shows_whole_payload_not_an_excerpt(secret_workspace: int) -> None:
    """C4 — hộp thoại nói "toàn bộ nội dung", nên nó phải LÀ toàn bộ nội dung.

    Bản cũ cắt `payload_text[:4000]` rồi vẫn hiện câu "đây là chính xác nội dung sẽ rời
    khỏi máy này". Trường trong code còn tên là `payload_excerpt` — tức là code BIẾT nó
    chỉ là trích đoạn, chỉ có người dùng là không biết.
    """
    long_payload = "Xã Thu Cúc " * 900        # ~9.900 ký tự, vượt xa mốc 4.000 cũ
    assert len(long_payload) > 4000

    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(
            secret_workspace, kind="test.long", declares=declares(),
            fingerprint="fp-long", payload_preview=long_payload,
        ):
            pass

    preview = exc.value.preview
    assert preview.payload_excerpt == long_payload
    assert preview.n_chars == len(long_payload)
    assert preview.payload_truncated is False
    assert preview.payload_known is True


def test_c4_multi_call_operation_admits_it_cannot_show_payload(secret_workspace: int) -> None:
    """Thao tác nhiều lệnh gọi phải NÓI RÕ là chưa biết trước nội dung, không hiện khối rỗng."""
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(
            secret_workspace, kind="research.run",
            declares=[gateway.OperationDeclaration("search", "ddgs", unit_calls=8),
                      gateway.OperationDeclaration("llm", "gemini", unit_calls=5)],
            fingerprint="fp-research",
        ):
            pass

    preview = exc.value.preview
    assert preview.payload_known is False
    assert "chưa hiện được ở đây" in preview.scope_note
    # Câu chữ phải SINH RA từ khai báo, không viết tay
    assert "8 lần tới DuckDuckGo" in preview.scope_note
    assert "5 lần tới Gemini (Google)" in preview.scope_note


# ============================== C2 ==============================


def test_c2_consent_for_one_destination_does_not_open_another(secret_workspace: int) -> None:
    """C2 — đồng ý gửi cho LLM KHÔNG được mở luôn tìm kiếm và đọc lời thoại.

    Bản cũ cấp vé với `destination = NULL`, và SQL coi NULL là khớp mọi đích trong 8 giờ.
    Bấm đồng ý một lần cho LLM là mở luôn cả ba đường ra.
    """
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="a.llm",
                               declares=declares(provider="gemini"), fingerprint="fp-a"):
            pass
    grant(exc.value.preview, scope="session")   # phạm vi rộng nhất có thể cấp

    # Cùng hồ sơ, cùng phiên, nhưng ĐÍCH KHÁC → vẫn phải hỏi
    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(secret_workspace, kind="b.tts",
                               declares=declares(provider="edge", destination="tts"),
                               fingerprint="fp-b"):
            pass


def test_c2_consent_for_one_provider_does_not_open_its_sibling(secret_workspace: int) -> None:
    """Cùng đích `tts` nhưng edge-tts là Microsoft còn gTTS là Google — hai nơi khác nhau."""
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="tts.edge",
                               declares=declares(provider="edge", destination="tts"),
                               fingerprint="fp-edge"):
            pass
    grant(exc.value.preview, scope="session")

    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(secret_workspace, kind="tts.gtts",
                               declares=declares(provider="gtts", destination="tts"),
                               fingerprint="fp-gtts"):
            pass


# ============================== C3 ==============================


def test_c3_blocked_call_leaves_a_trace(secret_workspace: int) -> None:
    """C3 — bị chặn cũng phải vào nhật ký, kèm mã thao tác để đối chiếu được.

    Không ghi thì màn Bảo mật chỉ kể được chuyện đã xảy ra, không kể được chuyện hệ thống
    đã NGĂN — mà cái sau mới là thứ chứng minh cờ hồ sơ mật có tác dụng.
    """
    before = len(log_rows(secret_workspace))

    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="test.blocked",
                               declares=declares(), fingerprint="fp-blocked"):
            pass

    rows = log_rows(secret_workspace)
    assert len(rows) == before + 1
    newest = rows[0]
    assert newest["status"] == "blocked"
    assert newest["operation_id"] == exc.value.preview.operation_id
    assert int(newest["n_chars"]) == 0        # chưa gửi gì thật


# ============================== C7 ==============================


def test_c7_grant_for_one_operation_does_not_cover_another(secret_workspace: int) -> None:
    """C7 — quyền cấp cho lần thao tác A không dùng được cho lần B."""
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="research.run",
                               declares=declares(), fingerprint="fp-khach-A"):
            pass
    grant(exc.value.preview, scope="operation")

    # Cùng loại thao tác, cùng hồ sơ — chỉ khác vân tay (khách hàng khác)
    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(secret_workspace, kind="research.run",
                               declares=declares(), fingerprint="fp-khach-B"):
            pass


def test_c7b_server_reads_scope_from_its_own_record(secret_workspace: int) -> None:
    """C7b — giao diện chỉ đưa mã yêu cầu; đích và nhà cung cấp do máy chủ tự đọc.

    Mã lạ, hết hạn, hoặc đã dùng đều phải bị từ chối — nếu không, một mã cũ có thể được
    dùng lại để mở quyền mà chuyên gia không hề thấy hộp thoại nào.
    """
    with pytest.raises(gateway.EgressError):
        gateway.grant_from_pending("khong-ton-tai", "operation")

    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="test.once",
                               declares=declares(), fingerprint="fp-once"):
            pass
    request_id = exc.value.preview.consent_request_id

    gateway.grant_from_pending(request_id, "operation")     # lần đầu: được
    with pytest.raises(gateway.EgressError):
        gateway.grant_from_pending(request_id, "operation")  # dùng lại: không


def test_c7b_rejects_unknown_scope(secret_workspace: int) -> None:
    with pytest.raises(gateway.EgressError):
        gateway.grant_from_pending("bat-ky", "forever")


def test_c7c_pham_vi_phien_dung_nghia_o_TUNG_che_do(secret_workspace: int) -> None:
    """C7c — nút phạm vi rộng phải nói đúng thứ hệ thống thật sự làm, ở CẢ HAI chế độ.

    NGỮ NGHĨA ĐÃ ĐỔI KHI LÊN CLOUD, và test này đổi theo — có lý do, không phải để cho
    xanh:

    Trên MÁY CÁ NHÂN, "phiên" là lần chạy ứng dụng. Quyền nằm trong SQLite nên sống qua
    cả lần tắt máy, vì vậy `init_db()` phải dọn lúc khởi động — nếu không thì nhãn "cho
    tới khi đóng ứng dụng" là lời hứa suông. Phần này giữ nguyên như cũ.

    Trên CLOUD thì làm vậy là SAI. Backend khởi động lại vì deploy, vì scale, vì crash —
    toàn những việc chẳng liên quan gì tới chuyên gia. Xoá quyền theo vòng đời tiến trình
    nghĩa là một lần deploy lúc nửa đêm âm thầm thu hồi quyền, và hai bản backend chạy
    song song thì mỗi bản thấy một tập quyền khác nhau. Ở đó "phiên" là PHIÊN TRÌNH
    DUYỆT: quyền gắn `client_session_id` và tự hết hạn theo `expires_at`.

    Nên điều bất biến KHÔNG phải "quyền chết khi khởi động lại". Nó là: **nhãn trên nút
    phải mô tả đúng thứ backend thực thi.** Test kiểm đúng điều đó ở từng chế độ.
    """
    from backend.database import driver
    from backend.db import init_db

    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="test.session",
                               declares=declares(), fingerprint="fp-session"):
            pass
    grant(exc.value.preview, scope="session")
    assert gateway.consent_state(secret_workspace)["n_active"] >= 1

    label = gateway.session_scope_label()
    init_db()   # giả lập lần khởi động lại của máy chủ
    remaining = [
        g for g in gateway.consent_state(secret_workspace)["grants"] if g["scope"] == "session"
    ]

    if driver.is_postgres():
        assert remaining, (
            "Trên cloud, khởi động lại backend KHÔNG được thu hồi quyền: deploy và scale "
            "là việc của hạ tầng, không phải quyết định của chuyên gia."
        )
        assert "tab" in label.lower() and "giờ" in label.lower(), (
            f"nhãn “{label}” không nói đúng ngữ nghĩa cloud (phiên trình duyệt + thời hạn)"
        )
    else:
        assert not remaining, (
            "Trên máy cá nhân, nhãn “cho tới khi đóng ứng dụng” phải đúng nghĩa đen."
        )
        assert label == "Cho tới khi đóng ứng dụng"


def test_c7c2_quyen_phien_khong_dung_chung_giua_hai_phien_trinh_duyet(
    secret_workspace: int,
) -> None:
    """Quyền cấp trong phiên trình duyệt A không được dùng ở phiên B.

    Không có ràng buộc này thì một tab khác — hoặc một thiết bị khác của cùng người —
    dùng lại được quyền mà chủ nhân tưởng đã đóng lại khi tắt tab.
    """
    from backend.auth.context import set_request_identity
    from backend.auth.verify import AuthUser
    from backend.database import driver

    if not driver.is_postgres():
        pytest.skip("phạm vi theo phiên trình duyệt chỉ áp dụng khi chạy trên cloud")

    user = AuthUser(user_id="user-mot", email="a@b.test")

    set_request_identity(user, "phien-A")
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="test.sess2",
                               declares=declares(), fingerprint="fp-s2"):
            pass
    grant(exc.value.preview, scope="session")
    assert gateway.consent_state(secret_workspace)["n_active"] >= 1, "phiên A phải có quyền"

    set_request_identity(user, "phien-B")
    assert gateway.consent_state(secret_workspace)["n_active"] == 0, (
        "phiên B thấy quyền của phiên A"
    )

    set_request_identity(AuthUser(user_id="user-hai", email="c@d.test"), "phien-A")
    assert gateway.consent_state(secret_workspace)["n_active"] == 0, (
        "người khác dùng lại được quyền chỉ vì trùng mã phiên"
    )

    set_request_identity(None, None)


# ============================== C7d ==============================


def test_c7d_failed_attempt_still_counts_as_data_having_left(workspace: int) -> None:
    """C7d — nhà cung cấp ném lỗi KHÔNG có nghĩa là dữ liệu chưa rời máy.

    Thân request có thể đã gửi xong rồi mới timeout lúc đọc. Gọi nó là "chưa gửi" cũng
    sai như gọi nó là "gửi thành công". Ta chỉ biết chắc một điều: ĐÃ CỐ gửi.
    """
    with fake_provider(raises=TimeoutError("giả lập mất mạng")):
        with gateway.operation(workspace, kind="test.fail",
                               declares=declares(), fingerprint="fp-fail"):
            with pytest.raises(TimeoutError):
                gateway.execute(request_for(workspace), prompt="x")

    newest = log_rows(workspace)[0]
    assert newest["status"] == "attempt_failed"
    assert newest["error_class"] == "TimeoutError"
    assert str(newest["status"]).startswith("attempt")   # → được đếm vào "đã cố gửi"


def test_c7d_blocked_is_not_counted_as_an_attempt(secret_workspace: int) -> None:
    """Ngược lại: bị chặn thì CHƯA chạm mạng, không được đếm vào 'đã cố gửi'."""
    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(secret_workspace, kind="test.blocked2",
                               declares=declares(), fingerprint="fp-blocked2"):
            pass

    newest = log_rows(secret_workspace)[0]
    assert newest["status"] == "blocked"
    assert not str(newest["status"]).startswith("attempt")
