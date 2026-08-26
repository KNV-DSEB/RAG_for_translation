"""Routes Module 3: sinh kịch bản, nộp bản dịch từng lượt, chấm điểm, báo cáo buổi.

Input:  cấu hình buổi mock, bản dịch của chuyên gia.
Output: kịch bản, điểm từng lượt, báo cáo cuối buổi.

Ở Giai đoạn 3 chuyên gia gõ bản dịch. Giai đoạn 4 sẽ thêm đường vào bằng giọng nói,
dùng chung đúng các endpoint này (chỉ khác `input_mode`).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from backend.routes._ops import OpContext, op_context
from backend.security import gateway, llm
from fastapi import Depends, APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import get_conn
from backend.simulation import scorer
from backend.simulation.generator import generate_script

router = APIRouter(prefix="/simulate", tags=["simulate"])


class ScriptRequest(BaseModel):
    workspace_id: int
    topic: str = Field(min_length=1)
    client_name: str | None = None
    partner_names: list[str] = Field(default_factory=list)
    difficulty: Literal["basic", "medium", "hard"] = "medium"
    n_turns: int = Field(default=8, ge=8, le=10)
    hide_script: bool = True
    engagement_id: int | None = None


class AttemptRequest(BaseModel):
    turn_id: int
    transcript: str = Field(min_length=1)
    input_mode: Literal["speech", "typed"] = "typed"
    transcript_raw: str | None = None
    replay_count: int = 0
    response_time_sec: float | None = None
    recording_path: str | None = None


def _require_workspace(workspace_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")
    return dict(row)


@router.get("/context")
def get_context(workspace_id: int = Query(...)) -> dict[str, Any]:
    """Bối cảnh sẽ dùng để sinh kịch bản — hiện cho chuyên gia biết trước (spec §2.3 bước 1)."""
    workspace = _require_workspace(workspace_id)
    with get_conn() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM documents WHERE workspace_id = ? AND status='ready') AS n_documents,
              (SELECT COUNT(*) FROM documents WHERE workspace_id = ? AND language='parallel'
                                                AND status='ready')                      AS n_parallel,
              (SELECT COUNT(*) FROM glossary  WHERE workspace_id = ? AND status <> 'skipped') AS n_terms,
              (SELECT COUNT(*) FROM glossary  WHERE workspace_id = ? AND status = 'expert_edited') AS n_expert_terms,
              (SELECT COUNT(*) FROM glossary  WHERE workspace_id = ? AND confidence='aligned_from_parallel') AS n_human_terms,
              (SELECT COUNT(*) FROM profiles  WHERE workspace_id = ?)                     AS n_profiles
            """,
            (workspace_id,) * 6,
        ).fetchone()

        entities = conn.execute(
            """
            SELECT DISTINCT entity_name, entity_role FROM profiles WHERE workspace_id = ?
            ORDER BY CASE entity_role WHEN 'client' THEN 0 ELSE 1 END
            """,
            (workspace_id,),
        ).fetchall()

    data = {k: int(v or 0) for k, v in dict(counts).items()}
    warnings: list[str] = []
    if not data["n_profiles"]:
        warnings.append(
            "Chưa có hồ sơ khách hàng — kịch bản sẽ chung chung. "
            "Chạy Nghiên cứu trước để kịch bản dùng đúng bối cảnh thật."
        )
    if data["n_fields_unsourced"]:
        warnings.append(
            f"{data['n_fields_unsourced']}/{data['n_fields']} trường hồ sơ chưa có nguồn — "
            "KHÔNG được đưa vào kịch bản, để bạn không luyện tập trên số liệu máy suy đoán. "
            "Vào màn Nghiên cứu xác minh hoặc sửa lại thì chúng sẽ được dùng."
        )
    if data["n_terms"] < 5:
        warnings.append(
            f"Bảng thuật ngữ chỉ có {data['n_terms']} mục — kịch bản sẽ ít thuật ngữ chuyên ngành."
        )

    return {
        "workspace": workspace,
        **data,
        "entities": [dict(e) for e in entities],
        "warnings": warnings,
    }


@router.post("/script")
def create_script(
    payload: ScriptRequest, op: OpContext = Depends(op_context)
) -> dict[str, Any]:
    """Sinh kịch bản mới. Tự kiểm và sinh lại một lần nếu chưa đạt chuẩn."""
    workspace = _require_workspace(payload.workspace_id)

    # 2 nội dung: lần sinh đầu, và lần sinh lại khi bản đầu không đạt chuẩn.
    with gateway.operation(
        payload.workspace_id,
        kind="simulate.script",
        declares=[gateway.OperationDeclaration(
            "llm", gateway.PROVIDER_GEMINI, unit_calls=2,
            retries_each=llm.retry_ceiling("quality"),
        )],
        fingerprint=op.fingerprint,
        resume_id=op.resume_id,
    ):
        result = generate_script(
            workspace_id=payload.workspace_id,
            topic=payload.topic.strip(),
            client_name=(payload.client_name or str(workspace["name"])).strip(),
            partner_names=[p.strip() for p in payload.partner_names if p.strip()],
            difficulty=payload.difficulty,
            n_turns=payload.n_turns,
            hide_script=payload.hide_script,
            engagement_id=payload.engagement_id,
        )
    return get_session(result.session_id)


@router.get("/sessions")
def list_sessions(workspace_id: int = Query(...), limit: int = Query(default=30, ge=1, le=200)) -> list[dict[str, Any]]:
    _require_workspace(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, mode, difficulty, n_turns, hide_script, status, overall_score,
                   started_at, completed_at, created_at
            FROM mock_sessions WHERE workspace_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/sessions/{session_id}")
def get_session(session_id: int) -> dict[str, Any]:
    """Kịch bản đầy đủ của một buổi, kèm trạng thái từng lượt."""
    with get_conn() as conn:
        session = conn.execute(
            "SELECT * FROM mock_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy buổi mock này.")

        turns = conn.execute(
            "SELECT * FROM mock_turns WHERE session_id = ? ORDER BY turn_index", (session_id,)
        ).fetchall()

        turn_items: list[dict[str, Any]] = []
        for turn in turns:
            attempt = conn.execute(
                """
                SELECT a.*, s.score_overall, s.score_meaning, s.score_terminology,
                       s.score_completeness, s.score_expression, s.comment, s.term_verdicts
                FROM turn_attempts a LEFT JOIN scores s ON s.attempt_id = a.id
                WHERE a.turn_id = ? ORDER BY a.id DESC LIMIT 1
                """,
                (int(turn["id"]),),
            ).fetchone()

            item = dict(turn)
            try:
                item["terms_used"] = json.loads(str(item.get("terms_used") or "[]"))
            except json.JSONDecodeError:
                item["terms_used"] = []
            item["attempt"] = dict(attempt) if attempt else None
            turn_items.append(item)

    data = dict(session)
    try:
        data["gen_warnings"] = json.loads(str(data.get("gen_warnings") or "[]"))
    except json.JSONDecodeError:
        data["gen_warnings"] = []
    data.pop("script_json", None)  # đã tách thành bảng mock_turns, không cần trả lại

    return {
        "session": data,
        "turns": turn_items,
        "n_scored": sum(1 for t in turn_items if t.get("attempt") and t["attempt"].get("score_overall") is not None),
    }


@router.post("/attempts")
def submit_attempt(payload: AttemptRequest) -> dict[str, Any]:
    """Nộp bản dịch cho một lượt. Chưa chấm — chấm ở endpoint riêng để tách lỗi rõ ràng."""
    with get_conn() as conn:
        turn = conn.execute(
            "SELECT * FROM mock_turns WHERE id = ?", (payload.turn_id,)
        ).fetchone()
        if turn is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy lượt thoại này.")

        session_id = int(turn["session_id"])
        conn.execute(
            "UPDATE mock_sessions SET status = 'in_progress', "
            "started_at = COALESCE(started_at, datetime('now')) WHERE id = ?",
            (session_id,),
        )
        attempt_id = int(
            conn.execute(
                """
                INSERT INTO turn_attempts
                    (turn_id, session_id, recording_path, transcript_raw, transcript_edited,
                     input_mode, replay_count, response_time_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.turn_id, session_id, payload.recording_path,
                    payload.transcript_raw or payload.transcript,
                    payload.transcript.strip(), payload.input_mode,
                    payload.replay_count, payload.response_time_sec,
                ),
            ).lastrowid
            or 0
        )
    return {"attempt_id": attempt_id, "turn_id": payload.turn_id, "session_id": session_id}


def _workspace_of_attempt(attempt_id: int) -> int | None:
    """Hồ sơ mà lần dịch này thuộc về — cần để biết có phải xin phép hay không."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT s.workspace_id FROM turn_attempts a
            JOIN mock_sessions s ON s.id = a.session_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
    return int(row["workspace_id"]) if row else None


@router.post("/attempts/{attempt_id}/score")
def score(attempt_id: int, op: OpContext = Depends(op_context)) -> dict[str, Any]:
    """Chấm một lần dịch theo 4 tiêu chí, thang 10."""
    workspace_id = _workspace_of_attempt(attempt_id)
    try:
        with gateway.operation(
            workspace_id,
            kind="simulate.score",
            declares=[gateway.OperationDeclaration(
                "llm", gateway.PROVIDER_GEMINI, unit_calls=1,
                retries_each=llm.retry_ceiling("light"),
            )],
            fingerprint=op.fingerprint,
            resume_id=op.resume_id,
        ):
            result = scorer.score_attempt(attempt_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "attempt_id": result.attempt_id,
        "scores": {
            "meaning": result.score_meaning,
            "terminology": result.score_terminology,
            "completeness": result.score_completeness,
            "expression": result.score_expression,
            "overall": result.score_overall,
        },
        "comment": result.comment,
        "term_verdicts": result.term_verdicts,
        "missing_items": result.missing_items,
        "reference_translation": result.reference_translation,
        "reference_tier": result.reference_tier,
        "notes": result.notes,
    }


@router.get("/sessions/{session_id}/report")
def report(session_id: int) -> dict[str, Any]:
    """Báo cáo cuối buổi."""
    try:
        return scorer.session_report(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/complete")
def complete(session_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE mock_sessions SET status = 'completed', completed_at = datetime('now') WHERE id = ?",
            (session_id,),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy buổi mock này.")
    return scorer.session_report(session_id)
