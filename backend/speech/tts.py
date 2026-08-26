"""Đọc văn bản thành giọng nói (TTS): edge-tts chính, gTTS fallback.

Input:  văn bản + ngôn ngữ + tốc độ đọc (+ workspace_id để tra cách đọc tên riêng).
Output: đường dẫn tệp MP3 trong `data/tts_cache/<workspace_id>/`.

Bốn điểm thiết kế:

1. CACHE THEO NỘI DUNG, CHIA THEO HỒ SƠ. Khoá cache là hash của (văn bản đã xử lý + giọng
   + tốc độ), nằm trong thư mục con của hồ sơ. Nghe lại cùng một lượt thì lấy tệp cũ,
   không gọi mạng lại, không phải chờ (spec A4.7).

   Chia theo hồ sơ vì khoá toàn cục gây hai lỗi cùng lúc: xoá hồ sơ không dọn được audio
   của nó — trong khi `workspaces.py` hứa "xoá vĩnh viễn toàn bộ dữ liệu liên quan" — và
   một hồ sơ MẬT có thể nhận tệp đã sinh dưới hồ sơ thường mà không qua hộp thoại nào,
   vì lần lấy từ cache không đi qua gateway.

2. DÙNG CỘT `pronunciation` CỦA GLOSSARY. Giọng tiếng Việt đọc "Latter-Day Saint Charities"
   sẽ sai bét. Trước khi đọc, hệ thống thay tên riêng bằng gợi ý cách đọc mà chuyên gia đã
   ghi trong bảng thuật ngữ (quyết định Q6) — đây là lý do cột đó tồn tại.

3. HAI NHÀ CUNG CẤP = HAI LẦN EGRESS RIÊNG. edge-tts gửi văn bản tới **Microsoft**, gTTS
   gửi tới **Google**. Bọc chung một lần ghi nhật ký thì khi edge hỏng, dữ liệu đi sang
   Google mà nhật ký vẫn ghi tên giọng của Microsoft — nhật ký nói sai đích đến.
   Cả hai đều được khai trước trong `declares` của thao tác, nên chuyên gia biết ngay từ
   hộp thoại đầu tiên rằng có khả năng fallback, và không bị hỏi lại giữa chừng.

4. HỎNG THÌ VẪN CHẠY TIẾP. Hỏng cả hai thì ném lỗi để giao diện hiện lời thoại dạng chữ,
   buổi mock không bị chặn (spec edge case §4.2).
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.config import settings
from backend.db import get_conn
from backend.security import gateway

Language = Literal["vi", "en"]
Speed = Literal["slow", "normal", "fast"]

# edge-tts nhận tốc độ dạng phần trăm tương đối.
_EDGE_RATE = {"slow": "-20%", "normal": "+0%", "fast": "+20%"}
# gTTS chỉ có nhanh/chậm, không có mức trung gian.
_GTTS_SLOW = {"slow": True, "normal": False, "fast": False}

MAX_TTS_CHARS = 4000

# Khai báo dùng chung cho mọi thao tác đọc lời thoại: đúng một lần mỗi nhà cung cấp.
TTS_DECLARES = (
    gateway.OperationDeclaration("tts", gateway.PROVIDER_EDGE, unit_calls=1),
    gateway.OperationDeclaration("tts", gateway.PROVIDER_GTTS, unit_calls=1),
)


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


def _cache_dir(workspace_id: int | None) -> Path:
    """Thư mục cache của một hồ sơ. `None` → thư mục dùng chung cho việc không thuộc hồ sơ nào."""
    name = str(workspace_id) if workspace_id is not None else "_chung"
    return settings.tts_cache_dir / name


def _cache_path(text: str, voice: str, speed: str, workspace_id: int | None) -> Path:
    digest = hashlib.sha256(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()
    return _cache_dir(workspace_id) / f"{digest[:32]}.mp3"


def delete_workspace_cache(workspace_id: int) -> int:
    """Xoá toàn bộ audio đã sinh cho một hồ sơ. Trả về số tệp đã xoá."""
    folder = _cache_dir(workspace_id)
    if not folder.exists():
        return 0
    n = len(list(folder.glob("*.mp3")))
    shutil.rmtree(folder, ignore_errors=True)
    return n


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
        # Chặn hai đầu bằng ranh giới từ. Không có nó, một thuật ngữ ngắn như "ODA" sẽ bị
        # thay ngay bên trong một từ khác và câu đọc lên thành vô nghĩa.
        # `(?<!\w)` / `(?!\w)` thay vì `\b` vì thuật ngữ có thể bắt đầu hoặc kết thúc bằng
        # ký tự không phải chữ (ví dụ "Latter-Day", "(LDSC)").
        pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)", re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(mapping[surface], result)
            applied.append((surface, mapping[surface]))
    return result, applied


# ============================== Điểm vào ==============================


def synthesize(
    text: str,
    lang: Language,
    *,
    workspace_id: int | None = None,
    speed: Speed = "normal",
    voice: str | None = None,
) -> TtsResult:
    """Đọc văn bản thành tệp MP3, có cache. Ném `TtsError` nếu cả hai engine đều hỏng.

    PHẢI được gọi bên trong `gateway.operation(..., declares=TTS_DECLARES)`.
    """
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
    out_path = _cache_path(spoken, chosen_voice, speed, workspace_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Cache hit: KHÔNG có lệnh gọi mạng nào, nên không tính là dữ liệu rời khỏi máy.
    if out_path.exists() and out_path.stat().st_size > 512:
        return TtsResult(
            path=out_path, engine="cache", voice=chosen_voice, cached=True,
            text_spoken=spoken, substitutions=substitutions,
        )

    # Từ đây trở xuống là gọi mạng thật. Lời thoại chứa tên khách hàng và số liệu dự án,
    # nên mỗi nhà cung cấp là một lần đi qua gateway riêng, có dòng nhật ký riêng.
    errors: list[str] = []

    # --- edge-tts (Microsoft): giọng neural, tiếng Việt tự nhiên ---
    try:
        gateway.execute(
            gateway.EgressRequest(
                module="speech.tts",
                destination="tts",
                provider=gateway.PROVIDER_EDGE,
                payload_text=spoken,
                summary=f"Đọc lời thoại ({lang}, giọng {chosen_voice}): {spoken[:100]}",
                workspace_id=workspace_id,
                endpoint=f"edge-tts:{chosen_voice}",
            ),
            text=spoken, voice=chosen_voice, rate=_EDGE_RATE[speed], out_path=out_path,
        )
        return TtsResult(
            path=out_path, engine="edge-tts", voice=chosen_voice, cached=False,
            text_spoken=spoken, substitutions=substitutions,
        )
    except (gateway.ConsentRequired, gateway.PayloadTooLarge, gateway.NoActiveOperation):
        raise
    except Exception as exc:
        errors.append(f"edge-tts: {type(exc).__name__}")
        out_path.unlink(missing_ok=True)

    # --- gTTS (Google): nhẹ, ổn định, giọng máy móc hơn ---
    try:
        gateway.execute(
            gateway.EgressRequest(
                module="speech.tts",
                destination="tts",
                provider=gateway.PROVIDER_GTTS,
                payload_text=spoken,
                summary=f"Đọc lời thoại dự phòng ({lang}): {spoken[:100]}",
                workspace_id=workspace_id,
                endpoint=f"gtts:{lang}",
            ),
            text=spoken, lang=lang, slow=_GTTS_SLOW[speed], out_path=out_path,
        )
        return TtsResult(
            path=out_path, engine="gTTS", voice=f"gtts-{lang}", cached=False,
            text_spoken=spoken, substitutions=substitutions,
        )
    except (gateway.ConsentRequired, gateway.PayloadTooLarge, gateway.NoActiveOperation):
        raise
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
    path = _cache_path(spoken, chosen, speed, workspace_id)
    return not (path.exists() and path.stat().st_size > 512)


def voice_for(lang: Language, character: str = "A") -> str:
    """Giọng theo nhân vật. A nói tiếng Việt, B nói tiếng Anh nên đã phân biệt sẵn."""
    return settings.tts_voice_vi if lang == "vi" else settings.tts_voice_en


def cache_stats(workspace_id: int | None = None) -> dict[str, object]:
    """Dung lượng cache audio, cho trang quản lý dung lượng."""
    settings.ensure_dirs()
    if workspace_id is None:
        files = list(settings.tts_cache_dir.rglob("*.mp3"))
    else:
        files = list(_cache_dir(workspace_id).glob("*.mp3"))
    total = sum(f.stat().st_size for f in files)
    return {
        "n_files": len(files),
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 1),
    }


def clear_cache(workspace_id: int | None = None) -> int:
    """Xoá cache audio. Không nêu hồ sơ thì xoá tất cả. Trả về số tệp đã xoá."""
    settings.ensure_dirs()
    if workspace_id is not None:
        return delete_workspace_cache(workspace_id)
    files = list(settings.tts_cache_dir.rglob("*.mp3"))
    for path in files:
        path.unlink(missing_ok=True)
    return len(files)
