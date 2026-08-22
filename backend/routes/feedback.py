"""Routes §6: chuyên gia phản biện điểm AI, và trang Đối chiếu chấm điểm.

Input:  nhận định của chuyên gia về một lượt đã chấm.
Output: xác nhận đã lưu + cảnh báo nếu mâu thuẫn với nhận định trước; số liệu độ lệch.

Điểm AI và điểm chuyên gia lưu SONG SONG, không ghi đè lẫn nhau (spec A5.2).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import get_conn
from backend.feedback import calibration
from backend.feedback.calibration import VerdictInput

router = APIRouter(prefix="/feedback", tags=["feedback"])


class VerdictRequest(BaseModel):
    attempt_id: int
    action: Literal["agree", "adjust", "note", "pin_translation"]
    score_meaning: float | None = Field(default=None, ge=0, le=10)
    score_terminology: float | None = Field(default=None, ge=0, le=10)
    score_completeness: float | None = Field(default=None, ge=0, le=10)
    score_expression: float | None = Field(default=None, ge=0, le=10)
    note: str = ""
    related_term_id: int | None = None
    pinned_translation: str = ""


@router.post("/verdict")
def submit_verdict(payload: VerdictRequest) -> dict[str, Any]:
    """Lưu nhận định của chuyên gia về một lượt đã chấm."""
    scores = {
        "meaning": payload.score_meaning,
        "terminology": payload.score_terminology,
        "completeness": payload.score_completeness,
        "expression": payload.score_expression,
    }
    try:
        result = calibration.save_verdict(
            VerdictInput(
                attempt_id=payload.attempt_id,
                action=payload.action,
                scores={k: v for k, v in scores.items() if v is not None},
                note=payload.note,
                related_term_id=payload.related_term_id,
                pinned_translation=payload.pinned_translation,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "verdict_id": result.verdict_id,
        "messages": result.messages,
        "contradictions": result.contradictions,
    }


@router.get("/verdicts")
def list_verdicts(
    workspace_id: int = Query(...), limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    """Những gì chuyên gia đã dạy hệ thống, mới nhất trước."""
    return calibration.verdict_history(workspace_id, limit)


@router.get("/divergence")
def divergence(workspace_id: int = Query(...)) -> dict[str, Any]:
    """Trang Đối chiếu chấm điểm: AI lệch bao nhiêu so với chuyên gia (spec A5.5)."""
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")
    return calibration.divergence_report(workspace_id)


@router.get("/calibration-preview")
def calibration_preview(
    workspace_id: int = Query(...), category: str | None = Query(default=None)
) -> dict[str, Any]:
    """Xem chính xác khối luật chấm đang được chèn vào prompt.

    Minh bạch: chuyên gia thấy được hệ thống đang "nhớ" những gì về cách chấm của mình,
    thay vì phải tin lời.
    """
    text = calibration.build_calibration_text(workspace_id, category)
    verdicts = calibration.relevant_verdicts(workspace_id, category)
    return {
        "workspace_id": workspace_id,
        "category": category,
        "active": bool(text),
        "n_rules": len(verdicts),
        "text": text,
        "note": (
            "Đây là hiệu chỉnh bằng ngữ cảnh, KHÔNG phải huấn luyện lại mô hình. "
            "Mỗi lần chấm chỉ chèn được một số nhận định có hạn nên hệ thống chọn "
            "phần liên quan nhất."
        ),
    }


@router.post("/reset-calibration")
def reset_calibration(workspace_id: int = Query(...), confirm: bool = Query(default=False)) -> dict[str, Any]:
    """Đặt lại hiệu chỉnh về mặc định. GIỮ điểm chuyên gia đã sửa, chỉ bỏ phần luật chấm."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Cần xác nhận: gọi lại với confirm=true.",
        )
    n = calibration.reset_calibration(workspace_id)
    return {
        "cleared": n,
        "message": (
            f"Đã bỏ {n} nhận định khỏi luật chấm. Điểm bạn đã sửa vẫn được giữ nguyên "
            "trong lịch sử."
        ),
    }
