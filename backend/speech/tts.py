"""Đọc văn bản thành giọng nói (TTS): edge-tts chính, gTTS fallback.

Input:  văn bản + ngôn ngữ + tốc độ đọc (+ workspace_id để tra cách đọc tên riêng).
Output: đường dẫn tệp MP3 trong `data/tts_cache/`.

Ba điểm thiết kế:

1. CACHE THEO NỘI DUNG. Khoá cache là hash của (văn bản đã xử lý + giọng + tốc độ). Nghe lại
   cùng một lượt thì lấy tệp cũ, không gọi mạng lại, không phải chờ (spec A4.7).

2. DÙNG CỘT `pronunciation` CỦA GLOSSARY. Giọng tiếng Việt đọc "Latter-Day Saint Charities"
   sẽ sai bét. Trước khi đọc, hệ thống thay tên riêng bằng gợi ý cách đọc mà chuyên gia đã
   ghi trong bảng thuật ngữ (quyết định Q6) — đây là lý do cột đó tồn tại.

3. HỎNG THÌ VẪN CHẠY TIẾP. edge-tts dùng API không chính thức nên có thể hỏng; khi đó tự
   chuyển sang gTTS. Hỏng cả hai thì ném lỗi để giao diện hiện lời thoại dạng chữ, buổi mock
   không bị chặn (spec edge case §4.2).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.config import settings
from backend.db import get_conn
from backend.security import egress

Language = Literal["vi", "en"]
Speed = Literal["slow", "normal", "fast"]

# edge-tts nhận tốc độ dạng phần trăm tương đối.
_EDGE_RATE = {"slow": "-20%", "normal": "+0%", "fast": "+20%"}
# gTTS chỉ có nhanh/chậm, không có mức trung gian.
_GTTS_SLOW = {"slow": True, "normal": False, "fast": False}

MAX_TTS_CHARS = 4000


class TtsError(RuntimeError):
    """Không đọc được văn bản thành giọng nói."""


@dataclass
class TtsResult:
    path: Path
    engine: str
    voice: str
    cached: bool
    text_spoken: str
    substitutions: list[tuple[str, str]]


def _cache_key(text: str, voice: str, speed: str) -> str:
    digest = hashlib.sha256(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()
    return digest[:32]


def pronunciation_map(workspace_id: int) -> dict[str, str]:
    """Các cặp (từ cần đọc đúng → gợi ý cách đọc) từ bảng thuật ngữ của hồ sơ."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT term_vi, term_en, pronunciation FROM glossary
            WHERE workspace_id = ? AND status <> 'skipped'
              AND pronunciation IS NOT NULL AND TRIM(pronunciation) <> ''
            """,
            (workspace_id,),
        ).fetchall()

    mapping: dict[str, str] = {}
    for row in rows:
        hint = str(row["pronunciation"]).strip()
        # Ưu tiên thay dạng tiếng Anh vì đó mới là dạng giọng Việt đọc sai.
        for surface in (str(row["term_en"] or ""), str(row["term_vi"] or "")):
            surface = surface.strip()
            if len(surface) >= 2 and surface.lower() != hint.lower():
                mapping.setdefault(surface, hint)
    return mapping


def apply_pronunciation(
    text: str, workspace_id: int | None, lang: Language
) -> tuple[str, list[tuple[str, str]]]:
    """Thay tên riêng/viết tắt bằng gợi ý cách đọc.

    Chỉ áp cho giọng TIẾNG VIỆT: giọng tiếng Anh đọc tên tiếng Anh vốn đã đúng, thay vào
    lại làm sai.
    """
    if workspace_id is None or lang != "vi":
        return text, []

    mapping = pronunciation_map(workspace_id)
    if not mapping:
        return text, []

    applied: list[tuple[str, str]] = []
    result = text
    # Thay cụm dài trước để "Latter-Day Saint Charities" không bị "Charities" cắt trước.
    for surface in sorted(mapping, key=len, reverse=True):
        pattern = re.compile(re.escape(surface), re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(mapping[surface], result)
            applied.append((surface, mapping[surface]))
    return result, applied


# ============================== edge-tts (chính) ==============================


async def _edge_save(text: str, voice: str, rate: str, out_path: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out_path))


def _synthesize_edge(text: str, voice: str, speed: Speed, out_path: Path) -> None:
    try:
        asyncio.run(_edge_save(text, voice, _EDGE_RATE[speed], out_path))
    except RuntimeError:
        # Đã có event loop đang chạy (ví dụ gọi từ trong async context)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_edge_save(text, voice, _EDGE_RATE[speed], out_path))
        finally:
            loop.close()

    if not out_path.exists() or out_path.stat().st_size < 1024:
        raise TtsError("edge-tts trả về tệp rỗng.")


# ============================== gTTS (fallback) ==============================


def _synthesize_gtts(text: str, lang: Language, speed: Speed, out_path: Path) -> None:
    from gtts import gTTS

    engine = gTTS(text=text, lang=lang, slow=_GTTS_SLOW[speed])
    engine.save(str(out_path))
    if not out_path.exists() or out_path.stat().st_size < 512:
        raise TtsError("gTTS trả về tệp rỗng.")


# ============================== Điểm vào ==============================


def synthesize(
    text: str,
    lang: Language,
    *,
    workspace_id: int | None = None,
    speed: Speed = "normal",
    voice: str | None = None,
) -> TtsResult:
    """Đọc văn bản thành tệp MP3, có cache. Ném `TtsError` nếu cả hai engine đều hỏng."""
    clean = text.strip()
    if not clean:
        raise TtsError("Không có nội dung để đọc.")
    if len(clean) > MAX_TTS_CHARS:
        clean = clean[:MAX_TTS_CHARS]

    spoken, substitutions = apply_pronunciation(clean, workspace_id, lang)
    chosen_voice = voice or (
        settings.tts_voice_vi if lang == "vi" else settings.tts_voice_en
    )

    settings.ensure_dirs()
    key = _cache_key(spoken, chosen_voice, speed)
    out_path = settings.tts_cache_dir / f"{key}.mp3"

    # Cache hit: KHÔNG có lệnh gọi mạng nào, nên không tính là dữ liệu rời khỏi máy.
    if out_path.exists() and out_path.stat().st_size > 512:
        return TtsResult(
            path=out_path, engine="cache", voice=chosen_voice, cached=True,
            text_spoken=spoken, substitutions=substitutions,
        )

    # Từ đây trở xuống là gọi mạng thật: edge-tts gửi văn bản tới Microsoft, gTTS tới Google.
    # Lời thoại chứa tên khách hàng và số liệu dự án nên PHẢI đi qua cửa egress (E3),
    # để hồ sơ mật được hỏi ý kiến trước và mọi lần gửi đều vào nhật ký.
    request = egress.EgressRequest(
        module="speech.tts",
        destination="tts",
        payload_text=spoken,
        summary=f"Đọc lời thoại ({lang}, giọng {chosen_voice}): {spoken[:100]}",
        workspace_id=workspace_id,
        endpoint=f"tts:{chosen_voice}",
    )

    errors: list[str] = []

    with egress.egress(request):
        # --- edge-tts: giọng neural, tiếng Việt tự nhiên ---
        try:
            _synthesize_edge(spoken, chosen_voice, speed, out_path)
            return TtsResult(
                path=out_path, engine="edge-tts", voice=chosen_voice, cached=False,
                text_spoken=spoken, substitutions=substitutions,
            )
        except Exception as exc:
            errors.append(f"edge-tts: {type(exc).__name__}")
            out_path.unlink(missing_ok=True)

        # --- gTTS: nhẹ, ổn định, giọng máy móc hơn ---
        try:
            _synthesize_gtts(spoken, lang, speed, out_path)
            return TtsResult(
                path=out_path, engine="gTTS", voice=f"gtts-{lang}", cached=False,
                text_spoken=spoken, substitutions=substitutions,
            )
        except Exception as exc:
            errors.append(f"gTTS: {type(exc).__name__}")
            out_path.unlink(missing_ok=True)

    raise TtsError(
        "Không đọc được lời thoại bằng cả edge-tts và gTTS ("
        + "; ".join(errors)
        + "). Buổi mock vẫn tiếp tục được — lời thoại sẽ hiện dạng chữ."
    )


def would_egress(text: str, lang: Language, workspace_id: int | None = None,
                 speed: Speed = "normal", voice: str | None = None) -> bool:
    """Lần đọc này có phải gọi mạng không, hay lấy được từ cache.

    Giao diện dùng để biết trước có sắp phải xin đồng ý hay không.
    """
    spoken, _ = apply_pronunciation(text.strip(), workspace_id, lang)
    chosen = voice or (settings.tts_voice_vi if lang == "vi" else settings.tts_voice_en)
    path = settings.tts_cache_dir / f"{_cache_key(spoken, chosen, speed)}.mp3"
    return not (path.exists() and path.stat().st_size > 512)


def voice_for(lang: Language, character: str = "A") -> str:
    """Giọng theo nhân vật. A nói tiếng Việt, B nói tiếng Anh nên đã phân biệt sẵn."""
    return settings.tts_voice_vi if lang == "vi" else settings.tts_voice_en


def cache_stats() -> dict[str, object]:
    """Dung lượng cache audio, cho trang quản lý dung lượng."""
    settings.ensure_dirs()
    files = list(settings.tts_cache_dir.glob("*.mp3"))
    total = sum(f.stat().st_size for f in files)
    return {
        "n_files": len(files),
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 1),
    }


def clear_cache() -> int:
    """Xoá toàn bộ cache audio. Trả về số tệp đã xoá."""
    settings.ensure_dirs()
    files = list(settings.tts_cache_dir.glob("*.mp3"))
    for path in files:
        path.unlink(missing_ok=True)
    return len(files)
