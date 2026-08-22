"""Routes bảo mật §7: nhật ký dữ liệu gửi ra ngoài và vé đồng ý cho hồ sơ mật.

Input:  workspace_id (tuỳ chọn) để lọc nhật ký; ConsentGrant để cấp vé.
Output: danh sách nhật ký egress, kết quả cấp/thu hồi vé.

Đây là công cụ để chuyên gia TỰ KIỂM CHỨNG cam kết ở spec §7.1, không phải tin lời.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.db import get_conn
from backend.schemas import ConsentGrant, EgressLogOut
from backend.security import egress

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/egress-log", response_model=list[EgressLogOut])
def get_egress_log(
    workspace_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[EgressLogOut]:
    """Nhật ký mọi lần dữ liệu rời khỏi máy, mới nhất trước (spec A7.2)."""
    rows = egress.recent_log(workspace_id=workspace_id, limit=limit)
    return [
        EgressLogOut(
            id=int(r["id"]),
            workspace_id=r["workspace_id"],
            module=str(r["module"]),
            destination=str(r["destination"]),
            endpoint=r["endpoint"],
            n_chars=int(r["n_chars"]),
            summary=r["summary"],
            consented=bool(r["consented"]),
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


@router.post("/consent")
def grant_consent(payload: ConsentGrant) -> dict[str, object]:
    """Cấp vé đồng ý gửi dữ liệu ra ngoài cho một hồ sơ mật.

    `scope='session'` = đồng ý cho cả buổi làm việc (mặc định, để việc luyện tập không
    bị ngắt liên tục). `scope='once'` = chỉ một lần gửi.
    """
    ticket_id = egress.grant_consent(
        workspace_id=payload.workspace_id,
        scope=payload.scope,
        destination=payload.destination,
    )
    if not ticket_id:
        raise HTTPException(status_code=400, detail="Không cấp được vé đồng ý.")
    return {
        "ticket_id": ticket_id,
        "scope": payload.scope,
        "message": (
            "Đã đồng ý cho cả buổi làm việc này."
            if payload.scope == "session"
            else "Đã đồng ý cho một lần gửi."
        ),
    }


@router.delete("/consent/{workspace_id}")
def revoke_consent(workspace_id: int) -> dict[str, object]:
    """Thu hồi mọi vé đồng ý của một hồ sơ — dùng khi muốn siết lại giữa buổi."""
    n = egress.revoke_consent(workspace_id)
    return {"revoked": n, "message": f"Đã thu hồi {n} vé đồng ý."}


@router.get("/consent/{workspace_id}")
def consent_status(workspace_id: int) -> dict[str, object]:
    """Hồ sơ này có đang mật không, và đã có vé đồng ý còn hiệu lực chưa."""
    # Hồ sơ không tồn tại phải báo 404. Trả "không mật" ở đây sẽ gây hiểu nhầm
    # là đã kiểm tra xong và an toàn, trong khi thực ra chưa kiểm tra được gì.
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")

    confidential = egress.is_confidential(workspace_id)
    llm_ticket = egress.find_consent(workspace_id, "llm") if confidential else None
    search_ticket = egress.find_consent(workspace_id, "search") if confidential else None
    return {
        "workspace_id": workspace_id,
        "is_confidential": confidential,
        "has_llm_consent": llm_ticket is not None,
        "has_search_consent": search_ticket is not None,
    }
