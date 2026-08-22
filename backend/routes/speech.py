"""Routes Module 4: đọc lời thoại thành giọng nói, kiểm tra loa, quản lý dung lượng.

Input:  văn bản cần đọc.
Output: tệp MP3 phát được.

ĐÃ BỎ phần nhận dạng giọng nói (STT). Lý do: mô hình chạy trên máy chủ nên mỗi lượt
phải chờ 15–30 giây, qua đường tunnel còn lâu hơn; và nó hay viết sai số liệu — đúng
thứ phiên dịch không được sai. Chuyên gia gõ bản dịch thay vì nói.
Phần NGHE lời thoại vẫn giữ, vì đó mới là cái tạo áp lực giống buổi thật.

Bản ghi âm giọng chuyên gia lưu LÂU DÀI theo mặc định (quyết định Q11) nhưng có cơ chế xoá
chủ động ba mức: một lượt · một buổi · toàn bộ hồ sơ. Xoá bản ghi KHÔNG làm mất điểm đã chấm.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db import get_conn
from backend.speech import tts

router = APIRouter(prefix="/speech", tags=["speech"])


class TtsRequest(BaseModel):
    text: str = Field(min_length=1)
    lang: Literal["vi", "en"]
    workspace_id: int | None = None
    speed: Literal["slow", "normal", "fast"] = "normal"


# ============================== TTS ==============================


@router.post("/tts")
def synthesize(payload: TtsRequest) -> dict[str, Any]:
    """Đọc văn bản thành giọng nói. Trả về khoá tệp để phát qua /speech/audio/{key}."""
    try:
        result = tts.synthesize(
            payload.text,
            payload.lang,
            workspace_id=payload.workspace_id,
            speed=payload.speed,
        )
    except tts.TtsError as exc:
        # 503 để giao diện biết mà chuyển sang hiện lời thoại dạng chữ
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "key": result.path.stem,
        "engine": result.engine,
        "voice": result.voice,
        "cached": result.cached,
        "size_bytes": result.path.stat().st_size,
        "substitutions": [
            {"surface": s, "spoken_as": p} for s, p in result.substitutions
        ],
    }


@router.get("/audio/{key}")
def get_audio(key: str) -> FileResponse:
    """Phát tệp audio đã sinh. Khoá là tên tệp trong cache, không phải đường dẫn tuỳ ý."""
    if not key.isalnum():
        raise HTTPException(status_code=400, detail="Khoá audio không hợp lệ.")
    path = settings.tts_cache_dir / f"{key}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp audio này.")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{key}.mp3")


@router.post("/turn-audio/{turn_id}")
def turn_audio(turn_id: int, speed: str = Query(default="normal")) -> dict[str, Any]:
    """Sinh (hoặc lấy từ cache) audio cho một lượt thoại, dùng giọng theo nhân vật."""
    with get_conn() as conn:
        turn = conn.execute(
            """
            SELECT t.*, s.workspace_id FROM mock_turns t
            JOIN mock_sessions s ON s.id = t.session_id
            WHERE t.id = ?
            """,
            (turn_id,),
        ).fetchone()
    if turn is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt thoại này.")

    if speed not in ("slow", "normal", "fast"):
        speed = "normal"

    try:
        result = tts.synthesize(
            str(turn["source_text"]),
            str(turn["source_lang"]),  # type: ignore[arg-type]
            workspace_id=int(turn["workspace_id"]),
            speed=speed,  # type: ignore[arg-type]
        )
    except tts.TtsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Ghi lại đường dẫn để lần sau khỏi phải sinh lại (spec A4.7)
    with get_conn() as conn:
        conn.execute(
            "UPDATE mock_turns SET tts_path = ? WHERE id = ?", (str(result.path), turn_id)
        )

    return {
        "key": result.path.stem,
        "engine": result.engine,
        "voice": result.voice,
        "cached": result.cached,
        "speaker_name": turn["speaker_name"],
        "source_lang": turn["source_lang"],
        "substitutions": [
            {"surface": s, "spoken_as": p} for s, p in result.substitutions
        ],
    }


# ============================== Kiểm tra thiết bị ==============================


@router.post("/device-check")
def device_check(workspace_id: int | None = None) -> dict[str, Any]:
    """Kiểm tra loa: sinh một câu mẫu để chuyên gia bấm nghe (spec A4.10).

    Phần micro phải kiểm ở phía giao diện vì backend không truy cập được thiết bị.
    """
    sample = "Đây là câu kiểm tra loa. Nếu bạn nghe rõ câu này thì phần âm thanh đã sẵn sàng."
    try:
        result = tts.synthesize(sample, "vi", workspace_id=workspace_id)
    except tts.TtsError as exc:
        return {
            "speaker_ok": False,
            "detail": str(exc),
            "hint": "Không sinh được audio. Buổi mock vẫn chạy được với lời thoại dạng chữ.",
        }
    return {
        "speaker_ok": True,
        "key": result.path.stem,
        "engine": result.engine,
        "sample_text": sample,
        "hint": "Bấm phát. Nghe rõ thì loa đã sẵn sàng; sau đó thử ghi âm để kiểm micro.",
    }


# ============================== Quản lý bản ghi (Q11) ==============================


def _dir_size(paths: list[Path]) -> int:
    return sum(p.stat().st_size for p in paths if p.exists())


@router.get("/storage")
def storage(workspace_id: int | None = Query(default=None)) -> dict[str, Any]:
    """Dung lượng đang dùng, chia theo hồ sơ và theo buổi (spec A4.13)."""
    settings.ensure_dirs()

    sql = """
        SELECT a.id, a.recording_path, a.session_id, s.workspace_id, w.name AS workspace_name
        FROM turn_attempts a
        JOIN mock_sessions s ON s.id = a.session_id
        JOIN workspaces w ON w.id = s.workspace_id
        WHERE a.recording_path IS NOT NULL
    """
    params: tuple[Any, ...] = ()
    if workspace_id is not None:
        sql += " AND s.workspace_id = ?"
        params = (workspace_id,)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    by_workspace: dict[str, dict[str, Any]] = {}
    by_session: dict[int, dict[str, Any]] = {}
    total_bytes = 0
    missing = 0

    for row in rows:
        path = Path(str(row["recording_path"]))
        if not path.exists():
            missing += 1
            continue
        size = path.stat().st_size
        total_bytes += size

        name = str(row["workspace_name"])
        entry = by_workspace.setdefault(
            name, {"workspace_id": int(row["workspace_id"]), "n_files": 0, "bytes": 0}
        )
        entry["n_files"] += 1
        entry["bytes"] += size

        sid = int(row["session_id"])
        sentry = by_session.setdefault(sid, {"session_id": sid, "n_files": 0, "bytes": 0})
        sentry["n_files"] += 1
        sentry["bytes"] += size

    cache = tts.cache_stats()

    return {
        "recordings": {
            "n_files": len(rows) - missing,
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 1),
            "missing_files": missing,
            "by_workspace": [{"workspace_name": k, **v} for k, v in by_workspace.items()],
            "by_session": sorted(
                by_session.values(), key=lambda x: int(x["bytes"]), reverse=True
            ),
        },
        "tts_cache": cache,
    }


def _delete_recordings(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Xoá tệp trên đĩa và xoá đường dẫn trong DB. Trả về (số tệp, số byte)."""
    deleted = 0
    freed = 0
    with get_conn() as conn:
        for row in rows:
            path = Path(str(row["recording_path"]))
            if path.exists():
                freed += path.stat().st_size
                path.unlink(missing_ok=True)
                deleted += 1
            # Chỉ xoá đường dẫn — điểm đã chấm và bản chữ vẫn giữ nguyên (spec A4.12)
            conn.execute(
                "UPDATE turn_attempts SET recording_path = NULL WHERE id = ?",
                (int(row["id"]),),
            )
    return deleted, freed


@router.get("/recordings/delete-preview")
def delete_preview(
    scope: Literal["attempt", "session", "workspace"] = Query(...),
    target_id: int = Query(...),
) -> dict[str, Any]:
    """Nói rõ sẽ mất bao nhiêu tệp và dung lượng trước khi xoá."""
    rows = _recordings_for(scope, target_id)
    total = sum(
        Path(str(r["recording_path"])).stat().st_size
        for r in rows
        if Path(str(r["recording_path"])).exists()
    )
    label = {"attempt": "lượt này", "session": "buổi mock này", "workspace": "hồ sơ này"}
    return {
        "scope": scope,
        "target_id": target_id,
        "n_files": len(rows),
        "total_mb": round(total / (1024 * 1024), 2),
        "warning": (
            f"Sẽ xoá vĩnh viễn {len(rows)} bản ghi âm của {label[scope]}. "
            "Điểm đã chấm và bản chữ vẫn được giữ nguyên."
        ),
    }


def _recordings_for(scope: str, target_id: int) -> list[dict[str, Any]]:
    queries = {
        "attempt": "SELECT id, recording_path FROM turn_attempts WHERE id = ? AND recording_path IS NOT NULL",
        "session": "SELECT id, recording_path FROM turn_attempts WHERE session_id = ? AND recording_path IS NOT NULL",
        "workspace": """
            SELECT a.id, a.recording_path FROM turn_attempts a
            JOIN mock_sessions s ON s.id = a.session_id
            WHERE s.workspace_id = ? AND a.recording_path IS NOT NULL
        """,
    }
    if scope not in queries:
        raise HTTPException(status_code=400, detail="Phạm vi xoá không hợp lệ.")
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(queries[scope], (target_id,)).fetchall()]


@router.delete("/recordings")
def delete_recordings(
    scope: Literal["attempt", "session", "workspace"] = Query(...),
    target_id: int = Query(...),
    confirm: bool = Query(default=False),
) -> dict[str, Any]:
    """Xoá bản ghi âm ở một trong ba mức. Bắt buộc `confirm=true`."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Cần xác nhận: gọi lại với confirm=true sau khi đã xem delete-preview.",
        )
    rows = _recordings_for(scope, target_id)
    deleted, freed = _delete_recordings(rows)
    return {
        "deleted": deleted,
        "freed_mb": round(freed / (1024 * 1024), 2),
        "message": (
            f"Đã xoá {deleted} bản ghi âm, giải phóng {freed / (1024 * 1024):.1f} MB. "
            "Điểm đã chấm vẫn được giữ."
        ),
    }


@router.delete("/tts-cache")
def clear_tts_cache() -> dict[str, Any]:
    """Xoá cache audio lời thoại. Lần nghe sau sẽ sinh lại (chậm hơn một chút)."""
    n = tts.clear_cache()
    with get_conn() as conn:
        conn.execute("UPDATE mock_turns SET tts_path = NULL")
    return {"deleted": n, "message": f"Đã xoá {n} tệp audio trong cache."}
