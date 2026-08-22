"""Nhận diện ngôn ngữ tài liệu, và phát hiện tài liệu SONG NGỮ SONG SONG.

Input:  danh sách `ExtractedBlock`.
Output: `DocumentLanguage` gồm nhãn tổng thể, nhãn từng khối, và điểm cắt nếu là song ngữ.

Vì sao cần riêng nhãn "song ngữ song song": tài liệu có sẵn cả bản Việt và bản Anh của
cùng một nội dung (ví dụ bài phát biểu đã dịch sẵn) là nguồn quý nhất trong dự án —
    (a) trích được cặp thuật ngữ do NGƯỜI THẬT dịch, không phải máy suy đoán;
    (b) dùng làm bản dịch tham chiếu mức ⭐⭐⭐ khi chấm điểm (spec §6.1).

Phương pháp nhận ngôn ngữ: ưu tiên tỷ lệ ký tự đặc trưng tiếng Việt (rất đáng tin và
không phụ thuộc độ dài), chỉ khi không rõ mới dùng `langdetect`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from backend.rag.extractors import ExtractedBlock

LangCode = Literal["vi", "en", "unknown"]
DocLang = Literal["vi", "en", "parallel", "mixed", "unknown"]

# Ký tự chỉ có trong bảng chữ cái tiếng Việt (ngoài ASCII).
_VIETNAMESE_CHARS = set(
    "àáảãạăằắẳẵặâầấẩẫậ"
    "èéẻẽẹêềếểễệ"
    "ìíỉĩị"
    "òóỏõọôồốổỗộơờớởỡợ"
    "ùúủũụưừứửữự"
    "ỳýỷỹỵ"
    "đ"
)

# Trên ngưỡng này thì gần như chắc chắn là tiếng Việt.
_VI_CHAR_RATIO = 0.012
# Mỗi ngôn ngữ phải chiếm ít nhất bấy nhiêu ký tự thì mới xét là song ngữ.
_MIN_SIDE_RATIO = 0.25
# Điểm cắt phải "sạch" tối thiểu bấy nhiêu thì mới coi là song ngữ song song
# (thay vì hai thứ tiếng trộn lẫn lộn xộn).
_MIN_SPLIT_PURITY = 0.80
# Khối ngắn hơn mức này không đủ tin để nhận ngôn ngữ.
_MIN_CHARS_FOR_DETECT = 25


@dataclass
class DocumentLanguage:
    language: DocLang
    block_languages: list[LangCode]
    vi_char_ratio: float = 0.0
    en_char_ratio: float = 0.0
    # Chỉ có khi language == 'parallel': chỉ số khối bắt đầu nửa sau
    split_index: int | None = None
    split_purity: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def is_parallel(self) -> bool:
        return self.language == "parallel"

    @property
    def label_vi(self) -> str:
        """Nhãn tiếng Việt để hiển thị trên giao diện."""
        return {
            "vi": "tiếng Việt",
            "en": "tiếng Anh",
            "parallel": "song ngữ song song",
            "mixed": "trộn hai thứ tiếng",
            "unknown": "chưa xác định",
        }[self.language]


def detect_language(text: str) -> LangCode:
    """Nhận ngôn ngữ một đoạn văn bản. Trả 'unknown' khi quá ngắn để chắc chắn."""
    stripped = text.strip()
    if len(stripped) < _MIN_CHARS_FOR_DETECT:
        return "unknown"

    lowered = stripped.lower()
    letters = [c for c in lowered if c.isalpha()]
    if not letters:
        return "unknown"

    vi_hits = sum(1 for c in letters if c in _VIETNAMESE_CHARS)
    if (vi_hits / len(letters)) >= _VI_CHAR_RATIO:
        return "vi"

    # Không có dấu tiếng Việt: nhờ langdetect phân biệt. Đặt seed cho kết quả ổn định.
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        code = detect(stripped)
    except Exception:
        return "unknown"

    if code == "vi":
        return "vi"
    if code == "en":
        return "en"
    return "unknown"


def _best_split(langs: Sequence[LangCode]) -> tuple[int | None, float]:
    """Tìm điểm cắt chia dãy khối thành hai nửa thuần ngôn ngữ nhất có thể.

    Trả về (chỉ số cắt, độ thuần). Độ thuần = tỷ lệ khối nằm đúng nửa của nó.
    Đây là cách phân biệt tài liệu SONG SONG (bản Việt rồi tới bản Anh) với tài liệu
    chỉ TRỘN LẪN hai thứ tiếng lung tung.
    """
    known = [(i, lang) for i, lang in enumerate(langs) if lang in ("vi", "en")]
    if len(known) < 4:
        return None, 0.0

    best_index: int | None = None
    best_purity = 0.0

    # Thử mọi điểm cắt, chấm theo cả hai chiều (vi trước / en trước).
    for cut in range(1, len(known)):
        left = [lang for _, lang in known[:cut]]
        right = [lang for _, lang in known[cut:]]
        for first, second in (("vi", "en"), ("en", "vi")):
            correct = sum(1 for l in left if l == first) + sum(1 for l in right if l == second)
            purity = correct / len(known)
            if purity > best_purity:
                best_purity = purity
                best_index = known[cut][0]

    return best_index, best_purity


def classify(blocks: Sequence[ExtractedBlock]) -> DocumentLanguage:
    """Gán nhãn ngôn ngữ cho cả tài liệu và từng khối."""
    if not blocks:
        return DocumentLanguage(language="unknown", block_languages=[])

    block_languages = [detect_language(b.text) for b in blocks]

    vi_chars = sum(len(b.text) for b, l in zip(blocks, block_languages) if l == "vi")
    en_chars = sum(len(b.text) for b, l in zip(blocks, block_languages) if l == "en")
    total = vi_chars + en_chars

    if total == 0:
        return DocumentLanguage(
            language="unknown",
            block_languages=block_languages,
            notes=["Không nhận ra ngôn ngữ nào — các đoạn có thể quá ngắn."],
        )

    vi_ratio = vi_chars / total
    en_ratio = en_chars / total

    # Một ngôn ngữ áp đảo -> tài liệu đơn ngữ.
    if vi_ratio < _MIN_SIDE_RATIO or en_ratio < _MIN_SIDE_RATIO:
        return DocumentLanguage(
            language="vi" if vi_ratio >= en_ratio else "en",
            block_languages=block_languages,
            vi_char_ratio=vi_ratio,
            en_char_ratio=en_ratio,
        )

    # Cả hai ngôn ngữ đều nhiều: song song hay chỉ trộn lẫn?
    split_index, purity = _best_split(block_languages)
    if split_index is not None and purity >= _MIN_SPLIT_PURITY:
        return DocumentLanguage(
            language="parallel",
            block_languages=block_languages,
            vi_char_ratio=vi_ratio,
            en_char_ratio=en_ratio,
            split_index=split_index,
            split_purity=purity,
            notes=[
                "Tài liệu có cả bản Việt và bản Anh của cùng nội dung — dùng được làm "
                "bản dịch tham chiếu của người thật và để trích cặp thuật ngữ."
            ],
        )

    return DocumentLanguage(
        language="mixed",
        block_languages=block_languages,
        vi_char_ratio=vi_ratio,
        en_char_ratio=en_ratio,
        split_purity=purity,
        notes=[
            "Hai thứ tiếng trộn lẫn chứ không phải bản dịch song song — "
            "không trích cặp thuật ngữ từ tài liệu này."
        ],
    )


def split_parallel(
    blocks: Sequence[ExtractedBlock], info: DocumentLanguage
) -> tuple[str, str]:
    """Tách tài liệu song ngữ thành (văn bản tiếng Việt, văn bản tiếng Anh).

    Dùng cho việc trích cặp thuật ngữ ở Giai đoạn 2. Trả về hai chuỗi rỗng nếu
    tài liệu không phải song ngữ song song.
    """
    if not info.is_parallel or info.split_index is None:
        return "", ""

    vi_parts: list[str] = []
    en_parts: list[str] = []
    for block, lang in zip(blocks, info.block_languages):
        if lang == "vi":
            vi_parts.append(block.text)
        elif lang == "en":
            en_parts.append(block.text)

    return "\n\n".join(vi_parts), "\n\n".join(en_parts)
