"""Provider: edge-tts (Microsoft). Đích `tts`.

Vào:  văn bản + tên giọng + tốc độ đọc dạng chuỗi rate của edge-tts ("-20%"…).
Ra:   ghi tệp mp3 vào `out_path`. Ném `ProviderFailed` nếu tệp rỗng.

Đây là nhà cung cấp KHÁC với gTTS, nên nó phải là một lần egress riêng có nhật ký riêng.
Bọc chung hai bên trong một lần ghi nhật ký thì khi edge hỏng, dữ liệu đi sang Google
mà nhật ký vẫn ghi tên giọng của Microsoft.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

PROVIDER = "edge"

MIN_BYTES = 1024


class ProviderFailed(RuntimeError):
    """Nhà cung cấp trả về thứ không dùng được. Điều phối bên trên quyết định fallback."""


async def _save(text: str, voice: str, rate: str, out_path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out_path))


def synthesize(*, text: str, voice: str, rate: str, out_path: Path) -> None:
    try:
        asyncio.run(_save(text, voice, rate, out_path))
    except RuntimeError:
        # Đã có event loop đang chạy (ví dụ gọi từ trong async context)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_save(text, voice, rate, out_path))
        finally:
            loop.close()

    if not out_path.exists() or out_path.stat().st_size < MIN_BYTES:
        raise ProviderFailed("edge-tts trả về tệp rỗng.")
