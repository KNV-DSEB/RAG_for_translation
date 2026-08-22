"""§6 Vòng phản hồi: lưu nhận định của chuyên gia và dùng lại khi chấm những lần sau.

Input:  phản biện của chuyên gia về điểm AI đã chấm (đồng ý / sửa điểm / ghi nhận định / chốt cách dịch).
Output: bản ghi `expert_verdicts`, và khối văn bản hiệu chỉnh chèn vào prompt chấm điểm.

NÓI RÕ ĐỂ KHÔNG HIỂU SAI: đây là **hiệu chỉnh bằng ngữ cảnh**, KHÔNG phải fine-tune mô hình.
Cơ chế thật là: lưu nhận định vào cơ sở dữ liệu, rồi những lần chấm sau chọn ra các nhận định
liên quan nhất và chèn vào prompt như luật chấm. Giới hạn kèm theo: mỗi lần chấm chỉ đưa được
một số nhận định có hạn, nên hệ thống chọn phần liên quan nhất chứ không đưa tất cả.

Ba quy tắc nghiệp vụ:
    - Chỉ nhận định CÓ LÝ DO mới dùng để hiệu chỉnh (sửa điểm suông thì chỉ lưu, không dạy lại).
    - Sửa thuật ngữ được ÁP CỨNG ở `scorer`, không để LLM đoán lại.
    - Nhận định mâu thuẫn nhau giữa các buổi thì HIỆN CẢ HAI cho chuyên gia, không tự chọn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from backend.config import settings
from backend.db import get_conn

Action = Literal["agree", "adjust", "note", "pin_translation"]

CRITERIA = ("meaning", "terminology", "completeness", "expression")

CRITERIA_LABELS = {
    "meaning": "Độ chính xác nghĩa",
    "terminology": "Thuật ngữ",
    "completeness": "Độ đầy đủ",
    "expression": "Diễn đạt",
}

# Độ lệch trung bình vượt mức này thì coi là AI đang chấm lệch đáng kể so với chuyên gia.
SIGNIFICANT_GAP = 1.0


@dataclass
class VerdictInput:
    attempt_id: int
    action: Action
    scores: dict[str, float] = field(default_factory=dict)
    note: str = ""
    related_term_id: int | None = None
    pinned_translation: str = ""


@dataclass
class SaveResult:
    verdict_id: int
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _attempt_context(attempt_id: int) -> dict[str, Any]:
    """Lấy workspace và phân loại thuật ngữ của lượt, để gắn nhãn nhận định."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.id AS attempt_id, a.turn_id, t.session_id, t.turn_index,
                   t.source_lang, t.target_lang, t.terms_used, s.workspace_id
            FROM turn_attempts a
            JOIN mock_turns t ON t.id = a.turn_id
            JOIN mock_sessions s ON s.id = t.session_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Không tìm thấy lần dịch này.")
    return dict(row)


def _dominant_category(terms_used_json: str | None) -> str | None:
    """Phân loại thuật ngữ chính của lượt — dùng để chọn lại nhận định cùng loại."""
    import json

    try:
        ids = json.loads(str(terms_used_json or "[]"))
    except json.JSONDecodeError:
        return None
    if not ids:
        return None
    placeholders = ",".join("?" * len(ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT category, COUNT(*) AS n FROM glossary
            WHERE id IN ({placeholders}) AND category IS NOT NULL
            GROUP BY category ORDER BY n DESC LIMIT 1
            """,
            tuple(ids),
        ).fetchall()
    return str(rows[0]["category"]) if rows else None


def _find_contradictions(
    workspace_id: int,
    category: str | None,
    note: str,
    new_direction: float | None,
) -> list[dict[str, Any]]:
    """Tìm nhận định cũ ngược chiều với nhận định mới, để hiện CẢ HAI (spec edge case §4.5).

    "Ngược chiều" = lần trước bạn nâng điểm AI lên, lần này lại hạ xuống (hoặc ngược lại),
    trên cùng một phân loại thuật ngữ. Hệ thống KHÔNG tự chọn bên nào — chỉ nêu ra để bạn
    tự xử lý, vì hai nhận định trái nhau mà im lặng chọn một là làm sai ý chuyên gia.
    """
    if not note.strip() or new_direction is None or abs(new_direction) < 1.0:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT v.id, v.note, v.created_at, v.related_category,
                   v.score_overall, s.score_overall AS ai_overall
            FROM expert_verdicts v
            JOIN scores s ON s.attempt_id = v.attempt_id
            WHERE v.workspace_id = ?
              AND TRIM(COALESCE(v.note,'')) <> ''
              AND v.score_overall IS NOT NULL
              AND (? IS NULL OR v.related_category = ?)
            ORDER BY v.created_at DESC LIMIT 8
            """,
            (workspace_id, category, category),
        ).fetchall()

    contradictions: list[dict[str, Any]] = []
    for row in rows:
        old = dict(row)
        if old["ai_overall"] is None:
            continue
        old_direction = float(old["score_overall"]) - float(old["ai_overall"])
        # Ngược dấu và cả hai đều lệch đáng kể mới coi là mâu thuẫn thật
        if old_direction * new_direction < 0 and abs(old_direction) >= 1.0:
            old["direction"] = "nâng điểm" if old_direction > 0 else "hạ điểm"
            old["gap"] = round(old_direction, 1)
            contradictions.append(old)
    return contradictions


def save_verdict(payload: VerdictInput) -> SaveResult:
    """Lưu nhận định của chuyên gia. Điểm AI và điểm chuyên gia lưu SONG SONG, không ghi đè."""
    context = _attempt_context(payload.attempt_id)
    workspace_id = int(context["workspace_id"])
    category = _dominant_category(context.get("terms_used"))

    scores = {k: float(v) for k, v in payload.scores.items() if v is not None}
    overall = None
    if scores:
        present = [scores[k] for k in CRITERIA if k in scores]
        if present:
            overall = round(sum(present) / len(present), 1)

    messages: list[str] = []

    # Chuyên gia đang nâng hay hạ điểm so với AI, để đối chiếu với các nhận định trước.
    with get_conn() as conn:
        ai_row = conn.execute(
            "SELECT score_overall FROM scores WHERE attempt_id = ? ORDER BY id DESC LIMIT 1",
            (payload.attempt_id,),
        ).fetchone()
    ai_overall = float(ai_row["score_overall"]) if ai_row and ai_row["score_overall"] is not None else None
    new_direction = (overall - ai_overall) if (overall is not None and ai_overall is not None) else None

    contradictions = _find_contradictions(
        workspace_id, category, payload.note, new_direction
    )

    with get_conn() as conn:
        # Điểm AI vẫn nguyên trong bảng `scores` — ở đây chỉ THÊM điểm của chuyên gia.
        verdict_id = int(
            conn.execute(
                """
                INSERT INTO expert_verdicts
                    (attempt_id, workspace_id, action, score_meaning, score_terminology,
                     score_completeness, score_expression, score_overall, note,
                     related_category, related_term_id, pinned_translation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.attempt_id, workspace_id, payload.action,
                    scores.get("meaning"), scores.get("terminology"),
                    scores.get("completeness"), scores.get("expression"), overall,
                    payload.note.strip() or None, category, payload.related_term_id,
                    payload.pinned_translation.strip() or None,
                ),
            ).lastrowid
            or 0
        )

        # Chốt cách dịch: nâng bản dịch của chuyên gia lên mức tham chiếu ⭐⭐
        if payload.pinned_translation.strip():
            conn.execute(
                """
                UPDATE mock_turns
                SET reference_translation = ?, reference_tier = 'expert_pinned'
                WHERE id = ?
                """,
                (payload.pinned_translation.strip(), int(context["turn_id"])),
            )
            messages.append(
                "Đã chốt bản dịch của bạn làm tham chiếu cho lượt này. "
                "Những lần chấm sau sẽ đối chiếu theo bản này."
            )

    if payload.note.strip():
        messages.append(
            "Nhận định đã lưu và sẽ được dùng làm luật chấm cho các buổi sau với hồ sơ này."
        )
    elif payload.action == "adjust":
        messages.append(
            "Đã lưu điểm bạn sửa. Ghi thêm lý do thì hệ thống mới học được cách chấm "
            "đúng ý bạn ở buổi sau."
        )

    if contradictions:
        messages.append(
            f"Lưu ý: bạn có {len(contradictions)} nhận định trước đó đi ngược hướng với lần này. "
            "Hệ thống không tự chọn bên nào — xem lại bên dưới và bỏ nhận định không còn đúng."
        )

    return SaveResult(
        verdict_id=verdict_id, contradictions=contradictions, messages=messages
    )


# ============================== Đưa nhận định trở lại prompt ==============================


def relevant_verdicts(
    workspace_id: int, category: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Chọn nhận định liên quan nhất: cùng hồ sơ → cùng phân loại → mới nhất.

    Chỉ lấy nhận định CÓ LÝ DO — sửa điểm suông không nói lên cách chấm nên không dạy lại được.
    """
    cap = limit or settings.max_verdicts_in_prompt

    with get_conn() as conn:
        # Ưu tiên cùng phân loại thuật ngữ, sau đó tới các nhận định khác cùng hồ sơ.
        rows = conn.execute(
            """
            SELECT v.note, v.related_category, v.score_overall, v.action, v.created_at,
                   s.score_overall AS ai_overall,
                   CASE WHEN v.related_category IS NOT NULL AND v.related_category = ?
                        THEN 0 ELSE 1 END AS priority
            FROM expert_verdicts v
            LEFT JOIN scores s ON s.attempt_id = v.attempt_id
            WHERE v.workspace_id = ?
              AND TRIM(COALESCE(v.note,'')) <> ''
            ORDER BY priority, v.created_at DESC
            LIMIT ?
            """,
            (category, workspace_id, cap),
        ).fetchall()
    return [dict(r) for r in rows]


def build_calibration_text(workspace_id: int, category: str | None = None) -> str:
    """Khối văn bản chèn vào prompt chấm điểm. Rỗng nếu chưa có nhận định nào."""
    verdicts = relevant_verdicts(workspace_id, category)
    if not verdicts:
        return ""

    lines: list[str] = []
    for item in verdicts:
        note = str(item["note"]).strip()
        expert = item.get("score_overall")
        ai = item.get("ai_overall")

        direction = ""
        if expert is not None and ai is not None:
            gap = float(expert) - float(ai)
            if gap >= 0.5:
                direction = f" (lần đó bạn chấm CAO hơn AI {gap:.1f} điểm)"
            elif gap <= -0.5:
                direction = f" (lần đó bạn chấm THẤP hơn AI {abs(gap):.1f} điểm)"

        tag = f"[{item['related_category']}] " if item.get("related_category") else ""
        lines.append(f"- {tag}{note}{direction}")

    return "\n".join(lines)


# ============================== Trang Đối chiếu chấm điểm ==============================


def divergence_report(workspace_id: int) -> dict[str, Any]:
    """AI đang chấm lệch bao nhiêu so với chuyên gia, theo từng tiêu chí và theo thời gian.

    Đây cũng là chỗ lộ ra TRỌNG SỐ THẬT mà chuyên gia coi trọng (câu mở O1): tiêu chí nào
    bạn hay sửa điểm nhất chính là tiêu chí bạn quan tâm nhất.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT v.id, v.created_at, v.action, v.related_category,
                   v.score_meaning      AS e_meaning,
                   v.score_terminology  AS e_terminology,
                   v.score_completeness AS e_completeness,
                   v.score_expression   AS e_expression,
                   v.score_overall      AS e_overall,
                   s.score_meaning      AS a_meaning,
                   s.score_terminology  AS a_terminology,
                   s.score_completeness AS a_completeness,
                   s.score_expression   AS a_expression,
                   s.score_overall      AS a_overall,
                   t.session_id
            FROM expert_verdicts v
            JOIN scores s ON s.attempt_id = v.attempt_id
            JOIN turn_attempts a ON a.id = v.attempt_id
            JOIN mock_turns t ON t.id = a.turn_id
            WHERE v.workspace_id = ?
            ORDER BY v.created_at
            """,
            (workspace_id,),
        ).fetchall()

        n_verdicts = conn.execute(
            "SELECT COUNT(*) AS n FROM expert_verdicts WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()["n"]

        n_agree = conn.execute(
            "SELECT COUNT(*) AS n FROM expert_verdicts WHERE workspace_id = ? AND action = 'agree'",
            (workspace_id,),
        ).fetchone()["n"]

    items = [dict(r) for r in rows]

    gaps: dict[str, list[float]] = {c: [] for c in CRITERIA}
    adjust_counts: dict[str, int] = {c: 0 for c in CRITERIA}
    timeline: list[dict[str, Any]] = []

    for item in items:
        row_gaps: dict[str, float | None] = {}
        for criterion in CRITERIA:
            expert = item.get(f"e_{criterion}")
            ai = item.get(f"a_{criterion}")
            if expert is None or ai is None:
                row_gaps[criterion] = None
                continue
            gap = float(expert) - float(ai)
            row_gaps[criterion] = round(gap, 1)
            gaps[criterion].append(gap)
            if abs(gap) >= 0.5:
                adjust_counts[criterion] += 1

        timeline.append(
            {
                "created_at": item["created_at"],
                "session_id": item["session_id"],
                "action": item["action"],
                "ai_overall": item.get("a_overall"),
                "expert_overall": item.get("e_overall"),
                "gaps": row_gaps,
            }
        )

    summary: dict[str, Any] = {}
    for criterion in CRITERIA:
        values = gaps[criterion]
        summary[criterion] = {
            "label": CRITERIA_LABELS[criterion],
            "n": len(values),
            "mean_gap": round(sum(values) / len(values), 2) if values else None,
            "mean_abs_gap": round(sum(abs(v) for v in values) / len(values), 2) if values else None,
            "times_adjusted": adjust_counts[criterion],
        }

    # Xu hướng: độ lệch có giảm dần không. Nếu không giảm thì cơ chế hiệu chỉnh chưa hiệu quả.
    trend: str | None = None
    scored_rows = [t for t in timeline if t["expert_overall"] is not None and t["ai_overall"] is not None]
    if len(scored_rows) >= 4:
        half = len(scored_rows) // 2
        early = [abs(float(t["expert_overall"]) - float(t["ai_overall"])) for t in scored_rows[:half]]
        late = [abs(float(t["expert_overall"]) - float(t["ai_overall"])) for t in scored_rows[half:]]
        early_mean = sum(early) / len(early)
        late_mean = sum(late) / len(late)
        if late_mean < early_mean - 0.3:
            trend = f"đang thu hẹp ({early_mean:.1f} → {late_mean:.1f} điểm)"
        elif late_mean > early_mean + 0.3:
            trend = f"đang giãn ra ({early_mean:.1f} → {late_mean:.1f} điểm)"
        else:
            trend = f"đi ngang (khoảng {late_mean:.1f} điểm)"

    # Tiêu chí chuyên gia thực sự coi trọng = nơi có TỔNG LƯỢNG sửa lớn nhất.
    # Chỉ đếm SỐ LẦN sửa là sai: sửa 2 lần mỗi lần 0.5 điểm nhẹ hơn hẳn sửa 2 lần mỗi lần
    # 2 điểm, mà lời khuyên về trọng số thì phải đúng chỗ mới dùng được.
    totals = {
        criterion: sum(abs(v) for v in gaps[criterion]) for criterion in CRITERIA
    }
    implied_weight_note = None
    if items and any(totals.values()):
        top = max(totals.items(), key=lambda kv: kv[1])[0]
        info = summary[top]
        implied_weight_note = (
            f"Bạn chỉnh tiêu chí “{CRITERIA_LABELS[top]}” nhiều nhất về tổng lượng "
            f"({info['times_adjusted']} lần, lệch trung bình {info['mean_gap']:+.1f} điểm) — "
            "đây là chỗ AI chấm xa ý bạn nhất. Nếu muốn, có thể tăng trọng số tiêu chí này "
            "trong Cài đặt."
        )

    return {
        "n_verdicts": int(n_verdicts or 0),
        "n_agree": int(n_agree or 0),
        "n_compared": len(items),
        "summary": summary,
        "timeline": timeline,
        "trend": trend,
        "implied_weight_note": implied_weight_note,
        "calibration_active": bool(build_calibration_text(workspace_id)),
    }


def reset_calibration(workspace_id: int) -> int:
    """Đặt lại hiệu chỉnh: xoá phần nhận định dùng để dạy lại, GIỮ điểm chuyên gia đã sửa.

    Dùng khi hiệu chỉnh làm chấm điểm lệch quá xa (spec edge case §4.5).
    """
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE expert_verdicts SET note = NULL
            WHERE workspace_id = ? AND TRIM(COALESCE(note,'')) <> ''
            """,
            (workspace_id,),
        )
        return cursor.rowcount


def verdict_history(workspace_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Danh sách nhận định đã ghi, để chuyên gia xem lại mình đã dạy hệ thống những gì."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT v.*, s.score_overall AS ai_overall, t.turn_index, t.session_id,
                   t.source_lang, t.target_lang, t.source_text
            FROM expert_verdicts v
            LEFT JOIN scores s ON s.attempt_id = v.attempt_id
            LEFT JOIN turn_attempts a ON a.id = v.attempt_id
            LEFT JOIN mock_turns t ON t.id = a.turn_id
            WHERE v.workspace_id = ?
            ORDER BY v.created_at DESC, v.id DESC LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
