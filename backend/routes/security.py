"""Routes bảo mật §7: nhật ký dữ liệu gửi ra ngoài và quyền cho hồ sơ mật.

Input:  workspace_id (tuỳ chọn) để lọc nhật ký; `consent_request_id` để cấp quyền.
Output: danh sách nhật ký egress, kết quả cấp/thu hồi quyền.

Đây là công cụ để chuyên gia TỰ KIỂM CHỨNG cam kết ở spec §7.1, không phải tin lời.

Điểm quan trọng khi cấp quyền: giao diện chỉ gửi lại `consent_request_id` mà máy chủ đã
phát ra cùng lỗi 409. Nó KHÔNG nói được sẽ cấp cho đích nào, nhà cung cấp nào, thao tác
nào — những thứ đó máy chủ đọc từ bản ghi của chính nó. Không có ràng buộc này thì giao
diện có thể (do lỗi hoặc cố ý) xin đồng ý một đằng rồi cấp quyền một nẻo.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.db import get_conn
from backend.schemas import ConsentGrant, EgressLogOut
from backend.security import gateway

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/egress-log", response_model=list[EgressLogOut])
def get_egress_log(
    workspace_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[EgressLogOut]:
    """Nhật ký mọi lần dữ liệu rời khỏi máy, mới nhất trước (spec A7.2)."""
    rows = gateway.recent_log(workspace_id=workspace_id, limit=limit)
    return [
        EgressLogOut(
            id=int(r["id"]),
            workspace_id=r["workspace_id"],
            module=str(r["module"]),
            destination=str(r["destination"]),
            provider=str(r["provider"] or ""),
            provider_label=gateway.PROVIDER_LABELS.get(
                str(r["provider"] or ""), str(r["provider"] or "—")
            ),
            endpoint=r["endpoint"],
            n_chars=int(r["n_chars"]),
            summary=r["summary"],
            status=str(r["status"] or "attempt_succeeded"),
            error_class=r["error_class"],
            operation_id=r["operation_id"],
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


@router.get("/egress-summary")
def egress_summary(workspace_id: int | None = Query(default=None)) -> dict[str, object]:
    """Số liệu tổng cho màn Bảo mật.

    Chỉ đếm được điều thật sự biết: đã CỐ gửi bao nhiêu lần. Một lần hỏng vì timeout có
    thể đã gửi xong body rồi mới hỏng lúc đọc — gọi nó là "chưa gửi" cũng sai như gọi nó
    là "gửi thành công". Vì vậy không có con số nào mang tên "đã gửi thành công".
    """
    rows = gateway.recent_log(workspace_id=workspace_id, limit=100_000)
    attempted = [r for r in rows if str(r["status"]).startswith("attempt")]
    ok = [r for r in attempted if r["status"] == "attempt_succeeded"]
    blocked = [r for r in rows if r["status"] == "blocked"]
    oversized = [r for r in attempted if int(r["n_chars"]) > 40_000]
    return {
        "n_attempted": len(attempted),
        "n_provider_ok": len(ok),
        "n_blocked": len(blocked),
        "n_oversized": len(oversized),
        "by_provider": {
            label: sum(
                1 for r in attempted
                if gateway.PROVIDER_LABELS.get(str(r["provider"] or ""), "") == label
            )
            for label in sorted(set(gateway.PROVIDER_LABELS.values()))
        },
        "note": (
            "“Đã cố gửi” đếm cả những lần nhà cung cấp báo lỗi: khi đó không kết luận được "
            "dữ liệu đã rời máy hay chưa, nên không được coi là chưa gửi."
        ),
    }


@router.post("/consent")
def grant_consent(payload: ConsentGrant) -> dict[str, object]:
    """Cấp quyền từ một yêu cầu đồng ý mà máy chủ đã phát ra trước đó.

    `scope='operation'` = chỉ thao tác này. `scope='session'` = cho tới khi đóng ứng dụng,
    và chỉ với đúng những dịch vụ mà thao tác này đã khai báo.
    """
    try:
        result = gateway.grant_from_pending(payload.consent_request_id, payload.scope)
    except gateway.EgressError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        **result,
        "message": (
            "Đã cho phép cho tới khi bạn đóng ứng dụng."
            if payload.scope == "session"
            else "Đã cho phép cho thao tác này."
        ),
    }


@router.delete("/consent/{workspace_id}")
def revoke_consent(workspace_id: int) -> dict[str, object]:
    """Thu hồi mọi quyền của một hồ sơ — dùng khi muốn siết lại giữa buổi."""
    n = gateway.revoke_consent(workspace_id)
    return {"revoked": n, "message": f"Đã thu hồi {n} quyền đã cấp."}


@router.get("/consent/{workspace_id}")
def consent_status(workspace_id: int) -> dict[str, object]:
    """Hồ sơ này có đang mật không, và đang cho phép những gì."""
    # Hồ sơ không tồn tại phải báo 404. Trả "không mật" ở đây sẽ gây hiểu nhầm
    # là đã kiểm tra xong và an toàn, trong khi thực ra chưa kiểm tra được gì.
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ khách hàng này.")

    state = gateway.consent_state(workspace_id)
    return {
        "workspace_id": workspace_id,
        "is_confidential": gateway.is_confidential(workspace_id),
        **state,
    }
