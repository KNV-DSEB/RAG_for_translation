"""Route tổng hợp cho Dashboard — gom mọi thứ cần hiện vào MỘT lệnh gọi.

Input:  workspace_id.
Output: việc đang dở · buổi làm việc sắp tới · tiến bộ theo thời gian · thuật ngữ cần ôn.

Gom một lệnh gọi thay vì để giao diện gọi sáu lần: Streamlit chạy lại toàn bộ script sau mỗi
tương tác, nên sáu lệnh gọi sẽ thành sáu vòng chờ mỗi lần bấm nút bất kỳ.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.db import get_conn

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _pending_work(conn: Any, workspace_id: int) -> list[dict[str, Any]]:
    """Việc đang dở: tài liệu lỗi/chưa xong, buổi mock bỏ giữa chừng, xung đột chưa xử."""
    items: list[dict[str, Any]] = []

    rows = conn.execute(
        """
        SELECT id, filename, status, error_message FROM documents
        WHERE workspace_id = ? AND status <> 'ready'
        ORDER BY id DESC LIMIT 10
        """,
        (workspace_id,),
    ).fetchall()
    for row in rows:
        items.append(
            {
                "kind": "document",
                "icon": "📄",
                "title": f"Tài liệu “{row['filename']}” chưa nạp xong",
                "detail": str(row["error_message"] or f"đang ở trạng thái {row['status']}"),
                "action": "Mở tab Tài liệu",
                "page": "documents",
            }
        )

    rows = conn.execute(
        """
        SELECT s.id, s.n_turns, s.created_at,
               (SELECT COUNT(*) FROM turn_attempts a
                JOIN scores sc ON sc.attempt_id = a.id
                WHERE a.session_id = s.id) AS n_scored
        FROM mock_sessions s
        WHERE s.workspace_id = ? AND s.status IN ('generated', 'in_progress')
        ORDER BY s.created_at DESC LIMIT 5
        """,
        (workspace_id,),
    ).fetchall()
    for row in rows:
        done = int(row["n_scored"] or 0)
        total = int(row["n_turns"] or 0)
        items.append(
            {
                "kind": "session",
                "icon": "🎙️",
                "title": f"Buổi mock #{row['id']} đang dở",
                "detail": f"đã chấm {done}/{total} lượt",
                "action": "Mở lại buổi",
                "page": "mock",
                "session_id": int(row["id"]),
            }
        )

    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM glossary_conflicts c
        JOIN glossary g ON g.id = c.glossary_id
        WHERE g.workspace_id = ? AND c.resolved = 0
        """,
        (workspace_id,),
    ).fetchone()
    if int(row["n"] or 0):
        items.append(
            {
                "kind": "conflict",
                "icon": "⚠️",
                "title": f"{row['n']} thuật ngữ có bản dịch xung đột",
                "detail": "cần bạn chọn bản chuẩn — hệ thống không tự chọn",
                "action": "Mở bảng thuật ngữ",
                "page": "research",
            }
        )

    return items


def _upcoming(conn: Any, workspace_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, topic, partners, event_date FROM engagements
        WHERE workspace_id = ? AND event_date IS NOT NULL
          AND date(event_date) >= date('now')
        ORDER BY date(event_date) LIMIT 5
        """,
        (workspace_id,),
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            partners = json.loads(str(row["partners"] or "[]"))
        except json.JSONDecodeError:
            partners = []
        items.append(
            {
                "id": int(row["id"]),
                "topic": str(row["topic"]),
                "partners": partners,
                "event_date": str(row["event_date"]),
            }
        )
    return items


def _progress(conn: Any, workspace_id: int) -> dict[str, Any]:
    """Điểm các buổi đã chấm, theo thời gian, kèm trung bình từng tiêu chí."""
    rows = conn.execute(
        """
        SELECT s.id, s.created_at, s.difficulty, s.mode,
               AVG(sc.score_overall)      AS overall,
               AVG(sc.score_meaning)      AS meaning,
               AVG(sc.score_terminology)  AS terminology,
               AVG(sc.score_completeness) AS completeness,
               AVG(sc.score_expression)   AS expression,
               COUNT(sc.id)               AS n_scored
        FROM mock_sessions s
        JOIN turn_attempts a ON a.session_id = s.id
        JOIN scores sc ON sc.attempt_id = a.id
        WHERE s.workspace_id = ?
        GROUP BY s.id
        HAVING n_scored > 0
        ORDER BY s.created_at
        """,
        (workspace_id,),
    ).fetchall()

    sessions = [
        {
            "session_id": int(r["id"]),
            "created_at": str(r["created_at"]),
            "difficulty": str(r["difficulty"]),
            "n_scored": int(r["n_scored"]),
            "overall": round(float(r["overall"]), 1),
            "meaning": round(float(r["meaning"]), 1) if r["meaning"] is not None else None,
            "terminology": round(float(r["terminology"]), 1) if r["terminology"] is not None else None,
            "completeness": round(float(r["completeness"]), 1) if r["completeness"] is not None else None,
            "expression": round(float(r["expression"]), 1) if r["expression"] is not None else None,
        }
        for r in rows
    ]

    trend = None
    if len(sessions) >= 2:
        delta = sessions[-1]["overall"] - sessions[0]["overall"]
        if delta >= 0.3:
            trend = f"tăng {delta:+.1f} điểm từ buổi đầu"
        elif delta <= -0.3:
            trend = f"giảm {delta:+.1f} điểm từ buổi đầu"
        else:
            trend = "đi ngang qua các buổi"

    return {"sessions": sessions, "trend": trend}


def _terms_to_review(conn: Any, workspace_id: int, limit: int = 12) -> list[dict[str, Any]]:
    """Thuật ngữ đã dịch sai, gộp qua mọi buổi mock của hồ sơ này."""
    rows = conn.execute(
        """
        SELECT sc.term_verdicts FROM scores sc
        JOIN turn_attempts a ON a.id = sc.attempt_id
        JOIN mock_sessions s ON s.id = a.session_id
        WHERE s.workspace_id = ? AND sc.term_verdicts IS NOT NULL
        """,
        (workspace_id,),
    ).fetchall()

    tally: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            payload = json.loads(str(row["term_verdicts"] or "{}"))
        except json.JSONDecodeError:
            continue
        for verdict in payload.get("terms", []):
            if verdict.get("correct"):
                continue
            key = str(verdict.get("term_vi") or "").strip()
            if not key:
                continue
            entry = tally.setdefault(
                key,
                {"term_vi": key, "expected": verdict.get("expected_en"), "wrong_times": 0},
            )
            entry["wrong_times"] = int(entry["wrong_times"]) + 1

    return sorted(tally.values(), key=lambda x: int(x["wrong_times"]), reverse=True)[:limit]


@router.get("")
def get_dashboard(workspace_id: int = Query(...)) -> dict[str, Any]:
    """Toàn bộ số liệu Dashboard trong một lệnh gọi."""
    with get_conn() as conn:
        workspace = conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")

        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM documents WHERE workspace_id = ? AND status='ready')     AS n_documents,
              (SELECT COUNT(*) FROM glossary  WHERE workspace_id = ? AND status <> 'skipped') AS n_terms,
              (SELECT COUNT(*) FROM glossary  WHERE workspace_id = ? AND status = 'expert_edited') AS n_terms_expert,
              (SELECT COUNT(*) FROM mock_sessions WHERE workspace_id = ?)                     AS n_sessions,
              (SELECT COUNT(*) FROM expert_verdicts WHERE workspace_id = ?)                   AS n_verdicts,
              (SELECT COUNT(*) FROM profiles WHERE workspace_id = ?)                          AS n_profiles
            """,
            (workspace_id,) * 6,
        ).fetchone()

        data = {
            "workspace": dict(workspace),
            **{k: int(v or 0) for k, v in dict(counts).items()},
            "pending_work": _pending_work(conn, workspace_id),
            "upcoming": _upcoming(conn, workspace_id),
            "progress": _progress(conn, workspace_id),
            "terms_to_review": _terms_to_review(conn, workspace_id),
        }

    # Gợi ý bước tiếp theo — người mới dùng biết ngay phải làm gì (spec A6.9)
    next_step: dict[str, str] | None = None
    if not data["n_documents"] and not data["n_profiles"]:
        next_step = {
            "title": "Bắt đầu: nạp tài liệu hoặc nghiên cứu khách hàng",
            "detail": "Hồ sơ này chưa có gì. Nạp tài liệu buổi làm việc, hoặc chạy Nghiên cứu để dựng hồ sơ khách hàng và bảng thuật ngữ.",
            "page": "documents",
            "label": "Mở tab Tài liệu",
        }
    elif not data["n_profiles"]:
        next_step = {
            "title": "Chạy Nghiên cứu để dựng hồ sơ khách hàng",
            "detail": "Có tài liệu rồi nhưng chưa có hồ sơ khách hàng. Kịch bản mock sẽ chung chung nếu thiếu bước này.",
            "page": "research",
            "label": "Mở tab Nghiên cứu",
        }
    elif not data["n_sessions"]:
        next_step = {
            "title": "Luyện buổi mock đầu tiên",
            "detail": f"Đã có {data['n_terms']} thuật ngữ và hồ sơ khách hàng. Sinh kịch bản 8–10 lượt để luyện dịch hai chiều.",
            "page": "mock",
            "label": "Mở tab Mock buổi dịch",
        }
    elif not data["n_verdicts"]:
        next_step = {
            "title": "Phản biện điểm để AI chấm đúng ý bạn",
            "detail": "Đã luyện nhưng chưa ghi nhận định nào. Nhận định có ghi lý do sẽ thành luật chấm cho các buổi sau.",
            "page": "mock",
            "label": "Mở buổi mock",
        }

    data["next_step"] = next_step
    return data
