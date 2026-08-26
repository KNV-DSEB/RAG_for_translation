"""Routes Module 2 — phần nghiên cứu: chạy research và xem hồ sơ đã dựng.

Input:  tên khách hàng / đối tác / chủ đề buổi làm việc.
Output: hồ sơ các bên (mỗi trường kèm URL nguồn) + thống kê thuật ngữ.

Nghiên cứu là tác vụ dài (nhiều lệnh gọi LLM + tìm kiếm) nên route này chạy đồng bộ và
frontend hiển thị spinner. Hồ sơ mật sẽ trả 409 kèm xem trước ở lệnh gọi ra ngoài đầu tiên.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db import get_conn
from backend.routes._ops import OpContext, op_context
from backend.security import gateway, llm
from backend.research.orchestrator import run_full_research
from backend.research.profiler import FIELD_LABELS

router = APIRouter(prefix="/research", tags=["research"])


class ResearchRequest(BaseModel):
    workspace_id: int
    client_name: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    partner_names: list[str] = Field(default_factory=list)
    industry: str | None = None
    extra_notes: str | None = None
    engagement_id: int | None = None


def _require_workspace(workspace_id: int) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")


@router.post("/run")
def run(payload: ResearchRequest, op: OpContext = Depends(op_context)) -> dict[str, Any]:
    """Chạy một lần nghiên cứu hoàn chỉnh: hồ sơ khách hàng + bảng thuật ngữ."""
    _require_workspace(payload.workspace_id)

    steps: list[str] = []
    # ĐÂY là thao tác khiến consent phải gắn với thao tác chứ không gắn với từng lệnh gọi:
    # một lần chạy gọi ra ngoài hơn chục lần. Hỏi ý kiến từng lệnh thì giao diện thử lại
    # cả request, các lệnh đã chạy sẽ chạy lại, và lần chạy không bao giờ kết thúc.
    #
    # Cả hai con số đều lấy từ cấu hình đang chạy, không đặt số mới:
    #   search  = hạn mức truy vấn của `QueryBudget`
    #   llm     = 1 lập kế hoạch + 1 tổng hợp hồ sơ + 3 trích thuật ngữ
    with gateway.operation(
        payload.workspace_id,
        kind="research.run",
        declares=[
            gateway.OperationDeclaration(
                "search", gateway.PROVIDER_DDGS,
                unit_calls=settings.max_search_queries, retries_each=2,
            ),
            gateway.OperationDeclaration(
                "llm", gateway.PROVIDER_GEMINI,
                unit_calls=5, retries_each=llm.retry_ceiling("quality"),
            ),
        ],
        fingerprint=op.fingerprint,
        resume_id=op.resume_id,
    ):
        result = run_full_research(
            workspace_id=payload.workspace_id,
            client_name=payload.client_name.strip(),
            partner_names=[p.strip() for p in payload.partner_names if p.strip()],
            topic=payload.topic.strip(),
            industry=payload.industry,
            extra_notes=payload.extra_notes,
            engagement_id=payload.engagement_id,
            on_progress=steps.append,
        )

    return {
        "research_run_id": result.research_run_id,
        "status": result.status,
        "queries_used": result.queries_used,
        "n_queries": len(result.queries_used),
        "n_sources": result.n_sources,
        "n_terms_total": result.n_terms_total,
        "n_terms_added": result.n_terms_added,
        "n_terms_human": result.n_terms_human,
        "n_conflicts": result.n_conflicts,
        "not_found_notes": result.not_found_notes,
        "ambiguity_warning": result.ambiguity_warning,
        "warnings": result.warnings,
        "steps": steps,
        "entities": [
            {
                "entity_name": entity.entity_name,
                "entity_role": entity.entity_role,
                "fields": [
                    {
                        "field_key": f.field_key,
                        "label": f.label,
                        "value": f.value,
                        "source_urls": f.source_urls,
                        "is_inference": f.is_inference,
                    }
                    for f in entity.fields
                ],
            }
            for entity in result.entities
        ],
    }


@router.get("/profiles")
def get_profiles(workspace_id: int = Query(...)) -> list[dict[str, Any]]:
    """Hồ sơ đã dựng của hồ sơ khách hàng, lấy lần chạy mới nhất cho mỗi bên."""
    _require_workspace(workspace_id)

    with get_conn() as conn:
        profiles = conn.execute(
            """
            SELECT p.* FROM profiles p
            WHERE p.workspace_id = ?
              AND p.id = (
                  SELECT MAX(p2.id) FROM profiles p2
                  WHERE p2.workspace_id = p.workspace_id AND p2.entity_name = p.entity_name
              )
            ORDER BY CASE p.entity_role WHEN 'client' THEN 0 ELSE 1 END, p.entity_name
            """,
            (workspace_id,),
        ).fetchall()

        output: list[dict[str, Any]] = []
        for profile in profiles:
            fields = conn.execute(
                "SELECT * FROM profile_fields WHERE profile_id = ? ORDER BY id",
                (int(profile["id"]),),
            ).fetchall()

            field_items: list[dict[str, Any]] = []
            for item in fields:
                sources = conn.execute(
                    """
                    SELECT url, title, published_at, reachable
                    FROM profile_sources WHERE profile_field_id = ?
                    """,
                    (int(item["id"]),),
                ).fetchall()
                field_items.append(
                    {
                        "id": int(item["id"]),
                        "field_key": str(item["field_key"]),
                        "label": FIELD_LABELS.get(str(item["field_key"]), str(item["field_key"])),
                        "value": item["value"],
                        "has_source": bool(item["has_source"]),
                        "is_expert_edited": bool(item["is_expert_edited"]),
                        "sources": [dict(s) for s in sources],
                    }
                )

            output.append(
                {
                    "id": int(profile["id"]),
                    "entity_name": str(profile["entity_name"]),
                    "entity_role": str(profile["entity_role"]),
                    "created_at": str(profile["created_at"]),
                    "fields": field_items,
                }
            )
    return output


@router.patch("/profile-fields/{field_id}")
def edit_profile_field(field_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Sửa tay một trường hồ sơ. Đánh dấu để lần nghiên cứu sau không ghi đè (spec A2.12)."""
    value = str(payload.get("value", "")).strip()
    if not value:
        raise HTTPException(status_code=400, detail="Nội dung đang để trống.")

    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE profile_fields
            SET value = ?, is_expert_edited = 1
            WHERE id = ?
            """,
            (value, field_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Không tìm thấy trường hồ sơ này.")
    return {"field_id": field_id, "value": value, "is_expert_edited": True}


@router.get("/runs")
def list_runs(workspace_id: int = Query(...), limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    """Lịch sử các lần nghiên cứu: đã dùng truy vấn nào, thu được bao nhiêu nguồn."""
    _require_workspace(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM research_runs WHERE workspace_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("queries_used", "partner_names"):
            try:
                item[key] = json.loads(str(item.get(key) or "[]"))
            except json.JSONDecodeError:
                item[key] = []
        items.append(item)
    return items
