"""Luồng đưa tài liệu lên kho: giấy phép → tải lên → chốt.

Vào:  yêu cầu đã xác thực (hồ sơ, tên tệp, cỡ tệp, kiểu tệp).
Ra:   một dòng `documents` và một đối tượng trong kho, hoặc lỗi rõ ràng.

Vì sao ba bước
--------------
Trình duyệt gửi tệp THẲNG tới kho, không đi vòng qua backend. Tệp 25 MB đi qua backend
là chiếm bộ nhớ và thời gian của tiến trình đang phục vụ mọi người, mà không đổi lại
được bảo đảm nào — backend vẫn phải kiểm lại ở bước chốt.

  1. `create_intent`  máy chủ kiểm quyền, kiểm cỡ/kiểu, TỰ DỰNG khoá, tạo dòng
                      `documents` ở trạng thái `awaiting_upload`, phát giấy phép.
  2. (trình duyệt tải tệp lên URL trong giấy phép)
  3. `finalize`       máy chủ kiểm đối tượng CÓ THẬT, đọc lại nội dung, tự tính SHA256,
                      rồi mới ghi nhận là đã lên kho.

Bước 3 không tin bất cứ điều gì trình duyệt nói. Trình duyệt có thể báo "xong rồi" mà
chưa tải gì, hoặc tải một tệp khác. Máy chủ tự đọc lại và tự băm.

Trạng thái `awaiting_upload` là có chủ đích: nếu trình duyệt bỏ ngang, dòng đó vẫn nằm
lại và nhìn thấy được, thay vì im lặng biến mất. Một tài liệu "đang chờ tải lên" từ ba
ngày trước là thông tin, không phải rác.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from backend.auth.context import request_user
from backend.config import settings
from backend.db import get_conn
from backend.storage import get_backend
from backend.storage.base import StorageError, UploadTicket
from backend.storage.paths import UnsafeName, document_key

# Kiểu tệp nhận vào. Danh sách CHO PHÉP, không phải danh sách cấm: thêm một kiểu mới là
# quyết định có chủ đích, còn quên chặn một kiểu nguy hiểm thì không ai biết.
ALLOWED_EXT: frozenset[str] = frozenset({".doc", ".docx", ".pdf", ".txt", ".md", ".rtf"})


class UploadRejected(ValueError):
    """Yêu cầu tải lên không hợp lệ. Thông báo hướng tới chuyên gia, không phải lập trình."""


@dataclass(frozen=True)
class UploadIntent:
    document_id: int
    ticket: UploadTicket
    storage_key: str
    backend_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "storage_key": self.storage_key,
            "backend": self.backend_name,
            "upload": {
                "url": self.ticket.url,
                "method": self.ticket.method,
                "headers": self.ticket.headers,
                "expires_at": self.ticket.expires_at,
                "max_bytes": self.ticket.max_bytes,
            },
        }


def log_event(
    event: str,
    *,
    workspace_id: int | None = None,
    document_id: int | None = None,
    object_key: str | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    detail: str | None = None,
) -> None:
    """Ghi một sự kiện vòng đời dữ liệu trên kho.

    KHÔNG ghi nội dung tài liệu, ở đây hay bất cứ đâu khác. Bảng này để chuyên gia biết
    tệp nào đang nằm ở đâu — không phải để chứa lại tệp.
    """
    user = request_user()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO storage_events (workspace_id, document_id, user_id, event, "
            "backend, object_key, size_bytes, sha256, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (workspace_id, document_id, user.user_id if user else None, event,
             get_backend().name, object_key, size_bytes, sha256, detail),
        )


def _validate(filename: str, size_bytes: int) -> str:
    """Kiểm tên và cỡ tệp TRƯỚC khi phát giấy phép. Trả về phần mở rộng đã chuẩn hoá."""
    if size_bytes <= 0:
        raise UploadRejected("Tệp rỗng.")
    limit = settings.max_upload_mb * 1024 * 1024
    if size_bytes > limit:
        raise UploadRejected(
            f"Tệp {size_bytes / 1024 / 1024:.1f} MB, vượt mức {settings.max_upload_mb} MB."
        )

    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise UploadRejected(
            f"Không nhận tệp `{ext or 'không có phần mở rộng'}`. "
            f"Nhận: {', '.join(sorted(ALLOWED_EXT))}."
        )
    return ext


def create_intent(workspace_id: int, filename: str, size_bytes: int) -> UploadIntent:
    """Bước 1: kiểm quyền, dựng khoá, tạo dòng chờ, phát giấy phép.

    Quyền sở hữu đã được `workspace_guard` kiểm trước khi tới đây. Hàm này lấy `user_id`
    từ JWT đã xác minh để dựng khoá — KHÔNG lấy từ thân request.
    """
    ext = _validate(filename, size_bytes)

    user = request_user()
    # Chạy trên máy cá nhân thì không có danh tính. Dùng một nhánh riêng trong kho thay
    # vì bịa ra một UUID: bịa thì sau này không phân biệt được dữ liệu thật với dữ liệu
    # của lần chạy không đăng nhập.
    owner = user.user_id if user is not None else "local"

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (workspace_id, filename, stored_path, ext, size_bytes, "
            "status, storage_state) VALUES (?, ?, '', ?, ?, 'pending', 'awaiting_upload')",
            (workspace_id, filename, ext, size_bytes),
        )
        document_id = int(cur.lastrowid or 0)

    try:
        key = document_key(owner, workspace_id, document_id, filename)
    except UnsafeName as exc:
        with get_conn() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        raise UploadRejected(f"Tên tệp không dùng được: {exc}") from exc

    backend = get_backend()
    ticket = backend.create_upload_ticket(
        key,
        content_type="application/octet-stream",
        # Cho dư một chút so với cỡ khai báo: trình duyệt có thể thêm vài byte đệm. Vẫn
        # là trần cứng do máy chủ đặt, không phải con số trình duyệt tự chọn.
        max_bytes=min(size_bytes + 4096, settings.max_upload_mb * 1024 * 1024 + 4096),
    )

    with get_conn() as conn:
        conn.execute("UPDATE documents SET storage_key = ? WHERE id = ?", (key, document_id))

    log_event("upload_intent", workspace_id=workspace_id, document_id=document_id,
              object_key=key, size_bytes=size_bytes)
    return UploadIntent(document_id, ticket, key, backend.name)


def finalize(document_id: int) -> dict[str, Any]:
    """Bước 3: kiểm đối tượng CÓ THẬT, tự tính SHA256, rồi mới ghi nhận.

    Không tin bất cứ điều gì trình duyệt nói ở bước này. Trình duyệt có thể báo "xong"
    mà chưa tải gì, hoặc tải một tệp khác hẳn. Máy chủ tự đọc lại đối tượng và tự băm.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, workspace_id, filename, storage_key, size_bytes, storage_state "
            "FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise UploadRejected("Không tìm thấy tài liệu này.")

    key = str(row["storage_key"] or "")
    if not key:
        raise UploadRejected("Tài liệu này chưa có khoá lưu trữ — chưa xin giấy phép tải lên.")

    backend = get_backend()
    info = backend.stat(key)
    if info is None:
        # Trình duyệt báo xong nhưng kho không có gì. Giữ nguyên `awaiting_upload` chứ
        # KHÔNG đánh dấu là đã lên: một dòng nói dối ở đây sẽ thành một tài liệu "sẵn
        # sàng" mà mở ra thì rỗng.
        raise UploadRejected(
            "Kho lưu trữ chưa có tệp cho tài liệu này. Có thể lần tải lên đã hỏng — thử lại."
        )

    data = backend.download(key)
    digest = hashlib.sha256(data).hexdigest()
    actual = len(data)

    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET storage_state = 'uploaded', content_sha256 = ?, "
            "content_hash = ?, size_bytes = ?, status = 'pending' WHERE id = ?",
            (digest, digest, actual, document_id),
        )

    log_event("uploaded", workspace_id=int(row["workspace_id"]), document_id=document_id,
              object_key=key, size_bytes=actual, sha256=digest)

    return {
        "document_id": document_id,
        "storage_key": key,
        "size_bytes": actual,
        "sha256": digest,
        "storage_state": "uploaded",
        # Cỡ tệp khai lúc xin phép so với cỡ THẬT sau khi tải lên. Lệch không phải lỗi
        # bảo mật (trần đã do máy chủ ép), nhưng là dấu hiệu lần tải lên không trọn vẹn.
        "declared_size_matched": actual == int(row["size_bytes"] or 0),
    }


def delete_document_object(document_id: int) -> dict[str, Any]:
    """Xoá đối tượng của một tài liệu khỏi kho.

    Trả về thứ THẬT SỰ xảy ra. Kho và cơ sở dữ liệu không chung một giao dịch, nên xoá
    dòng rồi coi như tệp cũng mất là tự lừa mình — và tệ hơn, là nói với chuyên gia rằng
    tài liệu khách hàng đã bị xoá trong khi nó vẫn nằm trên kho.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT workspace_id, storage_key FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    if row is None or not row["storage_key"]:
        return {"deleted": False, "reason": "không có đối tượng nào để xoá"}

    key = str(row["storage_key"])
    ws = int(row["workspace_id"])
    try:
        removed = get_backend().delete(key)
    except StorageError as exc:
        log_event("delete_failed", workspace_id=ws, document_id=document_id,
                  object_key=key, detail=type(exc).__name__)
        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET storage_state = 'delete_failed' WHERE id = ?",
                (document_id,),
            )
        return {"deleted": False, "reason": f"kho lưu trữ từ chối xoá: {exc}"}

    log_event("deleted" if removed else "delete_failed", workspace_id=ws,
              document_id=document_id, object_key=key,
              detail=None if removed else "đối tượng không tồn tại")
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET storage_state = ? WHERE id = ?",
            ("deleted" if removed else "delete_failed", document_id),
        )
    return {"deleted": removed, "key": key}


# ============================== Lớp A: báo trước khi tải lên ==============================


def upload_notice(workspace_id: int, filename: str, size_bytes: int) -> dict[str, Any]:
    """Nói trước cho chuyên gia biết tệp sẽ đi đâu — TRƯỚC khi nó rời thiết bị.

    Đây là RANH GIỚI TIN CẬY MỚI mà bản chạy trên máy không có. Trên máy cá nhân, "tải
    tệp lên" nghĩa là chép từ thư mục này sang thư mục khác trên cùng cái máy đó. Trên
    web, nó nghĩa là tệp rời khỏi thiết bị của chuyên gia và sang một máy chủ ở nơi khác.
    Hai việc hoàn toàn khác nhau mang cùng một cái tên.

    Vì sao TÁCH khỏi hộp thoại đồng ý gửi ra bên thứ ba
    ---------------------------------------------------
    Hai câu hỏi khác nhau, và trả lời gộp là trả lời sai cả hai:

      Lớp A (đây)  "Tệp này có rời khỏi thiết bị của tôi sang kho của ứng dụng không?"
      Lớp B (gateway) "Dữ liệu có sang Gemini / DuckDuckGo / Microsoft / Google không?"

    Gộp lại thì mỗi lần lưu một tệp lại hiện hộp thoại "gửi dữ liệu ra ngoài" — và chuyên
    gia sẽ quen tay bấm đồng ý, đúng lúc mà hộp thoại thật sự quan trọng xuất hiện.

    Câu chữ ở đây SINH RA từ kho đang chạy, không viết cứng: bản local nói "vẫn nằm trên
    máy này", bản cloud nói thẳng là tệp rời khỏi thiết bị. Viết cứng thì một trong hai
    trường hợp sẽ là nói dối, mà ta không biết là trường hợp nào.
    """
    from backend.storage import is_cloud_storage

    ext = _validate(filename, size_bytes)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT name, is_confidential FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    workspace_name = str(row["name"]) if row else f"#{workspace_id}"
    confidential = bool(row["is_confidential"]) if row else False

    cloud = is_cloud_storage()
    if cloud:
        destination = f"kho riêng trên Supabase (bucket `{settings.supabase_bucket}`)"
        leaves_device = True
        headline = (
            f"Tệp này sẽ rời khỏi thiết bị của bạn và được lưu vào {destination}. "
            "Kho không công khai — chỉ tài khoản của bạn đọc được."
        )
        after = (
            "Sau bước này, tài liệu KHÔNG còn chỉ nằm trên máy bạn. Việc gửi nội dung "
            "sang Gemini, DuckDuckGo hay dịch vụ đọc lời thoại vẫn là chuyện riêng, và "
            "vẫn phải xin phép từng thao tác."
        )
    else:
        destination = "thư mục dữ liệu trên máy này"
        leaves_device = False
        headline = f"Tệp này sẽ được chép vào {destination}. Nó không rời khỏi máy."
        after = (
            "Việc gửi nội dung sang Gemini, DuckDuckGo hay dịch vụ đọc lời thoại là "
            "chuyện riêng, và vẫn phải xin phép từng thao tác."
        )

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "is_confidential": confidential,
        "filename": filename,
        "ext": ext,
        "size_bytes": size_bytes,
        "destination": destination,
        # Cờ này là thứ giao diện dùng để quyết định có phải hỏi hay chỉ cần báo. Nó do
        # MÁY CHỦ đặt theo kho đang chạy, không phải giao diện tự đoán.
        "leaves_device": leaves_device,
        "requires_acknowledgement": leaves_device,
        "headline": headline,
        "after_note": after,
        # Nói rõ đây KHÔNG phải bên thứ ba, để không ai đọc nhầm thành "đã gửi cho Google".
        "boundary": "app_cloud" if cloud else "device",
        "third_party_involved": False,
    }
