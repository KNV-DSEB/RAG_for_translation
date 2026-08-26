"""Provider: gTTS (Google). Đích `tts`. Lớp dự phòng khi edge-tts hỏng.

Vào:  văn bản + mã ngôn ngữ + cờ đọc chậm.
Ra:   ghi tệp mp3 vào `out_path`. Ném `ProviderFailed` nếu tệp rỗng.
"""

from __future__ import annotations

from pathlib import Path

from backend.security.providers.tts_edge import ProviderFailed

PROVIDER = "gtts"

MIN_BYTES = 512


def synthesize(*, text: str, lang: str, slow: bool, out_path: Path) -> None:
    from gtts import gTTS

    engine = gTTS(text=text, lang=lang, slow=slow)
    engine.save(str(out_path))
    if not out_path.exists() or out_path.stat().st_size < MIN_BYTES:
        raise ProviderFailed("gTTS trả về tệp rỗng.")
