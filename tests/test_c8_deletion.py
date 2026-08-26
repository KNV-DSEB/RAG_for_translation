"""C8 — xoá hồ sơ phải xoá được THẬT, kể cả audio lời thoại.

Vào:  cơ sở dữ liệu + thư mục dữ liệu tạm (xem conftest).
Ra:   assert. Không gọi mạng.

`workspaces.py` nói với chuyên gia: "Đã xoá vĩnh viễn hồ sơ và toàn bộ dữ liệu liên
quan." Trước đây câu đó SAI: khoá cache audio là hash toàn cục `(giọng|tốc độ|văn bản)`
không mang hồ sơ, nên không có cách nào tìm ra tệp nào thuộc hồ sơ nào mà xoá.

Kèm theo là một lỗ hổng đồng ý: lần lấy từ cache trả về TRƯỚC cửa egress (đúng nguyên
tắc — không gọi mạng thì không phải egress), nhưng vì khoá toàn cục nên một hồ sơ MẬT
có thể nhận tệp đã sinh dưới hồ sơ thường mà không qua hộp thoại nào.
"""

from __future__ import annotations

from pathlib import Path

from backend.config import settings
from backend.rag import ingest
from backend.speech import tts


def _seed_audio(workspace_id: int, text: str = "lời thoại thử") -> Path:
    """Đặt sẵn một tệp cache như thể TTS vừa sinh ra nó."""
    path = tts._cache_path(text, "vi-VN-HoaiMyNeural", "normal", workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 4096)
    return path


def test_c8_cache_key_separates_workspaces(workspace: int, secret_workspace: int) -> None:
    """Cùng văn bản, cùng giọng, hai hồ sơ → HAI tệp khác nhau.

    Nếu chung một tệp thì hồ sơ mật dùng lại được audio của hồ sơ thường mà không phải
    xin phép ai — cache hit không đi qua gateway.
    """
    a = tts._cache_path("cùng một câu", "vi-VN-HoaiMyNeural", "normal", workspace)
    b = tts._cache_path("cùng một câu", "vi-VN-HoaiMyNeural", "normal", secret_workspace)
    assert a != b
    assert a.parent != b.parent


def test_c8_deleting_a_workspace_removes_its_audio(workspace: int, secret_workspace: int) -> None:
    """C8 — xoá hồ sơ dọn sạch audio CỦA NÓ, và chỉ của nó."""
    mine = _seed_audio(workspace)
    theirs = _seed_audio(secret_workspace)
    assert mine.exists() and theirs.exists()

    ingest.delete_workspace_data(workspace)

    assert not mine.exists(), "audio của hồ sơ vừa xoá vẫn còn trên đĩa"
    assert theirs.exists(), "đã xoá lây sang hồ sơ khác"


def test_c8_storage_stats_are_per_workspace(workspace: int, secret_workspace: int) -> None:
    """Màn Dung lượng phải báo số của hồ sơ đang xem, không phải của cả máy."""
    _seed_audio(workspace, "câu một")
    _seed_audio(workspace, "câu hai")
    _seed_audio(secret_workspace, "câu ba")

    assert tts.cache_stats(workspace)["n_files"] == 2
    assert tts.cache_stats(secret_workspace)["n_files"] == 1
    assert tts.cache_stats(None)["n_files"] >= 3      # None = toàn bộ


def test_c8_clear_cache_can_target_one_workspace(workspace: int, secret_workspace: int) -> None:
    """Dọn riêng một hồ sơ mật mà không đụng phần còn lại."""
    _seed_audio(workspace)
    kept = _seed_audio(secret_workspace)

    assert tts.clear_cache(workspace) == 1
    assert tts.cache_stats(workspace)["n_files"] == 0
    assert kept.exists()


def test_c8_deleting_a_workspace_with_no_audio_is_harmless(workspace: int) -> None:
    """Hồ sơ chưa từng phát lời thoại nào thì xoá vẫn phải chạy êm."""
    ingest.delete_workspace_data(workspace)      # không được ném
    assert tts.cache_stats(workspace)["n_files"] == 0


def test_c8_cache_lives_under_the_data_dir(workspace: int) -> None:
    """Tệp cache phải nằm trong thư mục dữ liệu của ứng dụng, không rơi ra ngoài.

    Có test này vì `.gitignore` chặn theo đường dẫn `/data/*`: một tệp audio sinh ra ngoài
    đó sẽ lọt vào commit, và đó là lời thoại chứa tên khách hàng.
    """
    path = _seed_audio(workspace)
    assert settings.data_dir in path.parents
