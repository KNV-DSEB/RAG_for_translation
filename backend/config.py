"""Cấu hình tập trung cho backend.

Input:  biến môi trường từ `.env` (nạp bằng python-dotenv).
Output: đối tượng `settings` chứa đường dẫn, tên model, và các ngưỡng nghiệp vụ.

Nguyên tắc: KHÔNG hardcode API key, KHÔNG in key ra log (xem CLAUDE.md > Bảo mật).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw and raw.strip().isdigit() else default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    # ----- Đường dẫn -----
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    db_path: Path = BASE_DIR / "data" / "app.db"
    chroma_dir: Path = BASE_DIR / "data" / "chroma"
    documents_dir: Path = BASE_DIR / "data" / "documents"
    recordings_dir: Path = BASE_DIR / "data" / "recordings"
    tts_cache_dir: Path = BASE_DIR / "data" / "tts_cache"
    test_documents_dir: Path = BASE_DIR / "data" / "test_documents"

    # ----- LLM (Gemini) -----
    # Key đọc từ .env, không bao giờ ghi vào log hay trả về qua API.
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", "").strip())

    # HAI BẬC MODEL. Lý do: hạn mức free tier là `GenerateRequestsPerDayPerProjectPerModel`
    # — tính riêng cho TỪNG model (đo thực tế: gemini-2.5-flash chỉ 20 request/ngày).
    # Tách theo loại việc vừa nhân được hạn mức ngày, vừa khớp sức mạnh model với công việc.
    #   quality — ít lệnh gọi, cần chất lượng cao: sinh kịch bản, tổng hợp hồ sơ, hỏi đáp
    #   light   — nhiều lệnh gọi, việc rút trích có cấu trúc: trích thuật ngữ, chấm điểm
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    )
    gemini_model_light: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL_LIGHT", "gemini-3.5-flash-lite")
    )
    # Hết hạn mức ngày của một model thì tự chuyển sang model kế tiếp trong danh sách.
    gemini_fallbacks: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            m.strip()
            for m in os.getenv(
                "GEMINI_FALLBACKS",
                "gemini-3.6-flash,gemini-3.1-flash-lite,gemini-flash-lite-latest,gemini-2.5-flash",
            ).split(",")
            if m.strip()
        )
    )
    llm_timeout_sec: int = field(default_factory=lambda: _env_int("LLM_TIMEOUT_SEC", 90))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 1))
    # Giới hạn theo PHÚT thì chờ rồi thử lại được; giới hạn theo NGÀY thì phải đổi model.
    llm_rate_limit_retries: int = field(
        default_factory=lambda: _env_int("LLM_RATE_LIMIT_RETRIES", 2)
    )
    llm_rate_limit_wait_sec: int = field(
        default_factory=lambda: _env_int("LLM_RATE_LIMIT_WAIT_SEC", 20)
    )

    # ----- Embedding (chạy local, không tính là egress) -----
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )

    # ----- TTS: edge-tts chính, gTTS fallback -----
    tts_voice_vi: str = field(default_factory=lambda: os.getenv("TTS_VOICE_VI", "vi-VN-NamMinhNeural"))
    tts_voice_en: str = field(default_factory=lambda: os.getenv("TTS_VOICE_EN", "en-US-JennyNeural"))

    # ----- Research Agent -----
    # Trần cứng theo CLAUDE.md: tối đa 5-8 truy vấn mỗi lần research.
    max_search_queries: int = field(default_factory=lambda: _env_int("MAX_SEARCH_QUERIES", 8))
    search_results_per_query: int = field(
        default_factory=lambda: _env_int("SEARCH_RESULTS_PER_QUERY", 8)
    )
    min_glossary_terms: int = field(default_factory=lambda: _env_int("MIN_GLOSSARY_TERMS", 15))

    # ----- Tài liệu -----
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 25))
    chunk_size_chars: int = field(default_factory=lambda: _env_int("CHUNK_SIZE_CHARS", 1200))
    chunk_overlap_chars: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP_CHARS", 200))
    # Câu hỏi mở kiểu "cho tôi thông tin về dự án" rất dễ khớp vào đoạn mở đầu/kết thúc
    # mà bỏ sót đoạn chứa số liệu. Lấy rộng hơn để không mất con số quan trọng.
    retrieval_top_k: int = field(default_factory=lambda: _env_int("RETRIEVAL_TOP_K", 10))
    # Dưới ngưỡng này coi như PDF không có lớp chữ (ảnh scan).
    scanned_pdf_char_threshold: int = field(
        default_factory=lambda: _env_int("SCANNED_PDF_CHAR_THRESHOLD", 120)
    )

    # ----- Mock buổi dịch -----
    turn_sentences: int = field(default_factory=lambda: _env_int("TURN_SENTENCES", 5))
    turn_min_sec: int = field(default_factory=lambda: _env_int("TURN_MIN_SEC", 30))
    turn_max_sec: int = field(default_factory=lambda: _env_int("TURN_MAX_SEC", 60))
    # Tốc độ đọc dùng để ước lượng thời lượng lượt ngay lúc sinh kịch bản.
    # ĐO THỰC TẾ trên edge-tts ở tốc độ bình thường, qua 8 lượt của bộ tài liệu LDSC:
    # tiếng Việt 228 từ/phút, tiếng Anh 158 từ/phút. Trước đây để 140/130 (đoán mò) khiến
    # ước lượng cao hơn thực tế 1.6x với tiếng Việt — bộ sinh tưởng lượt dài 60 giây trong
    # khi audio thật chỉ 35 giây, nên kịch bản luôn dồn về đầu thấp của khoảng 30–60s.
    words_per_min_vi: int = field(default_factory=lambda: _env_int("WORDS_PER_MIN_VI", 228))
    words_per_min_en: int = field(default_factory=lambda: _env_int("WORDS_PER_MIN_EN", 158))
    max_recording_sec: int = field(default_factory=lambda: _env_int("MAX_RECORDING_SEC", 180))

    # ----- Vòng phản hồi §6 -----
    # Số nhận định tối đa chèn vào prompt chấm điểm (không đưa hết được).
    max_verdicts_in_prompt: int = field(
        default_factory=lambda: _env_int("MAX_VERDICTS_IN_PROMPT", 12)
    )

    # ----- Hạ tầng -----
    backend_host: str = field(default_factory=lambda: os.getenv("BACKEND_HOST", "127.0.0.1"))
    backend_port: int = field(default_factory=lambda: _env_int("BACKEND_PORT", 8000))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))

    @property
    def has_gemini_key(self) -> bool:
        """Có key hay không. Dùng để báo lỗi rõ ràng thay vì để gọi API rồi mới hỏng."""
        return bool(self.gemini_api_key)

    def ensure_dirs(self) -> None:
        """Tạo sẵn các thư mục dữ liệu. Gọi một lần lúc khởi động."""
        for path in (
            self.data_dir,
            self.chroma_dir,
            self.documents_dir,
            self.recordings_dir,
            self.tts_cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
