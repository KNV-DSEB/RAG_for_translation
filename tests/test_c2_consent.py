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


def test_c7c_session_grants_die_when_the_app_restarts(secret_workspace: int) -> None:
    """C7c — nút ghi "cho tới khi đóng ứng dụng" thì phải đúng nghĩa đen.

    Quyền nằm trong SQLite nên nó sống qua cả lần tắt máy. `init_db()` chạy lúc khởi
    động phải dọn sạch, nếu không cái nhãn đó là một lời hứa suông.
    """
    from backend.db import init_db

    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(secret_workspace, kind="test.session",
                               declares=declares(), fingerprint="fp-session"):
            pass
    grant(exc.value.preview, scope="session")
    assert gateway.consent_state(secret_workspace)["n_active"] >= 1

    init_db()   # giả lập lần khởi động sau

    remaining = gateway.consent_state(secret_workspace)["grants"]
    assert not [g for g in remaining if g["scope"] == "session"]


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
