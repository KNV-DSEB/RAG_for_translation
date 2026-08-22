"""Chấm điểm bản dịch của chuyên gia: 4 tiêu chí, thang 10 điểm.

Input:  lượt thoại + bản dịch của chuyên gia.
Output: bản ghi `scores` với điểm từng tiêu chí, nhận xét, và phán quyết từng thuật ngữ.

Hai điểm thiết kế đáng chú ý:

1. Điểm tiêu chí Thuật ngữ KHÔNG phó mặc cho LLM. Các thuật ngữ chuyên gia đã sửa tay là
   chuẩn đã chốt, nên hệ thống tự đối chiếu bản dịch với chuẩn đó và ÁP CỨNG kết quả
   (spec §6.3). LLM chỉ nhận xét, không được quyền phủ quyết bản dịch chuyên gia đã chốt.

2. Bản dịch tham chiếu có ba mức tin cậy (§6.1). Mức được ghi vào prompt để LLM biết khi nào
   bản tham chiếu là chuẩn tuyệt đối (người thật dịch) và khi nào chỉ là một cách dịch tốt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import Field

from backend.db import get_conn
from backend.feedback import calibration
from backend.security import llm
from backend.security.llm import LLMSchema
from backend.simulation.prompts import SCORING_SYSTEM, build_scoring_prompt

CRITERIA = ("meaning", "terminology", "completeness", "expression")

CRITERIA_LABELS = {
    "meaning": "Độ chính xác nghĩa",
    "terminology": "Thuật ngữ",
    "completeness": "Độ đầy đủ",
    "expression": "Diễn đạt",
}


class TermVerdictOut(LLMSchema):
    term_vi: str
    expected_en: str = Field(description="Bản dịch chuẩn theo bảng thuật ngữ")
    used_by_expert: str = Field(description="Chuyên gia đã dịch thành gì, rỗng nếu bỏ sót")
    correct: bool


class ScoreOut(LLMSchema):
    score_meaning: float = Field(description="Độ chính xác nghĩa, 0–10")
    score_terminology: float = Field(description="Thuật ngữ, 0–10")
    score_completeness: float = Field(description="Độ đầy đủ, 0–10")
    score_expression: float = Field(description="Diễn đạt, 0–10")
    comment: str = Field(description="Nhận xét cụ thể bằng tiếng Việt, chỉ rõ chỗ sai và cách sửa")
    term_verdicts: list[TermVerdictOut] = Field(
        description="Phán quyết từng thuật ngữ có trong lượt này"
    )
    missing_items: list[str] = Field(
        description="Các thông tin bị bỏ sót: số liệu, tên riêng, điều kiện, chức danh"
    )


@dataclass
class TurnScore:
    attempt_id: int
    score_meaning: float
    score_terminology: float
    score_completeness: float
    score_expression: float
    score_overall: float
    comment: str
    term_verdicts: list[dict[str, object]] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)
    reference_translation: str = ""
    reference_tier: str = "ai"
    notes: list[str] = field(default_factory=list)


def _clamp(value: float) -> float:
    return round(max(0.0, min(10.0, float(value))), 1)


def _turn_terms(turn: dict[str, object]) -> list[dict[str, object]]:
    """Lấy chi tiết các thuật ngữ gắn với lượt này."""
    try:
        term_ids = json.loads(str(turn.get("terms_used") or "[]"))
    except json.JSONDecodeError:
        term_ids = []
    if not term_ids:
        return []
    placeholders = ",".join("?" * len(term_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, term_vi, term_en, definition, status
            FROM glossary WHERE id IN ({placeholders})
            """,
            tuple(term_ids),
        ).fetchall()
    return [dict(r) for r in rows]


def _contains_term(text: str, term: str) -> bool:
    """Bản dịch có chứa thuật ngữ này không (so khớp lỏng, bỏ qua hoa/thường và dấu câu)."""
    def norm(s: str) -> str:
        return re.sub(r"[^\w\s]", " ", s.lower())

    return norm(term).strip() in norm(text)


def score_attempt(
    attempt_id: int,
    *,
    calibration_text: str | None = None,
) -> TurnScore:
    """Chấm một lần dịch. Dùng bản transcript ĐÃ SỬA nếu chuyên gia có sửa (spec A3.14).

    `calibration_text=None` (mặc định) thì tự lấy các nhận định liên quan của chuyên gia và
    chèn vào prompt như luật chấm — đây là chỗ §6 vòng phản hồi thực sự có tác dụng.
    Truyền chuỗi rỗng để chấm "thô", không hiệu chỉnh (dùng khi so sánh đối chứng).
    """
    with get_conn() as conn:
        attempt = conn.execute(
            "SELECT * FROM turn_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        if attempt is None:
            raise ValueError("Không tìm thấy lần dịch này.")
        turn = conn.execute(
            "SELECT * FROM mock_turns WHERE id = ?", (int(attempt["turn_id"]),)
        ).fetchone()
        if turn is None:
            raise ValueError("Không tìm thấy lượt thoại tương ứng.")
        session = conn.execute(
            "SELECT workspace_id FROM mock_sessions WHERE id = ?", (int(turn["session_id"]),)
        ).fetchone()

    workspace_id = int(session["workspace_id"]) if session else None

    # Bản đã sửa luôn thắng bản thô: chấm theo cái chuyên gia xác nhận, không chấm oan
    # vì máy nghe nhầm.
    user_translation = str(
        attempt["transcript_edited"] or attempt["transcript_raw"] or ""
    ).strip()
    if not user_translation:
        raise ValueError(
            "Chưa có bản dịch để chấm. Hãy ghi âm hoặc gõ bản dịch trước."
        )

    terms = _turn_terms(dict(turn))
    glossary_text = "\n".join(
        f"  - {t['term_vi']} = {t['term_en']}"
        + (" (bạn đã chốt bản dịch này)" if t["status"] == "expert_edited" else "")
        for t in terms
    )

    # §6: lấy nhận định chuyên gia đã ghi ở các buổi trước, ưu tiên cùng phân loại thuật ngữ
    if calibration_text is None:
        category = None
        if terms:
            categories = [str(t["category"]) for t in terms if t.get("category")]
            category = max(set(categories), key=categories.count) if categories else None
        calibration_text = (
            calibration.build_calibration_text(workspace_id, category)
            if workspace_id is not None
            else ""
        )

    prompt = build_scoring_prompt(
        source_lang=str(turn["source_lang"]),
        target_lang=str(turn["target_lang"]),
        source_text=str(turn["source_text"]),
        reference_translation=str(turn["reference_translation"] or ""),
        reference_tier=str(turn["reference_tier"]),
        user_translation=user_translation,
        glossary_text=glossary_text,
        calibration_text=calibration_text,
    )

    result = llm.generate_json(
        module="simulation.score",
        prompt=prompt,
        schema=ScoreOut,
        workspace_id=workspace_id,
        system_instruction=SCORING_SYSTEM,
        temperature=0.15,
        summary=f"Chấm lượt {int(turn['turn_index']) + 1} ({turn['source_lang']}→{turn['target_lang']})",
        tier="light",
    )

    notes: list[str] = []
    verdicts = [v.model_dump() for v in result.term_verdicts]

    # --- Áp cứng phán quyết cho thuật ngữ chuyên gia đã chốt ---
    pinned = [t for t in terms if t["status"] == "expert_edited"]
    for term in pinned:
        expected = str(term["term_en"]) if turn["target_lang"] == "en" else str(term["term_vi"])
        actually_used = _contains_term(user_translation, expected)

        existing = next(
            (v for v in verdicts if v.get("term_vi") == term["term_vi"]), None
        )
        if existing is None:
            verdicts.append(
                {
                    "term_vi": term["term_vi"],
                    "expected_en": expected,
                    "used_by_expert": expected if actually_used else "",
                    "correct": actually_used,
                }
            )
        elif bool(existing.get("correct")) != actually_used:
            # LLM chấm khác với đối chiếu trực tiếp -> tin đối chiếu, vì đây là bản
            # dịch chính chuyên gia đã chốt làm chuẩn.
            existing["correct"] = actually_used
            notes.append(
                f"Thuật ngữ '{term['term_vi']}' chấm theo bản bạn đã chốt "
                f"('{expected}'), không theo suy đoán của mô hình."
            )

    scores = {
        "meaning": _clamp(result.score_meaning),
        "terminology": _clamp(result.score_terminology),
        "completeness": _clamp(result.score_completeness),
        "expression": _clamp(result.score_expression),
    }

    # Nếu có thuật ngữ đã chốt mà bị dùng sai, điểm Thuật ngữ không được cao hơn mức này.
    if pinned:
        pinned_names = {str(t["term_vi"]) for t in pinned}
        wrong = [
            v for v in verdicts
            if v.get("term_vi") in pinned_names and not v.get("correct")
        ]
        if wrong:
            ceiling = max(0.0, 10.0 - 2.5 * len(wrong))
            if scores["terminology"] > ceiling:
                scores["terminology"] = ceiling
                notes.append(
                    f"Điểm Thuật ngữ bị giới hạn ở {ceiling} vì dùng sai "
                    f"{len(wrong)} thuật ngữ bạn đã chốt bản dịch."
                )

    overall = round(sum(scores.values()) / len(scores), 1)

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO scores
                (attempt_id, score_meaning, score_terminology, score_completeness,
                 score_expression, score_overall, comment, term_verdicts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id, scores["meaning"], scores["terminology"],
                scores["completeness"], scores["expression"], overall,
                result.comment.strip(),
                json.dumps(
                    {"terms": verdicts, "missing": result.missing_items},
                    ensure_ascii=False,
                ),
            ),
        )

    return TurnScore(
        attempt_id=attempt_id,
        score_meaning=scores["meaning"],
        score_terminology=scores["terminology"],
        score_completeness=scores["completeness"],
        score_expression=scores["expression"],
        score_overall=overall,
        comment=result.comment.strip(),
        term_verdicts=verdicts,
        missing_items=result.missing_items,
        reference_translation=str(turn["reference_translation"] or ""),
        reference_tier=str(turn["reference_tier"]),
        notes=notes,
    )


def session_report(session_id: int) -> dict[str, object]:
    """Báo cáo cuối buổi: điểm tổng, điểm từng tiêu chí, bảng theo lượt, thuật ngữ cần ôn."""
    with get_conn() as conn:
        session = conn.execute(
            "SELECT * FROM mock_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if session is None:
            raise ValueError("Không tìm thấy buổi mock này.")

        rows = conn.execute(
            """
            SELECT t.turn_index, t.speaker_name, t.source_lang, t.target_lang,
                   t.source_text, t.reference_translation, t.reference_tier,
                   a.id AS attempt_id, a.transcript_edited, a.transcript_raw,
                   a.input_mode, a.replay_count, a.response_time_sec,
                   s.score_meaning, s.score_terminology, s.score_completeness,
                   s.score_expression, s.score_overall, s.comment, s.term_verdicts
            FROM mock_turns t
            LEFT JOIN turn_attempts a ON a.turn_id = t.id
            LEFT JOIN scores s ON s.attempt_id = a.id
            WHERE t.session_id = ?
            ORDER BY t.turn_index, a.id
            """,
            (session_id,),
        ).fetchall()

    turns = [dict(r) for r in rows]
    scored = [t for t in turns if t.get("score_overall") is not None]

    averages: dict[str, float | None] = {}
    for name in CRITERIA:
        values = [float(t[f"score_{name}"]) for t in scored if t.get(f"score_{name}") is not None]
        averages[name] = round(sum(values) / len(values), 1) if values else None

    overall_values = [float(t["score_overall"]) for t in scored]
    overall = round(sum(overall_values) / len(overall_values), 1) if overall_values else None

    # Thuật ngữ dịch sai -> danh sách cần ôn
    need_review: dict[str, dict[str, object]] = {}
    for turn in scored:
        try:
            payload = json.loads(str(turn.get("term_verdicts") or "{}"))
        except json.JSONDecodeError:
            continue
        for verdict in payload.get("terms", []):
            if verdict.get("correct"):
                continue
            key = str(verdict.get("term_vi"))
            entry = need_review.setdefault(
                key, {"term_vi": key, "expected": verdict.get("expected_en"), "count": 0}
            )
            entry["count"] = int(entry["count"]) + 1

    if overall is not None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE mock_sessions SET overall_score = ? WHERE id = ?", (overall, session_id)
            )

    return {
        "session": dict(session),
        "turns": turns,
        "n_turns": len({t["turn_index"] for t in turns}),
        "n_scored": len(scored),
        "overall_score": overall,
        "averages": averages,
        "criteria_labels": CRITERIA_LABELS,
        "terms_to_review": sorted(
            need_review.values(), key=lambda x: int(x["count"]), reverse=True
        ),
    }
