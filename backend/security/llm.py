"""Client Gemini — mọi lệnh gọi LLM của toàn dự án đi qua đây.

Input:  prompt (đã gồm sẵn các đoạn ngữ cảnh đã truy hồi) + schema Pydantic mong đợi.
Output: văn bản, hoặc một instance schema đã validate.

Bắt buộc: mọi lệnh gọi bọc trong `egress.egress(...)` để ghi nhật ký và tôn trọng
cờ hồ sơ mật (spec §7). Không được import `google.genai` ở bất kỳ module nào khác.

QUẢN LÝ HẠN MỨC FREE TIER (đo thực tế trên chính API key của dự án):
    - Hạn mức là `GenerateRequestsPerDayPerProjectPerModel` — tính riêng cho TỪNG model.
      `gemini-2.5-flash` chỉ cho 20 request/ngày.
    - Vì vậy chia hai bậc model: `quality` cho việc ít-nhưng-khó, `light` cho việc
      nhiều-nhưng-có-cấu-trúc. Hết hạn mức một model thì tự chuyển sang model kế tiếp.
    - Giới hạn theo PHÚT thì chờ rồi thử lại. Giới hạn theo NGÀY thì chờ vô ích — phải đổi model.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError, model_validator

from backend.config import settings
from backend.security import egress

Tier = Literal["quality", "light"]

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_RETRY_DELAY_RE = re.compile(r"retryDelay['\"\s:]*(\d+)s")


class LLMSchema(BaseModel):
    """Lớp cha cho mọi schema output của LLM.

    Mô hình rất hay trả `null` cho trường tuỳ chọn thay vì bỏ trường đó đi. Pydantic từ chối
    `null` với trường không Optional, làm hỏng cả lần gọi dù nội dung hoàn toàn dùng được.
    Bỏ các khoá có giá trị null trước khi validate để giá trị mặc định được áp dụng.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


T = TypeVar("T", bound=BaseModel)


# ============================== Lỗi có nghĩa nghiệp vụ ==============================


class LLMError(RuntimeError):
    """Lỗi chung khi gọi LLM."""


class LLMUnavailable(LLMError):
    """Thiếu API key — báo rõ để chuyên gia biết phải bổ sung gì."""


class LLMTimeout(LLMError):
    """Quá thời gian chờ. Caller phải giữ nguyên phần việc đã làm được."""


class LLMQuotaExceeded(LLMError):
    """Hết hạn mức ngày của TẤT CẢ model khả dụng."""


class LLMBlocked(LLMError):
    """Nội dung bị chặn bởi bộ lọc an toàn, hoặc trả về rỗng."""


class LLMBadResponse(LLMError):
    """Trả về sai cấu trúc sau khi đã thử lại — KHÔNG được hiện điểm rỗng cho người dùng."""


class _RateLimited(LLMError):
    """Nội bộ: giới hạn theo phút, chờ rồi thử lại được."""

    def __init__(self, wait_sec: int) -> None:
        super().__init__(f"Bị giới hạn tần suất, chờ {wait_sec}s")
        self.wait_sec = wait_sec


class _DailyQuotaForModel(LLMError):
    """Nội bộ: hết hạn mức NGÀY của một model cụ thể — chờ vô ích, phải đổi model."""

    def __init__(self, model: str) -> None:
        super().__init__(f"Hết hạn mức ngày của model {model}")
        self.model = model


# ============================== Chọn model ==============================


def model_chain(tier: Tier) -> list[str]:
    """Danh sách model thử theo thứ tự cho một bậc công việc."""
    primary = settings.gemini_model if tier == "quality" else settings.gemini_model_light
    chain = [primary]
    for name in settings.gemini_fallbacks:
        if name not in chain:
            chain.append(name)
    return chain


def _client() -> Any:
    """Khởi tạo client. Import bên trong hàm để module này nạp được kể cả khi chưa cài SDK."""
    if not settings.has_gemini_key:
        raise LLMUnavailable(
            "Chưa có GOOGLE_API_KEY. Sao chép .env.example thành .env rồi dán key "
            "lấy miễn phí tại https://aistudio.google.com/apikey"
        )
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover
        raise LLMUnavailable("Chưa cài thư viện google-genai. Chạy: uv sync") from exc
    return genai.Client(api_key=settings.gemini_api_key)


def _classify(exc: Exception, model: str) -> LLMError:
    """Dịch lỗi SDK thành exception nghiệp vụ. Không bao giờ đưa API key vào thông báo."""
    text = str(exc)
    lowered = text.lower()

    if "resource_exhausted" in lowered or "429" in text or "quota" in lowered:
        # Phân biệt hạn mức NGÀY (đổi model) với hạn mức PHÚT (chờ rồi thử lại).
        if "perday" in lowered.replace("_", ""):
            return _DailyQuotaForModel(model)
        match = _RETRY_DELAY_RE.search(text)
        wait = int(match.group(1)) if match else settings.llm_rate_limit_wait_sec
        return _RateLimited(min(wait, 60))

    if "not_found" in lowered or "404" in text:
        return _DailyQuotaForModel(model)  # model không dùng được → thử model khác
    if "timeout" in lowered or "deadline" in lowered or isinstance(exc, TimeoutError):
        return LLMTimeout("Gemini không phản hồi kịp. Bấm Thử lại — phần đã làm được vẫn giữ.")
    if "safety" in lowered or "blocked" in lowered or "prohibited" in lowered:
        return LLMBlocked("Nội dung bị bộ lọc an toàn của Gemini chặn. Thử sửa lại đầu vào.")
    if "api key" in lowered or "unauthenticated" in lowered or "permission" in lowered:
        return LLMUnavailable("API key không hợp lệ hoặc chưa được cấp quyền. Kiểm tra lại .env")
    return LLMError(f"Gọi Gemini thất bại: {type(exc).__name__}")


def _strip_fence(text: str) -> str:
    """Gemini hay bọc JSON trong ```json ... ``` dù đã yêu cầu JSON thuần."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


# ============================== Lệnh gọi ==============================


def _generate_once(
    client: Any,
    model: str,
    prompt: str,
    system_instruction: str | None,
    temperature: float,
    json_mode: bool,
    response_schema: type[BaseModel] | None,
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

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return (getattr(response, "text", None) or "").strip()


def _call(
    *,
    module: str,
    prompt: str,
    workspace_id: int | None,
    system_instruction: str | None,
    temperature: float,
    json_mode: bool,
    summary: str,
    tier: Tier,
    response_schema: type[BaseModel] | None = None,
) -> tuple[str, str]:
    """Một lệnh gọi Gemini, đã bọc cổng egress. Trả về (text thô, model đã dùng).

    Tự xử lý hai loại giới hạn: theo phút thì chờ, theo ngày thì đổi model.
    """
    client = _client()
    chain = model_chain(tier)
    exhausted: list[str] = []

    request = egress.EgressRequest(
        module=module,
        destination="llm",
        payload_text=prompt if not system_instruction else f"{system_instruction}\n\n{prompt}",
        summary=summary,
        workspace_id=workspace_id,
    )

    for model in chain:
        request.endpoint = f"gemini:{model}"
        attempts_left = settings.llm_rate_limit_retries

        while True:
            try:
                with egress.egress(request):
                    text = _generate_once(
                        client, model, prompt, system_instruction,
                        temperature, json_mode, response_schema,
                    )
                break  # gọi xong, thoát vòng chờ
            except (egress.ConsentRequired, egress.PayloadTooLarge, LLMUnavailable):
                raise
            except Exception as exc:
                error = _classify(exc, model) if not isinstance(exc, LLMError) else exc

                if isinstance(error, _RateLimited) and attempts_left > 0:
                    attempts_left -= 1
                    time.sleep(error.wait_sec)
                    continue
                if isinstance(error, (_RateLimited, _DailyQuotaForModel)):
                    exhausted.append(model)
                    text = ""
                    break
                raise error from exc

        if text:
            return text, model
        if not exhausted or exhausted[-1] != model:
            # Trả về rỗng nhưng không phải do hạn mức → là nội dung bị chặn.
            raise LLMBlocked(
                "Gemini trả về rỗng (có thể bị bộ lọc an toàn chặn). "
                "Thử sinh lại hoặc sửa đầu vào."
            )

    raise LLMQuotaExceeded(
        "Đã dùng hết hạn mức miễn phí hôm nay của tất cả model khả dụng "
        f"({', '.join(exhausted)}). Hạn mức đặt lại theo ngày. "
        "Phần việc đã hoàn thành vẫn được giữ nguyên."
    )


def generate_text(
    *,
    module: str,
    prompt: str,
    workspace_id: int | None = None,
    system_instruction: str | None = None,
    temperature: float = 0.4,
    summary: str = "",
    tier: Tier = "quality",
) -> str:
    """Sinh văn bản thuần."""
    text, _ = _call(
        module=module,
        prompt=prompt,
        workspace_id=workspace_id,
        system_instruction=system_instruction,
        temperature=temperature,
        json_mode=False,
        summary=summary or f"{module}: sinh văn bản",
        tier=tier,
    )
    return text


def generate_json(
    *,
    module: str,
    prompt: str,
    schema: type[T],
    workspace_id: int | None = None,
    system_instruction: str | None = None,
    temperature: float = 0.3,
    summary: str = "",
    tier: Tier = "quality",
) -> T:
    """Sinh JSON và validate theo schema Pydantic.

    Sai cấu trúc thì thử lại đúng MỘT lần (theo edge case §4.3 của spec), vẫn sai thì ném
    `LLMBadResponse` — tầng trên phải báo lỗi chứ không được hiện kết quả rỗng.
    """
    attempts = 1 + max(0, settings.llm_max_retries)
    last_error: Exception | None = None
    effective_prompt = prompt

    for attempt in range(attempts):
        raw, _model = _call(
            module=module,
            prompt=effective_prompt,
            workspace_id=workspace_id,
            system_instruction=system_instruction,
            temperature=temperature,
            json_mode=True,
            summary=summary or f"{module}: sinh JSON ({schema.__name__})",
            tier=tier,
            response_schema=schema,
        )
        try:
            return schema.model_validate(json.loads(_strip_fence(raw)))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                # Lần thử lại: nói rõ sai ở đâu để mô hình tự sửa cấu trúc.
                effective_prompt = (
                    f"{prompt}\n\n"
                    "LƯU Ý: lần trước bạn trả về JSON không đúng cấu trúc. "
                    f"Lỗi: {str(exc)[:500]}\n"
                    "Lần này CHỈ trả về JSON thuần, không kèm giải thích, không bọc trong ```."
                )

    raise LLMBadResponse(
        f"Gemini trả về dữ liệu sai cấu trúc sau {attempts} lần thử "
        f"({type(last_error).__name__}). Chưa thể hiện kết quả."
    )


def ping(workspace_id: int | None = None) -> str:
    """Gọi thử một lệnh ngắn để nghiệm thu: có kết nối + có ghi nhật ký egress."""
    return generate_text(
        module="system.ping",
        prompt="Trả lời đúng hai chữ: OK",
        workspace_id=workspace_id,
        temperature=0.0,
        summary="Kiểm tra kết nối Gemini (ping)",
        tier="light",
    )


def available_models(tier: Tier = "quality") -> list[str]:
    """Chuỗi model sẽ thử — dùng cho /health để chuyên gia biết đang dùng gì."""
    return model_chain(tier)
