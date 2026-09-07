"""Dựng khoá đối tượng trong kho lưu trữ — MÁY CHỦ quyết định, không phải client.

Vào:  user_id, workspace_id, document_id, tên tệp người dùng đặt.
Ra:   một khoá chuẩn hoá, an toàn, mang sẵn ranh giới sở hữu.

Vì sao máy chủ dựng đường dẫn
-----------------------------
Nếu client gửi lên đường dẫn đích, nó gửi được `../../users/<người khác>/…` và ghi đè
tệp của người khác. Không có cách nào "kiểm tra cho kỹ" đường dẫn do client gửi mà an
toàn bằng việc KHÔNG NHẬN nó. Client chỉ nói tên tệp gốc; mọi thứ khác do máy chủ đặt.

Hình dạng khoá
--------------
    users/{user_id}/workspaces/{workspace_id}/documents/{document_id}/{tên-đã-làm-sạch}

Ba mảnh danh tính nằm ngay trong đường dẫn, nên chính sách bảo mật của kho (RLS trên
Supabase Storage) chặn được theo tiền tố mà không cần tra cơ sở dữ liệu. Đây là chỗ RLS
THẬT SỰ có tác dụng — khác với truy vấn từ backend, nơi vai trò quyền cao bỏ qua RLS
(xem `docs/security-model.md`).

`document_id` nằm trong đường dẫn nên hai tệp trùng tên trong cùng hồ sơ KHÔNG đè nhau.
Không dùng tên người dùng đặt làm định danh duy nhất: nó không duy nhất, và người dùng
đổi được nó.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata

# Ký tự an toàn cho khoá đối tượng. Supabase Storage nhận nhiều hơn thế, nhưng thu hẹp
# lại thì không phải đoán xem tầng nào diễn giải ký tự lạ theo kiểu gì.
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_REPEAT = re.compile(r"-{2,}")

MAX_NAME_LEN = 120
MAX_KEY_LEN = 700


class UnsafeName(ValueError):
    """Tên tệp không dùng được, kể cả sau khi làm sạch."""


def sanitize_filename(filename: str) -> str:
    """Đưa tên tệp người dùng đặt về dạng an toàn, GIỮ phần mở rộng.

    Tiếng Việt có dấu được chuyển sang không dấu chứ không bị xoá: `Kế hoạch.docx` thành
    `Ke-hoach.docx` chứ không thành `.docx`. Tên gốc vẫn được lưu nguyên trong cột
    `documents.filename` để hiển thị — bản làm sạch chỉ dùng cho khoá lưu trữ.
    """
    raw = (filename or "").strip().replace("\\", "/")
    # Chỉ lấy thành phần cuối: `../../etc/passwd` thành `passwd`.
    raw = posixpath.basename(raw)
    if not raw or raw in {".", ".."}:
        raise UnsafeName(f"tên tệp không dùng được: {filename!r}")

    stem, dot, ext = raw.rpartition(".")
    if not dot:
        stem, ext = raw, ""

    def clean(part: str) -> str:
        # NFKD tách dấu ra khỏi chữ cái, rồi bỏ phần dấu — giữ được chữ gốc.
        folded = unicodedata.normalize("NFKD", part)
        folded = "".join(c for c in folded if not unicodedata.combining(c))
        folded = folded.replace("đ", "d").replace("Đ", "D")
        folded = _SAFE.sub("-", folded).strip("-._")
        return _REPEAT.sub("-", folded)

    stem_safe = clean(stem)[:MAX_NAME_LEN] or "tai-lieu"
    ext_safe = clean(ext).lower()[:12]

    return f"{stem_safe}.{ext_safe}" if ext_safe else stem_safe


def document_key(user_id: str, workspace_id: int, document_id: int, filename: str) -> str:
    """Khoá đối tượng chuẩn cho một tài liệu. Ném lỗi nếu bất kỳ mảnh nào không hợp lệ."""
    for name, value in (("user_id", user_id), ("workspace_id", workspace_id),
                        ("document_id", document_id)):
        if value in (None, "", 0):
            raise UnsafeName(f"thiếu {name} — không dựng được khoá có ranh giới sở hữu")

    uid = _SAFE.sub("", str(user_id))
    if not uid:
        raise UnsafeName(f"user_id không dùng được: {user_id!r}")

    key = (
        f"users/{uid}/workspaces/{int(workspace_id)}/"
        f"documents/{int(document_id)}/{sanitize_filename(filename)}"
    )
    if len(key) > MAX_KEY_LEN:
        raise UnsafeName(f"khoá dài {len(key)} ký tự, quá {MAX_KEY_LEN}")
    if ".." in key or key.startswith("/"):
        raise UnsafeName(f"khoá không an toàn sau khi dựng: {key!r}")
    return key


def tts_key(user_id: str, workspace_id: int, digest: str) -> str:
    """Khoá cho tệp âm thanh đã sinh. Cùng ranh giới sở hữu như tài liệu."""
    uid = _SAFE.sub("", str(user_id))
    safe = _SAFE.sub("", digest)[:64]
    if not uid or not safe:
        raise UnsafeName("thiếu user_id hoặc mã băm để dựng khoá âm thanh")
    return f"users/{uid}/workspaces/{int(workspace_id)}/tts/{safe}.mp3"


def owner_prefix(user_id: str, workspace_id: int | None = None) -> str:
    """Tiền tố dùng để liệt kê hoặc xoá theo ranh giới sở hữu."""
    uid = _SAFE.sub("", str(user_id))
    if not uid:
        raise UnsafeName(f"user_id không dùng được: {user_id!r}")
    if workspace_id is None:
        return f"users/{uid}/"
    return f"users/{uid}/workspaces/{int(workspace_id)}/"
