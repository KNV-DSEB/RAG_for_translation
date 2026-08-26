"""Cửa DUY NHẤT để dữ liệu rời khỏi máy này.

Vào:  một `EgressRequest` mô tả sẽ gửi gì, tới đâu, cho nhà cung cấp nào.
Ra:   kết quả provider trả về. Kèm theo: một dòng nhật ký, một lần trừ ngân sách.

Vì sao là `execute()` chứ không phải `with`
------------------------------------------
Bản trước dùng context manager `egress()` bọc quanh lệnh gọi mạng. Cái bọc thì luôn có
thể *không* bọc — không gì ngăn một module gọi thẳng `edge_tts.Communicate(...)`. Nên
gateway ĐÍCH THÂN gọi provider: muốn ra ngoài thì phải đi qua đây, không có đường khác.

Ba tầng canh, cả ba đều tự động:
  C1a (quét AST)   chỉ `providers/` được import thư viện mạng
  C1b (quét AST)   chỉ tệp này được import `providers/`
  C1c (runtime)    `execute()` ngoài `operation()` bị chặn trước khi chạm mạng

Đơn vị đồng ý là THAO TÁC, không phải lệnh gọi
----------------------------------------------
Một lần `/research/run` gọi ra ngoài tới ~13 lần. Hỏi ý kiến từng lệnh gọi thì không
chạy nổi: giao diện thử lại cả request, nên các lệnh gọi đã chạy sẽ chạy lại và đốt
hết vé của chúng. Vì vậy chuyên gia đồng ý cho MỘT THAO TÁC — biết trước dịch vụ nào
và tối đa bao nhiêu lần — còn nhật ký vẫn ghi RIÊNG từng lệnh gọi.

Chỗ này yếu hơn "mỗi lần gửi một vé": thao tác nhiều lệnh gọi không hiện trước được
nội dung, vì truy vấn tìm kiếm do bước đầu sinh ra. Hộp thoại nói thẳng điều đó.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Iterator, Literal

from backend.db import get_conn

Destination = Literal["llm", "search", "tts"]
Status = Literal["blocked", "attempt_succeeded", "attempt_failed"]

# Trần payload. Vượt ngưỡng này gần như chắc chắn là đang gửi CẢ tài liệu thay vì
# các đoạn đã truy hồi — đúng thứ spec §7 cấm.
MAX_PAYLOAD_CHARS = 60_000

# Thao tác sống đủ lâu để chuyên gia đọc hộp thoại rồi bấm đồng ý, không lâu hơn.
OPERATION_TTL_MIN = 15
PENDING_TTL_MIN = 10
# Lưới an toàn cho phiên chạy dài. Quyền phiên còn bị xoá lúc khởi động (xem db._migrate)
# nên "cho tới khi đóng ứng dụng" đúng nghĩa đen.
SESSION_TTL_HOURS = 8

# Tên nhà cung cấp. Gateway công bố ở đây vì nơi khai báo thao tác cần chúng, mà C1b
# cấm module khác import `providers/` — kể cả chỉ để lấy một hằng chuỗi.
PROVIDER_GEMINI = "gemini"
PROVIDER_DDGS = "ddgs"
PROVIDER_EDGE = "edge"
PROVIDER_GTTS = "gtts"

# Tên hiện trên hộp thoại và trong nhật ký.
PROVIDER_LABELS = {
    "gemini": "Gemini (Google)",
    "ddgs": "DuckDuckGo",
    "edge": "edge-tts (Microsoft)",
    "gtts": "gTTS (Google)",
}
DESTINATION_LABELS = {
    "llm": "mô hình ngôn ngữ",
    "search": "tìm kiếm web",
    "tts": "đọc lời thoại",
}

# Đường dẫn chứ không phải hàm: provider nạp lười lúc gọi. Giữ hàm trực tiếp ở đây sẽ
# kéo cả bốn thư viện mạng vào lúc khởi động, vỡ ngân sách RAM 7,8 GB của máy.
_REGISTRY: dict[tuple[str, str], Any] = {
    ("llm", "gemini"): "backend.security.providers.gemini:generate",
    ("search", "ddgs"): "backend.security.providers.ddgs:search",
    ("tts", "edge"): "backend.security.providers.tts_edge:synthesize",
    ("tts", "gtts"): "backend.security.providers.tts_gtts:synthesize",
}


# ============================== Lỗi ==============================


class EgressError(RuntimeError):
    """Gốc cho mọi lỗi của cửa egress."""


class PayloadTooLarge(EgressError):
    """Định gửi nhiều hơn trần cho phép."""


class NoActiveOperation(EgressError):
    """Gọi `execute()` khi không có thao tác nào mở — lỗi lập trình, không phải lỗi người dùng."""


class OperationBudgetExceeded(EgressError):
    """Thao tác đã dùng hết số lệnh gọi mà chuyên gia được cho biết trước."""


class ConsentRequired(EgressError):
    """Hồ sơ mật, chưa có quyền. Route bắt lỗi này và trả 409 kèm bản xem trước."""

    def __init__(self, preview: "OperationPreview") -> None:
        super().__init__(preview.headline)
        self.preview = preview


# ============================== Kiểu dữ liệu ==============================


@dataclass(frozen=True)
class OperationDeclaration:
    """Khai báo trước: thao tác này sẽ gọi ai, tối đa bao nhiêu lần.

    `max_calls` là luật MÁY thực thi. Để nó thành câu chữ trên giao diện thôi thì vòng
    lặp chạy 80 lần vẫn hợp lệ trong khi hộp thoại ghi 8 — đúng loại lỗi "nhãn mạnh hơn
    thứ code bảo đảm" mà cả đợt sửa này nhắm vào.

    Hai con số, vì chúng trả lời hai câu hỏi khác nhau:

      `unit_calls`    bao nhiêu NỘI DUNG KHÁC NHAU sẽ rời khỏi máy. Đây là con số chuyên
                      gia cần: nó đo mức lộ dữ liệu.
      `retries_each`  mỗi nội dung có thể được gửi lại bao nhiêu lần nữa khi nhà cung cấp
                      giới hạn tần suất hoặc hết hạn mức ngày phải đổi model dự phòng.
                      Gửi lại CÙNG một nội dung cho CÙNG một nhà cung cấp không làm lộ
                      thêm gì — nhưng vẫn phải đếm, vì cái chặn vòng lặp chạy loạn là
                      số lần gọi mạng thật.

    `max_calls` = tích của hai số trên, và là thứ duy nhất được thực thi. Cả câu chữ trên
    hộp thoại lẫn luật chặn đều suy ra từ đây, nên chúng không thể lệch nhau.
    """

    destination: Destination
    provider: str
    unit_calls: int
    retries_each: int = 0

    @property
    def max_calls(self) -> int:
        return self.unit_calls * (self.retries_each + 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "provider": self.provider,
            "unit_calls": self.unit_calls,
            "max_calls": self.max_calls,
            "provider_label": PROVIDER_LABELS.get(self.provider, self.provider),
            "destination_label": DESTINATION_LABELS.get(self.destination, self.destination),
        }


@dataclass
class Operation:
    """Một lần thao tác người dùng bấm."""

    id: str
    workspace_id: int | None
    kind: str
    fingerprint: str
    declares: tuple[OperationDeclaration, ...]
    resumed: bool = False


@dataclass
class EgressRequest:
    """Một lần gửi dữ liệu ra ngoài.

    `operation_id` KHÔNG phải tham số đầu vào — gateway tự đóng dấu từ thao tác đang mở.
    Cái không đặt được thì không đặt sai được.
    """

    module: str
    destination: Destination
    provider: str
    payload_text: str
    summary: str
    workspace_id: int | None = None
    endpoint: str = ""
    n_chars: int = 0
    operation_id: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if not self.n_chars:
            self.n_chars = len(self.payload_text)


@dataclass(frozen=True)
class OperationPreview:
    """Thứ chuyên gia thấy trước khi quyết định cho hay không cho."""

    consent_request_id: str
    operation_id: str
    workspace_id: int
    workspace_name: str
    operation_kind: str
    declares: tuple[OperationDeclaration, ...]
    payload_excerpt: str
    payload_known: bool
    payload_truncated: bool
    n_chars: int

    @property
    def headline(self) -> str:
        parts = [
            f"{d.unit_calls} lần tới {PROVIDER_LABELS.get(d.provider, d.provider)}"
            for d in self.declares
        ]
        return (
            f"Hồ sơ “{self.workspace_name}” đang ở chế độ mật — cần bạn đồng ý trước khi "
            "gửi dữ liệu ra ngoài: tối đa " + ", ".join(parts) + "."
        )

    @property
    def scope_note(self) -> str:
        """Câu mô tả phạm vi, SINH RA TỪ `declares`.

        Không nhận câu viết tay: chính sách và câu chữ phải có đúng một nguồn, nếu không
        chúng sẽ lệch nhau đúng vào lúc quan trọng nhất.
        """
        parts = []
        for d in self.declares:
            label = PROVIDER_LABELS.get(d.provider, d.provider)
            piece = f"tối đa {d.unit_calls} lần tới {label}"
            if d.max_calls > d.unit_calls:
                # Nói rõ vì sao trần kỹ thuật lớn hơn: gửi LẠI cùng nội dung khi bị giới
                # hạn tần suất hoặc phải đổi model dự phòng. Giấu con số này đi thì luật
                # chặn và câu chữ lệch nhau — đúng thứ đang phải sửa.
                piece += (
                    f" (gửi lại cùng nội dung đó tối đa {d.retries_each} lần nếu nhà cung cấp "
                    f"bận hoặc hết hạn mức, nên trần kỹ thuật là {d.max_calls} lượt)"
                )
            parts.append(piece)
        note = "Thao tác này sẽ gửi dữ liệu ra ngoài: " + ", ".join(parts) + "."
        if not self.payload_known:
            note += (
                " Nội dung từng lần do các bước bên trong sinh ra nên chưa hiện được ở đây — "
                "mọi lần gửi đều được ghi vào Nhật ký Bảo mật để bạn soi lại."
            )
        return note

    def as_dict(self) -> dict[str, Any]:
        return {
            "consent_request_id": self.consent_request_id,
            "operation_id": self.operation_id,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "operation_kind": self.operation_kind,
            "declares": [d.as_dict() for d in self.declares],
            "scope_note": self.scope_note,
            "payload_excerpt": self.payload_excerpt,
            "payload_known": self.payload_known,
            "payload_truncated": self.payload_truncated,
            "n_chars": self.n_chars,
        }


# ============================== Vân tay request ==============================


def fingerprint(
    *, method: str, route: str, body: Any = None, query: dict[str, Any] | None = None
) -> str:
    """Vân tay của MỘT LẦN thao tác.

    Không có nó, quyền cấp cho "nghiên cứu khách hàng A" dùng lại được cho khách hàng B:
    cùng hồ sơ, cùng loại thao tác, mọi kiểm tra khác đều lọt. Ta đã không tin giao diện
    khai `destination`/`provider` — thì cũng không được ngầm tin nó rằng lần thử lại vẫn
    là request cũ.

    Chạy được vì `web/js/api.js` thử lại bằng ĐÚNG `options` cũ, nên body giống hệt
    từng byte. Đó là tính chất của việc gom retry về một chỗ, không phải may mắn.
    """
    canonical_body = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    canonical_query = json.dumps(
        dict(sorted((query or {}).items())), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    raw = f"{method.upper()}\n{route}\n{canonical_body}\n{canonical_query}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================== Truy vấn phụ trợ ==============================


def _workspace(workspace_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, is_confidential FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    return dict(row) if row else None


def is_confidential(workspace_id: int | None) -> bool:
    """Hồ sơ có đang bật cờ mật không. Không thuộc hồ sơ nào thì coi như không mật."""
    if workspace_id is None:
        return False
    ws = _workspace(workspace_id)
    return bool(ws and ws["is_confidential"])


def _resolve(destination: str, provider: str):
    """Lấy hàm provider. Nạp lười để không kéo thư viện mạng vào lúc khởi động."""
    entry = _REGISTRY.get((destination, provider))
    if entry is None:
        raise EgressError(
            f"Không có nhà cung cấp nào đăng ký cho ({destination}, {provider}). "
            "Thêm dịch vụ mạng mới thì phải đăng ký ở đây — đó là điều kiện để nó đi qua cửa."
        )
    if callable(entry):
        return entry
    module_path, _, func_name = entry.partition(":")
    return getattr(import_module(module_path), func_name)


def _log(req: EgressRequest, *, status: Status, error_class: str | None = None) -> None:
    """Ghi một dòng nhật ký cho MỘT lệnh gọi.

    `summary` không bao giờ được chứa API key — xem `security/llm.py` khi phân loại lỗi.
    """
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO egress_log
                (workspace_id, module, destination, provider, endpoint, n_chars,
                 summary, consented, status, error_class, operation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.workspace_id, req.module, req.destination, req.provider, req.endpoint,
                req.n_chars, req.summary,
                1 if status != "blocked" else 0,   # cột cũ, giữ cho dữ liệu lịch sử đọc được
                status, error_class, req.operation_id or None,
            ),
        )


# ============================== Quyền ==============================


def _has_grant(workspace_id: int, operation_id: str, destination: str, provider: str) -> bool:
    """Quyền riêng cho thao tác này, HOẶC quyền cho cả phiên.

    Hai nhánh là lý do `operations` phải tách khỏi `consent_grants`: gộp chung thì quyền
    phiên (`operation_id IS NULL`) làm việc resume trượt, và nút "cho tới khi đóng ứng
    dụng" không làm được đúng điều nó ghi trên mặt.
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM consent_grants
            WHERE workspace_id = ? AND destination = ? AND provider = ?
              AND expires_at > datetime('now')
              AND (operation_id = ? OR operation_id IS NULL)
            LIMIT 1
            """,
            (workspace_id, destination, provider, operation_id),
        ).fetchone()
    return row is not None


def _missing_declares(op: Operation) -> tuple[OperationDeclaration, ...]:
    """Những (đích, nhà cung cấp) mà thao tác này khai báo nhưng chưa có quyền."""
    if op.workspace_id is None:
        return ()
    return tuple(
        d for d in op.declares
        if not _has_grant(op.workspace_id, op.id, d.destination, d.provider)
    )


def grant_from_pending(consent_request_id: str, scope: str) -> dict[str, Any]:
    """Cấp quyền từ challenge do CHÍNH máy chủ ghi trước đó.

    Giao diện chỉ gửi lại `consent_request_id` + `scope`. Nó không nói được sẽ cấp cho
    đích nào, nhà cung cấp nào, thao tác nào — những thứ đó đọc từ bản ghi của máy chủ.
    """
    if scope not in ("operation", "session"):
        raise EgressError("Phạm vi đồng ý phải là 'operation' hoặc 'session'.")

    with get_conn() as conn:
        pending = conn.execute(
            """
            SELECT p.id, p.operation_id, p.workspace_id, o.declares
            FROM pending_consents p JOIN operations o ON o.id = p.operation_id
            WHERE p.id = ? AND p.used = 0 AND p.expires_at > datetime('now')
            """,
            (consent_request_id,),
        ).fetchone()
        if pending is None:
            raise EgressError(
                "Yêu cầu đồng ý này không còn hiệu lực (đã dùng, hết hạn, hoặc không tồn tại). "
                "Hãy thao tác lại từ đầu."
            )

        declares = json.loads(str(pending["declares"]))
        ttl = (
            f"+{SESSION_TTL_HOURS} hours" if scope == "session" else f"+{OPERATION_TTL_MIN} minutes"
        )
        operation_id = None if scope == "session" else pending["operation_id"]

        for item in declares:
            conn.execute(
                """
                INSERT INTO consent_grants
                    (workspace_id, operation_id, scope, destination, provider, expires_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', ?))
                """,
                (pending["workspace_id"], operation_id, scope,
                 item["destination"], item["provider"], ttl),
            )
        conn.execute("UPDATE pending_consents SET used = 1 WHERE id = ?", (consent_request_id,))

    return {
        "operation_id": pending["operation_id"],
        "workspace_id": pending["workspace_id"],
        "scope": scope,
        "n_grants": len(declares),
    }


def revoke_consent(workspace_id: int) -> int:
    """Thu hồi mọi quyền còn hiệu lực của một hồ sơ."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM consent_grants WHERE workspace_id = ?", (workspace_id,))
    return int(cur.rowcount or 0)


def consent_state(workspace_id: int) -> dict[str, Any]:
    """Hồ sơ này đang cho phép những gì."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT scope, destination, provider, operation_id, granted_at, expires_at
            FROM consent_grants
            WHERE workspace_id = ? AND expires_at > datetime('now')
            ORDER BY granted_at DESC
            """,
            (workspace_id,),
        ).fetchall()
    return {"grants": [dict(r) for r in rows], "n_active": len(rows)}


# ============================== Thao tác ==============================


_ACTIVE: ContextVar[Operation | None] = ContextVar("gateway_active_operation", default=None)


def _open_or_resume(
    *, workspace_id: int | None, kind: str, declares: tuple[OperationDeclaration, ...],
    fp: str, resume_id: str | None,
) -> Operation:
    """Vào lại thao tác cũ nếu `resume_id` qua đủ SÁU kiểm tra, ngược lại đúc thao tác mới.

    Trượt bất kỳ kiểm tra nào thì coi như không có `resume_id` — hỏng theo hướng hỏi lại
    chuyên gia, không theo hướng cho qua.
    """
    if resume_id:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, workspace_id, operation_kind, request_fingerprint, declares
                FROM operations
                WHERE id = ?                              --  1. tồn tại
                  AND operation_kind = ?                  --  3. đúng loại thao tác
                  AND request_fingerprint = ?             --  4. đúng LẦN thao tác đó
                  AND expires_at > datetime('now')        --  5. chưa hết hạn
                  AND completed_at IS NULL                --  6. chưa chạy xong
                """,
                (resume_id, kind, fp),
            ).fetchone()
        #  2. đúng hồ sơ — so ngoài SQL để `NULL = NULL` không đánh lừa
        if row is not None and row["workspace_id"] == workspace_id:
            return Operation(
                id=str(row["id"]), workspace_id=workspace_id, kind=kind,
                fingerprint=fp, declares=declares, resumed=True,
            )

    op_id = uuid.uuid4().hex
    payload = json.dumps([d.as_dict() for d in declares], ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO operations
                (id, workspace_id, operation_kind, request_fingerprint, declares, expires_at)
            VALUES (?, ?, ?, ?, ?, datetime('now', ?))
            """,
            (op_id, workspace_id, kind, fp, payload, f"+{OPERATION_TTL_MIN} minutes"),
        )
        for d in declares:
            conn.execute(
                """
                INSERT OR IGNORE INTO operation_calls
                    (operation_id, destination, provider, allowed_calls)
                VALUES (?, ?, ?, ?)
                """,
                (op_id, d.destination, d.provider, d.max_calls),
            )
    return Operation(
        id=op_id, workspace_id=workspace_id, kind=kind, fingerprint=fp, declares=declares
    )


def _make_pending(op: Operation, payload_preview: str | None) -> OperationPreview:
    """Ghi challenge rồi dựng bản xem trước cho hộp thoại."""
    request_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO pending_consents (id, operation_id, workspace_id, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
            """,
            (request_id, op.id, op.workspace_id, f"+{PENDING_TTL_MIN} minutes"),
        )
    ws = _workspace(op.workspace_id) if op.workspace_id else None
    text = payload_preview or ""
    return OperationPreview(
        consent_request_id=request_id,
        operation_id=op.id,
        workspace_id=op.workspace_id or 0,
        workspace_name=str(ws["name"]) if ws else "(không thuộc hồ sơ nào)",
        operation_kind=op.kind,
        declares=op.declares,
        # Hiện ĐỦ, không cắt. Trần 60k đã chặn payload khổng lồ nên khối cuộn được là đủ;
        # cắt bớt rồi bảo "đây là chính xác nội dung sẽ gửi" là nói dối.
        payload_excerpt=text,
        payload_known=bool(payload_preview),
        payload_truncated=False,
        n_chars=len(text),
    )


@contextmanager
def operation(
    workspace_id: int | None,
    *,
    kind: str,
    declares: list[OperationDeclaration] | tuple[OperationDeclaration, ...],
    fingerprint: str,
    resume_id: str | None = None,
    payload_preview: str | None = None,
) -> Iterator[Operation]:
    """Mở một thao tác. MỌI lệnh gọi ra ngoài phải nằm trong một cái như thế này.

    Hỏi ý kiến ĐÚNG MỘT LẦN ở đây, cho toàn bộ `declares` — không hỏi lại giữa chừng dù
    bên trong gọi mười ba lần.
    """
    declared = tuple(declares)
    op = _open_or_resume(
        workspace_id=workspace_id, kind=kind, declares=declared,
        fp=fingerprint, resume_id=resume_id,
    )

    if is_confidential(workspace_id):
        missing = _missing_declares(op)
        if missing:
            preview = _make_pending(op, payload_preview)
            for d in missing:
                blocked = EgressRequest(
                    module=kind, destination=d.destination, provider=d.provider,
                    payload_text="", summary=f"Bị chặn: hồ sơ mật chưa cho phép {kind}",
                    workspace_id=workspace_id, endpoint=f"{d.provider}:(chưa gọi)",
                )
                # Đóng dấu thao tác cả cho dòng bị chặn. Thiếu nó thì chuyên gia không nối
                # được "lần bị chặn này" với "lần tôi bấm đồng ý" khi soi lại nhật ký —
                # mà đó chính là việc màn Bảo mật sinh ra để làm.
                blocked.operation_id = op.id
                _log(blocked, status="blocked")
            raise ConsentRequired(preview)

    token = _ACTIVE.set(op)
    try:
        yield op
    finally:
        _ACTIVE.reset(token)
        with get_conn() as conn:
            conn.execute(
                "UPDATE operations SET completed_at = datetime('now') WHERE id = ?", (op.id,)
            )


def active_operation() -> Operation | None:
    return _ACTIVE.get()


# ============================== Ngân sách ==============================


def _spend_budget(op: Operation, req: EgressRequest) -> None:
    """Trừ một lượt. Tăng đếm bằng MỘT câu lệnh có điều kiện, không đọc-rồi-ghi.

    Đọc rồi ghi thì hai lệnh gọi song song cùng thấy `used < allowed` và cùng lọt.
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE operation_calls SET used_calls = used_calls + 1
            WHERE operation_id = ? AND destination = ? AND provider = ?
              AND used_calls < allowed_calls
            """,
            (op.id, req.destination, req.provider),
        )
        if cur.rowcount:
            return
        row = conn.execute(
            """
            SELECT allowed_calls, used_calls FROM operation_calls
            WHERE operation_id = ? AND destination = ? AND provider = ?
            """,
            (op.id, req.destination, req.provider),
        ).fetchone()

    label = PROVIDER_LABELS.get(req.provider, req.provider)
    if row is None:
        raise OperationBudgetExceeded(
            f"Thao tác “{op.kind}” không khai báo trước là sẽ gọi {label}, nên không được gọi. "
            "Đây là lỗi lập trình: thêm nó vào `declares` của thao tác."
        )
    raise OperationBudgetExceeded(
        f"Thao tác “{op.kind}” đã dùng hết {row['allowed_calls']} lượt gọi {label} mà bạn "
        "đã cho phép, nên dừng tại đây. Phần việc đã xong vẫn được giữ nguyên."
    )


# ============================== Điểm ra ==============================


def execute(req: EgressRequest, **kwargs: Any) -> Any:
    """Gọi nhà cung cấp. Đây là hàm DUY NHẤT trong toàn bộ mã nguồn chạm tới mạng.

    Bốn cửa chặn trước khi chạm mạng, trượt cửa nào cũng ghi `blocked`.
    """
    # Cửa 0 — RUNTIME. Không có thao tác đang mở thì không có đường ra.
    # Ba cửa dưới là chính sách; cửa này là thứ chặn lỗi thật sự dễ mắc: quên bọc.
    op = _ACTIVE.get()
    if op is None:
        _log(req, status="blocked", error_class="NoActiveOperation")
        raise NoActiveOperation(
            f"`{req.module}` gọi ra ngoài mà không mở `gateway.operation(...)`. "
            "Mọi lệnh gọi mạng phải nằm trong một thao tác đã được chuyên gia cho phép."
        )
    req.operation_id = op.id
    if req.workspace_id is None:
        req.workspace_id = op.workspace_id

    if req.n_chars > MAX_PAYLOAD_CHARS:
        _log(req, status="blocked", error_class="PayloadTooLarge")
        raise PayloadTooLarge(
            f"Mô-đun '{req.module}' định gửi {req.n_chars} ký tự (trần {MAX_PAYLOAD_CHARS}). "
            "Chỉ được gửi các đoạn ngữ cảnh đã truy hồi, không gửi toàn bộ tài liệu."
        )

    if op.workspace_id is not None and is_confidential(op.workspace_id):
        if not _has_grant(op.workspace_id, op.id, req.destination, req.provider):
            _log(req, status="blocked", error_class="ConsentRequired")
            raise ConsentRequired(_make_pending(op, req.payload_text))

    try:
        _spend_budget(op, req)
    except OperationBudgetExceeded:
        # Docstring trên nói "trượt cửa nào cũng ghi blocked" — thì phải ghi thật.
        # Thiếu dòng này, một thao tác bị chặn vì vượt ngân sách sẽ không để lại dấu vết
        # nào trong màn Bảo mật, và chuyên gia không biết hệ thống vừa ngăn cái gì.
        _log(req, status="blocked", error_class="OperationBudgetExceeded")
        raise

    try:
        result = _resolve(req.destination, req.provider)(**kwargs)
    except Exception as exc:
        # ĐÃ cố gửi. Không kết luận được dữ liệu đã đi hay chưa — body có thể gửi xong rồi
        # mới timeout lúc đọc. Nên vẫn tính là "đã cố gửi ra ngoài", chỉ không gọi là thành công.
        _log(req, status="attempt_failed", error_class=type(exc).__name__)
        raise
    _log(req, status="attempt_succeeded")
    return result


# ============================== Đọc nhật ký ==============================


def recent_log(workspace_id: int | None = None, limit: int = 300) -> list[dict[str, Any]]:
    sql = """
        SELECT id, workspace_id, module, destination, provider, endpoint, n_chars,
               summary, status, error_class, operation_id, created_at
        FROM egress_log
    """
    params: tuple[Any, ...] = ()
    if workspace_id is not None:
        sql += " WHERE workspace_id = ?"
        params = (workspace_id,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
