"""Provider: Gemini (Google). Đích `llm`.

Vào:  prompt + cấu hình sinh.
Ra:   văn bản mô hình trả về (đã strip).

KHÔNG bắt lỗi ở đây — `security/llm.py` mới là nơi phân loại lỗi SDK thành hạn mức
ngày / hạn mức phút / bị chặn, vì nó cũng là nơi giữ chuỗi model dự phòng.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

PROVIDER = "gemini"

_CLIENT: Any = None
_CLIENT_KEY: str | None = None


def _client(api_key: str) -> Any:
    """Dùng lại client giữa các lần gọi — tạo mới mỗi request là phí công bắt tay TLS."""
    global _CLIENT, _CLIENT_KEY
    if _CLIENT is None or _CLIENT_KEY != api_key:
        from google import genai

        _CLIENT = genai.Client(api_key=api_key)
        _CLIENT_KEY = api_key
    return _CLIENT


def generate(
    *,
    api_key: str,
    model: str,
    prompt: str,
    system_instruction: str | None = None,
    temperature: float = 0.7,
    json_mode: bool = False,
    response_schema: type[BaseModel] | None = None,
) -> str:
    from google.genai import types

    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
        # Ép mô hình sinh đúng hình dạng thay vì chỉ "một JSON nào đó".
        if response_schema is not None:
            config_kwargs["response_schema"] = response_schema

    response = _client(api_key).models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return (getattr(response, "text", None) or "").strip()
