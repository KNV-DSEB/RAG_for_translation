"""C5 · C6x — vòng đời thao tác, ngân sách, và fallback nhiều nhà cung cấp.

Vào:  gateway + cơ sở dữ liệu tạm. Provider bị thay bằng hàm giả, KHÔNG gọi mạng.
Ra:   assert.

Đây là nhóm dựng lại đúng những ca đã làm hỏng bốn phiên bản plan liên tiếp:

  C6   fallback TTS bị kẹt vì vé `once` bị tiêu ngay cả khi lần gọi đầu hỏng
  C6b  lần thử lại đúc thao tác MỚI nên quyền vừa cấp thành vô dụng
  C6c  hỏi ý kiến theo thao tác, nhưng nhật ký vẫn phải ghi từng lệnh gọi
  C6d  "tối đa 8 truy vấn" chỉ là câu chữ, không ai thực thi
  C6e  mã thao tác dùng lại được sang hồ sơ / loại thao tác / lần khác
  C6f  câu chữ trên hộp thoại lệch khỏi chính sách thật
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

import pytest

from backend.security import gateway


@contextlib.contextmanager
def providers(*specs: tuple[str, str, Exception | None]) -> Iterator[list[tuple[str, str]]]:
    """Thay nhiều provider cùng lúc. Trả về nhật ký (destination, provider) đã bị gọi."""
    seen: list[tuple[str, str]] = []
    originals: dict[tuple[str, str], Any] = {}

    for destination, provider, boom in specs:
        key = (destination, provider)
        originals[key] = gateway._REGISTRY.get(key)

        def make(dest: str, prov: str, err: Exception | None):
            def stub(**_kwargs: Any) -> str:
                seen.append((dest, prov))
                if err is not None:
                    raise err
                return "ok"
            return stub

        gateway._REGISTRY[key] = make(destination, provider, boom)

    try:
        yield seen
    finally:
        for key, original in originals.items():
            if original is None:
                gateway._REGISTRY.pop(key, None)
            else:
                gateway._REGISTRY[key] = original


def req(workspace_id: int, destination: str, provider: str) -> gateway.EgressRequest:
    return gateway.EgressRequest(
        module="test", destination=destination, provider=provider,
        payload_text="lời thoại thử", summary="thử", workspace_id=workspace_id,
        endpoint=f"{provider}:thu",
    )


def consent_for(workspace_id: int, kind: str, declares, fingerprint: str, scope="operation") -> str:
    """Chạy thao tác một lần để lấy 409, cấp quyền, rồi trả về mã thao tác."""
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(workspace_id, kind=kind, declares=declares,
                               fingerprint=fingerprint):
            pass
    gateway.grant_from_pending(exc.value.preview.consent_request_id, scope)
    return exc.value.preview.operation_id


TTS_DECLARES = [
    gateway.OperationDeclaration("tts", "edge", unit_calls=1),
    gateway.OperationDeclaration("tts", "gtts", unit_calls=1),
]


# ============================== C5 + C6 ==============================


def test_c5_fallback_logs_the_provider_that_actually_ran(workspace: int) -> None:
    """C5 — edge-tts hỏng thì dữ liệu sang Google; nhật ký phải nói đúng như vậy.

    Bản cũ bọc CẢ HAI nhà cung cấp trong một lần ghi nhật ký, và chốt `endpoint` trước
    khi biết bên nào chạy. Kết quả: dữ liệu đi tới Google mà nhật ký ghi tên giọng của
    Microsoft — nhật ký nói sai đích đến, đúng thứ màn Bảo mật tồn tại để chống.
    """
    with providers(("tts", "edge", RuntimeError("edge hỏng")), ("tts", "gtts", None)):
        with gateway.operation(workspace, kind="tts.speak", declares=TTS_DECLARES,
                               fingerprint="fp-c5"):
            with pytest.raises(RuntimeError):
                gateway.execute(req(workspace, "tts", "edge"), text="x")
            gateway.execute(req(workspace, "tts", "gtts"), text="x")

    rows = gateway.recent_log(workspace_id=workspace, limit=2)
    assert [r["provider"] for r in rows] == ["gtts", "edge"]        # mới nhất trước
    assert rows[0]["status"] == "attempt_succeeded"
    assert rows[1]["status"] == "attempt_failed"
    assert rows[0]["operation_id"] == rows[1]["operation_id"]       # cùng một thao tác


def test_c6_tts_fallback_is_reachable_on_a_confidential_workspace(secret_workspace: int) -> None:
    """C6 — hồ sơ mật + edge hỏng chắc chắn → gTTS vẫn chạy được, KHÔNG hỏi lại lần hai.

    Đây là ngõ cụt của plan v1: vé cấp riêng cho edge bị tiêu ngay cả khi edge ném lỗi,
    nên gTTS luôn thiếu vé, và fallback không bao giờ với tới được.
    Cách thoát: khai TRƯỚC cả hai nhà cung cấp, xin phép MỘT lần cho cả thao tác.
    """
    op_id = consent_for(secret_workspace, "tts.speak", TTS_DECLARES, "fp-c6")

    with providers(("tts", "edge", RuntimeError("edge hỏng")), ("tts", "gtts", None)) as seen:
        with gateway.operation(secret_workspace, kind="tts.speak", declares=TTS_DECLARES,
                               fingerprint="fp-c6", resume_id=op_id):
            with pytest.raises(RuntimeError):
                gateway.execute(req(secret_workspace, "tts", "edge"), text="x")
            # KHÔNG được ném ConsentRequired ở đây — đó là lỗi mà v1 mắc phải
            gateway.execute(req(secret_workspace, "tts", "gtts"), text="x")

    assert seen == [("tts", "edge"), ("tts", "gtts")]


# ============================== C6b ==============================


def test_c6b_retry_with_header_resumes_the_same_operation(secret_workspace: int) -> None:
    """C6b — thử lại KÈM mã thao tác thì vào lại đúng thao tác cũ, không hỏi lại."""
    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=3)]
    op_id = consent_for(secret_workspace, "research.run", declares, "fp-c6b")

    with providers(("llm", "gemini", None)) as seen:
        with gateway.operation(secret_workspace, kind="research.run", declares=declares,
                               fingerprint="fp-c6b", resume_id=op_id) as op:
            assert op.resumed is True
            gateway.execute(req(secret_workspace, "llm", "gemini"), prompt="x")
    assert len(seen) == 1


def test_c6b_retry_without_header_must_ask_again(secret_workspace: int) -> None:
    """Ca âm — thiếu mã thao tác thì phải HỎI LẠI, không được im lặng cho qua.

    Hỏng theo hướng hỏi lại chuyên gia, không theo hướng cho lọt.
    """
    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=3)]
    consent_for(secret_workspace, "research.run", declares, "fp-c6b2")

    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(secret_workspace, kind="research.run", declares=declares,
                               fingerprint="fp-c6b2"):
            pass


# ============================== C6c ==============================


def test_c6c_one_dialog_many_log_lines(secret_workspace: int) -> None:
    """C6c — hỏi ý kiến theo THAO TÁC, nhưng nhật ký vẫn ghi TỪNG lệnh gọi.

    Đây là điểm cân bằng của cả thiết kế: độ mịn của việc hỏi ý kiến giảm xuống (bắt
    buộc, nếu không `/research/run` không chạy nổi), nhưng độ mịn của audit thì KHÔNG.
    """
    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=13)]
    op_id = consent_for(secret_workspace, "research.run", declares, "fp-c6c")

    before = len(gateway.recent_log(workspace_id=secret_workspace, limit=1000))
    with providers(("llm", "gemini", None)):
        with gateway.operation(secret_workspace, kind="research.run", declares=declares,
                               fingerprint="fp-c6c", resume_id=op_id):
            for _ in range(13):
                gateway.execute(req(secret_workspace, "llm", "gemini"), prompt="x")

    rows = gateway.recent_log(workspace_id=secret_workspace, limit=1000)
    added = [r for r in rows[: len(rows) - before] if r["status"] == "attempt_succeeded"]
    assert len(added) == 13
    assert {r["operation_id"] for r in added} == {op_id}    # một thao tác, mười ba dòng


# ============================== C6d ==============================


def test_c6d_budget_is_enforced_by_the_machine(workspace: int) -> None:
    """C6d — lệnh gọi vượt ngân sách bị chặn TRƯỚC khi chạm mạng.

    Không có phần này thì "tối đa 8 truy vấn" chỉ là câu chữ: vòng lặp chạy 80 lần vẫn
    hợp lệ trong khi hộp thoại ghi 8. Đúng loại lỗi mà cả đợt sửa này nhắm vào.
    """
    declares = [gateway.OperationDeclaration("search", "ddgs", unit_calls=3)]

    with providers(("search", "ddgs", None)) as seen:
        with gateway.operation(workspace, kind="research.run", declares=declares,
                               fingerprint="fp-c6d"):
            for _ in range(3):
                gateway.execute(req(workspace, "search", "ddgs"), query="x")
            with pytest.raises(gateway.OperationBudgetExceeded):
                gateway.execute(req(workspace, "search", "ddgs"), query="x")

    assert len(seen) == 3, "lệnh gọi thứ 4 vẫn chạm tới nhà cung cấp"
    newest = gateway.recent_log(workspace_id=workspace, limit=1)[0]
    assert newest["status"] == "blocked"


def test_c6d_undeclared_provider_is_refused(workspace: int) -> None:
    """Gọi nhà cung cấp mà thao tác không khai trước → chặn. Khai báo phải là đủ, không thiếu."""
    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=1)]
    with providers(("search", "ddgs", None)) as seen:
        with gateway.operation(workspace, kind="test.undeclared", declares=declares,
                               fingerprint="fp-undecl"):
            with pytest.raises(gateway.OperationBudgetExceeded):
                gateway.execute(req(workspace, "search", "ddgs"), query="x")
    assert seen == []


def test_c6d_retries_count_against_the_budget(workspace: int) -> None:
    """`retries_each` nâng trần đúng bằng tích, không nâng vô hạn."""
    d = gateway.OperationDeclaration("llm", "gemini", unit_calls=2, retries_each=2)
    assert d.max_calls == 6

    with providers(("llm", "gemini", None)) as seen:
        with gateway.operation(workspace, kind="test.retry", declares=[d],
                               fingerprint="fp-retry"):
            for _ in range(6):
                gateway.execute(req(workspace, "llm", "gemini"), prompt="x")
            with pytest.raises(gateway.OperationBudgetExceeded):
                gateway.execute(req(workspace, "llm", "gemini"), prompt="x")
    assert len(seen) == 6


# ============================== C6e ==============================


@pytest.mark.parametrize(
    "kind, fingerprint, reason",
    [
        ("tts.speak", "fp-c6e", "sai loại thao tác"),
        ("research.run", "fp-KHAC", "sai vân tay — là lần thao tác khác"),
    ],
)
def test_c6e_resume_id_must_match_kind_and_fingerprint(
    secret_workspace: int, kind: str, fingerprint: str, reason: str
) -> None:
    """C6e — mã thao tác chỉ dùng được cho ĐÚNG lần thao tác đã được đồng ý.

    Không có kiểm vân tay, quyền cấp cho "nghiên cứu khách hàng A" dùng lại được cho
    khách hàng B: cùng hồ sơ, cùng loại thao tác, mọi kiểm tra khác đều lọt.
    """
    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=1),
                gateway.OperationDeclaration("tts", "edge", unit_calls=1)]
    op_id = consent_for(secret_workspace, "research.run", declares, "fp-c6e")

    with pytest.raises(gateway.ConsentRequired), \
         gateway.operation(secret_workspace, kind=kind, declares=declares,
                           fingerprint=fingerprint, resume_id=op_id):
        pass


def test_c6e_resume_id_from_another_workspace_is_refused(secret_workspace: int) -> None:
    """Mã thao tác của hồ sơ này không mở được cho hồ sơ khác."""
    from tests.conftest import _new_workspace

    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=1)]
    op_id = consent_for(secret_workspace, "research.run", declares, "fp-c6e-ws")
    other = _new_workspace("Hồ sơ mật khác", 1)

    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(other, kind="research.run", declares=declares,
                               fingerprint="fp-c6e-ws", resume_id=op_id):
            pass


def test_c6e_completed_operation_cannot_be_reused(secret_workspace: int) -> None:
    """Thao tác đã chạy xong thì mã của nó chết theo — không chạy lại bằng quyền cũ."""
    declares = [gateway.OperationDeclaration("llm", "gemini", unit_calls=5)]
    op_id = consent_for(secret_workspace, "research.run", declares, "fp-c6e-done")

    with providers(("llm", "gemini", None)):
        with gateway.operation(secret_workspace, kind="research.run", declares=declares,
                               fingerprint="fp-c6e-done", resume_id=op_id):
            gateway.execute(req(secret_workspace, "llm", "gemini"), prompt="x")
    # Thoát khối `with` → thao tác được đánh dấu đã xong

    with pytest.raises(gateway.ConsentRequired):
        with gateway.operation(secret_workspace, kind="research.run", declares=declares,
                               fingerprint="fp-c6e-done", resume_id=op_id):
            pass


# ============================== C6f ==============================


def test_c6f_dialog_text_is_derived_from_the_policy(secret_workspace: int) -> None:
    """C6f — đổi ngân sách thì câu chữ đổi theo, vì cả hai chỉ có MỘT nguồn.

    Nếu câu chữ là chuỗi viết tay thì đến một lúc nào đó nó sẽ nói 8 trong khi luật cho 80.
    """
    def scope_note_for(unit_calls: int, fingerprint: str) -> str:
        with pytest.raises(gateway.ConsentRequired) as exc:
            with gateway.operation(
                secret_workspace, kind="research.run",
                declares=[gateway.OperationDeclaration("search", "ddgs", unit_calls=unit_calls)],
                fingerprint=fingerprint,
            ):
                pass
        return exc.value.preview.scope_note

    assert "8 lần tới DuckDuckGo" in scope_note_for(8, "fp-c6f-8")
    assert "3 lần tới DuckDuckGo" in scope_note_for(3, "fp-c6f-3")


def test_c6f_retry_ceiling_is_explained_not_hidden(secret_workspace: int) -> None:
    """Trần kỹ thuật lớn hơn số nội dung thì phải NÓI RÕ vì sao, không giấu đi.

    Giấu thì con số trên hộp thoại và con số được thực thi lệch nhau — mà đó chính là
    lỗi trung tâm của cả đợt sửa này.
    """
    with pytest.raises(gateway.ConsentRequired) as exc:
        with gateway.operation(
            secret_workspace, kind="documents.ask",
            declares=[gateway.OperationDeclaration(
                "llm", "gemini", unit_calls=1, retries_each=14)],
            fingerprint="fp-c6f-retry",
        ):
            pass

    note = exc.value.preview.scope_note
    assert "1 lần tới Gemini (Google)" in note
    assert "14 lần" in note        # số lần gửi lại
    assert "15 lượt" in note       # trần kỹ thuật thật sự được thực thi
