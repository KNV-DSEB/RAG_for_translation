"""⭐ CỬA DUY NHẤT để dữ liệu rời khỏi máy.

Input:  một `EgressRequest` mô tả sẽ gửi gì, đi đâu, thuộc module nào.
Output: ghi một dòng vào `egress_log`; nếu hồ sơ đang bật cờ mật mà chưa có vé đồng ý
        thì ném `ConsentRequired` mang theo bản xem trước để giao diện hỏi chuyên gia.

Theo spec §7.1 toàn hệ thống có ĐÚNG BA đường ra:
    E1 — gọi LLM (Gemini)
    E2 — truy vấn tìm kiếm web
    E3 — đọc lời thoại thành giọng nói (edge-tts gửi văn bản tới Microsoft, gTTS tới Google)

Cả ba BẮT BUỘC đi qua module này. Không được gọi trực tiếp SDK ở nơi khác — đó là lý do
dự án không dùng LangChain (framework che giấu lệnh gọi thì không bảo đảm được điều này).

Ghi chú về E3: ban đầu spec chỉ liệt kê hai đường ra vì tưởng TTS chạy local (Coqui). Khi
đổi sang edge-tts thì nó thành một đường ra thật — lời thoại chứa tên khách hàng, số liệu
dự án, tên địa phương. Bỏ sót chỗ này nghĩa là hồ sơ mật bị gửi dữ liệu đi mà không hỏi.
Lần đọc lấy từ CACHE thì KHÔNG tính là egress vì không có lệnh gọi mạng nào.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterator, Literal

from backend.db import get_conn

Destination = Literal["llm", "search", "tts"]

# Trần cứng để bắt lỗi lập trình: nếu payload lớn cỡ này thì gần như chắc chắn ai đó
# đang gửi cả tài liệu thay vì các đoạn ngữ cảnh đã truy hồi (vi phạm spec A7.3).
MAX_PAYLOAD_CHARS = 60_000

# Vé đồng ý phạm vi 'session' sống bao lâu.
CONSENT_SESSION_HOURS = 8


class EgressError(RuntimeError):
    """Lỗi chung của tầng egress."""


class PayloadTooLarge(EgressError):
    """Payload vượt trần — chặn để không vô tình gửi cả tài liệu ra ngoài."""


@dataclass(frozen=True)
class EgressPreview:
    """Bản xem trước hiện cho chuyên gia duyệt khi hồ sơ đang bật cờ mật."""

    workspace_id: int
    workspace_name: str
    module: str
    destination: Destination
    endpoint: str
    n_chars: int
    summary: str
    payload_excerpt: str

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "module": self.module,
            "destination": self.destination,
            "endpoint": self.endpoint,
            "n_chars": self.n_chars,
            "summary": self.summary,
            "payload_excerpt": self.payload_excerpt,
        }


class ConsentRequired(EgressError):
    """Hồ sơ mật, chưa có vé đồng ý. Route bắt lỗi này và trả 409 kèm preview."""

    def __init__(self, preview: EgressPreview) -> None:
        super().__init__(
            f"Hồ sơ '{preview.workspace_name}' đang bật chế độ mật — "
            f"cần bạn đồng ý trước khi gửi {preview.n_chars} ký tự tới {preview.destination}."
        )
        self.preview = preview


@dataclass
class EgressRequest:
    """Mô tả một lần gửi dữ liệu ra ngoài."""

    module: str
    destination: Destination
    payload_text: str
    summary: str
    workspace_id: int | None = None
    endpoint: str = ""
    # Số ký tự thật sự gửi đi. Tính từ payload nếu không truyền vào.
    n_chars: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.n_chars:
            self.n_chars = len(self.payload_text)


def _now() -> datetime:
    return datetime.now()


def _workspace(workspace_id: int) -> dict[str, object] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, is_confidential FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    return dict(row) if row else None


def is_confidential(workspace_id: int | None) -> bool:
    """Hồ sơ có đang bật cờ mật không. Không có workspace thì coi như không mật."""
    if workspace_id is None:
        return False
    ws = _workspace(workspace_id)
    return bool(ws and ws["is_confidential"])


def find_consent(workspace_id: int, destination: Destination) -> dict[str, object] | None:
    """Tìm vé đồng ý còn hiệu lực. Vé `destination` NULL áp dụng cho mọi đích."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM consent_tickets
            WHERE workspace_id = ?
              AND (destination IS NULL OR destination = ?)
              AND (expires_at IS NULL OR expires_at > datetime('now'))
              AND (scope = 'session' OR used = 0)
            ORDER BY granted_at DESC
            LIMIT 1
            """,
            (workspace_id, destination),
        ).fetchone()
    return dict(row) if row else None


def grant_consent(
    workspace_id: int,
    scope: Literal["session", "once"] = "session",
    destination: Destination | None = None,
) -> int:
    """Cấp vé đồng ý. `session` dùng cho cả buổi làm việc, `once` chỉ một lần."""
    expires_at: str | None = None
    if scope == "session":
        expires_at = (_now() + timedelta(hours=CONSENT_SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO consent_tickets (workspace_id, scope, destination, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (workspace_id, scope, destination, expires_at),
        )
        return int(cur.lastrowid or 0)


def revoke_consent(workspace_id: int) -> int:
    """Thu hồi mọi vé của một hồ sơ (dùng khi chuyên gia muốn siết lại giữa buổi)."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE consent_tickets SET expires_at = datetime('now'), used = 1 WHERE workspace_id = ?",
            (workspace_id,),
        )
        return cur.rowcount


def _consume_once_ticket(ticket_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE consent_tickets SET used = 1 WHERE id = ?", (ticket_id,))


def _log(req: EgressRequest, consented: bool) -> int:
    """Ghi nhật ký. `summary` do caller soạn — không bao giờ chứa API key."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO egress_log
                (workspace_id, module, destination, endpoint, n_chars, summary, consented)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.workspace_id,
                req.module,
                req.destination,
                req.endpoint,
                req.n_chars,
                req.summary[:2000],
                int(consented),
            ),
        )
        return int(cur.lastrowid or 0)


def build_preview(req: EgressRequest) -> EgressPreview:
    ws = _workspace(req.workspace_id) if req.workspace_id else None
    return EgressPreview(
        workspace_id=req.workspace_id or 0,
        workspace_name=str(ws["name"]) if ws else "(không thuộc hồ sơ nào)",
        module=req.module,
        destination=req.destination,
        endpoint=req.endpoint,
        n_chars=req.n_chars,
        summary=req.summary,
        payload_excerpt=req.payload_text[:4000],
    )


@contextmanager
def egress(req: EgressRequest) -> Iterator[EgressPreview]:
    """Cổng bắt buộc quanh mọi lệnh gọi ra ngoài.

    Dùng:
        with egress(EgressRequest(module="rag.qa", destination="llm", ...)):
            ... gọi API ...

    Ném:
        PayloadTooLarge — payload vượt trần, gần như chắc là đang gửi cả tài liệu.
        ConsentRequired — hồ sơ mật, chưa có vé đồng ý.
    """
    if req.n_chars > MAX_PAYLOAD_CHARS:
        raise PayloadTooLarge(
            f"Module '{req.module}' định gửi {req.n_chars} ký tự (trần {MAX_PAYLOAD_CHARS}). "
            "Chỉ được gửi các đoạn ngữ cảnh đã truy hồi, không gửi toàn bộ tài liệu."
        )

    preview = build_preview(req)
    consented = True
    ticket: dict[str, object] | None = None

    if is_confidential(req.workspace_id):
        assert req.workspace_id is not None
        ticket = find_consent(req.workspace_id, req.destination)
        if ticket is None:
            # Ghi lại cả lần bị chặn để chuyên gia thấy hệ thống đã thực sự chặn.
            _log(req, consented=False)
            raise ConsentRequired(preview)
        consented = True

    try:
        yield preview
    finally:
        # Luôn ghi nhật ký, kể cả khi lệnh gọi bên trong thất bại — dữ liệu đã rời máy rồi.
        _log(req, consented=consented)
        if ticket is not None and ticket.get("scope") == "once":
            _consume_once_ticket(int(ticket["id"]))


def recent_log(
    workspace_id: int | None = None, limit: int = 200
) -> list[dict[str, object]]:
    """Nhật ký gửi ra ngoài, mới nhất trước. Dùng cho trang kiểm chứng (spec A7.2)."""
    sql = "SELECT * FROM egress_log"
    params: tuple[object, ...] = ()
    if workspace_id is not None:
        sql += " WHERE workspace_id = ?"
        params = (workspace_id,)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params += (limit,)
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
