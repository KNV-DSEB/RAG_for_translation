"""Client kho lưu trữ Supabase — nơi DUY NHẤT giữ client mạng cho kho lưu trữ.

Đặt ở đây, cạnh các provider bên thứ ba, vì lý do KỸ THUẬT chứ không phải phân loại:
invariant C1a cấm mọi module ngoài `security/providers/**` import thư viện mạng, và
client này dùng `httpx`. Nhưng nó KHÁC hạng mục với Gemini/DDGS/TTS:

  Gemini, DDGS, edge-tts, gTTS  →  BÊN THỨ BA. Qua `gateway.execute()`, ghi `egress_log`,
                                    hồ sơ mật phải xin phép trước.
  Supabase Storage              →  HẠ TẦNG CỦA CHÍNH ỨNG DỤNG. Cùng hạng với kết nối
                                    PostgreSQL. Nhật ký riêng `storage_events`.

Vì thế module này KHÔNG được đăng ký vào `gateway._REGISTRY` và không đi qua
`gateway.execute()`. Cửa của nó là `backend/storage/cloud.py`. Hai cửa, mỗi cửa có tên,
có nhật ký riêng, và có invariant riêng canh — xem `tests/test_c1_single_door.py`.

CHƯA TỪNG CHẠY THẬT
-------------------
Toàn bộ tệp này viết theo tài liệu HTTP API của Supabase Storage. Máy phát triển không
có credential Supabase, nên KHÔNG một dòng nào ở đây từng gọi tới máy chủ thật. Test
chạy trên `LocalStorage`, và điều đó chứng minh LUỒNG đúng, không chứng minh Supabase
hành xử như mô tả. Đừng báo cáo ngược lại.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

PROVIDER = "supabase_storage"
TIMEOUT_SEC = 60.0


class SupabaseStorageError(RuntimeError):
    """Lỗi từ Supabase Storage. KHÔNG mang theo khoá API trong thông báo."""


@dataclass(frozen=True)
class Config:
    url: str            # https://<project>.supabase.co
    service_key: str
    bucket: str

    @property
    def base(self) -> str:
        return f"{self.url.rstrip('/')}/storage/v1"


def _headers(cfg: Config, extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {cfg.service_key}", "apikey": cfg.service_key}
    h.update(extra or {})
    return h


def _raise(resp: httpx.Response, what: str) -> None:
    """Chuyển lỗi HTTP thành lỗi có nghĩa, KHÔNG lộ khoá.

    `resp.request.headers` chứa `Authorization: Bearer <service key>`. Ném nguyên
    `HTTPStatusError` là đưa khoá vào chuỗi lỗi, rồi vào log của nền tảng.
    """
    body = ""
    try:
        body = resp.text[:200]
    except Exception:  # noqa: BLE001
        pass
    raise SupabaseStorageError(f"{what} thất bại: HTTP {resp.status_code} {body}")


def create_signed_upload_url(cfg: Config, key: str, *, upsert: bool = False) -> dict[str, Any]:
    """URL ký sẵn để trình duyệt tải tệp lên THẲNG kho, không đi vòng qua backend."""
    with httpx.Client(timeout=TIMEOUT_SEC) as client:
        resp = client.post(
            f"{cfg.base}/object/upload/sign/{cfg.bucket}/{key}",
            headers=_headers(cfg, {"x-upsert": "true" if upsert else "false"}),
        )
    if resp.status_code >= 400:
        _raise(resp, "tạo URL tải lên")
    data = resp.json()
    return {"key": key, "signed_url": f"{cfg.url.rstrip('/')}/storage/v1{data['url']}"}


def create_signed_download_url(cfg: Config, key: str, ttl_sec: int) -> str:
    with httpx.Client(timeout=TIMEOUT_SEC) as client:
        resp = client.post(
            f"{cfg.base}/object/sign/{cfg.bucket}/{key}",
            headers=_headers(cfg, {"Content-Type": "application/json"}),
            json={"expiresIn": ttl_sec},
        )
    if resp.status_code >= 400:
        _raise(resp, "tạo URL tải xuống")
    return f"{cfg.url.rstrip('/')}/storage/v1{resp.json()['signedURL']}"


def stat(cfg: Config, key: str) -> dict[str, Any] | None:
    """Đối tượng có tồn tại không, và lớn bao nhiêu. `None` nếu không có."""
    with httpx.Client(timeout=TIMEOUT_SEC) as client:
        resp = client.head(f"{cfg.base}/object/{cfg.bucket}/{key}", headers=_headers(cfg))
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        _raise(resp, "đọc thông tin đối tượng")
    return {
        "key": key,
        "size_bytes": int(resp.headers.get("content-length", 0)),
        "content_type": resp.headers.get("content-type"),
    }


def download(cfg: Config, key: str) -> bytes:
    with httpx.Client(timeout=TIMEOUT_SEC) as client:
        resp = client.get(f"{cfg.base}/object/{cfg.bucket}/{key}", headers=_headers(cfg))
    if resp.status_code >= 400:
        _raise(resp, "tải đối tượng")
    return resp.content


def delete(cfg: Config, keys: list[str]) -> int:
    """Xoá nhiều đối tượng. Trả về SỐ THẬT SỰ bị xoá theo máy chủ báo về.

    Không suy ra từ số khoá đã gửi: đó là chỗ mà "đã xoá toàn bộ" trở thành lời nói dối
    khi một khoá không tồn tại hoặc bị từ chối.
    """
    if not keys:
        return 0
    with httpx.Client(timeout=TIMEOUT_SEC) as client:
        resp = client.request(
            "DELETE",
            f"{cfg.base}/object/{cfg.bucket}",
            headers=_headers(cfg, {"Content-Type": "application/json"}),
            json={"prefixes": keys},
        )
    if resp.status_code >= 400:
        _raise(resp, "xoá đối tượng")
    body = resp.json()
    return len(body) if isinstance(body, list) else 0


def list_prefix(cfg: Config, prefix: str, *, limit: int = 1000) -> list[dict[str, Any]]:
    with httpx.Client(timeout=TIMEOUT_SEC) as client:
        resp = client.post(
            f"{cfg.base}/object/list/{cfg.bucket}",
            headers=_headers(cfg, {"Content-Type": "application/json"}),
            json={"prefix": prefix.rstrip("/"), "limit": limit,
                  "sortBy": {"column": "name", "order": "asc"}},
        )
    if resp.status_code >= 400:
        _raise(resp, "liệt kê đối tượng")
    return list(resp.json())
