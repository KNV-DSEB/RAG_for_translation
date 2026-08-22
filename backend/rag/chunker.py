"""Cắt tài liệu thành đoạn để lập chỉ mục, GIỮ NGUYÊN vị trí gốc.

Input:  danh sách `ExtractedBlock` + nhãn ngôn ngữ từng khối.
Output: danh sách `Chunk` có `locator` mô tả đúng vị trí trong tệp gốc.

Vị trí là thứ làm nên trích dẫn bấm mở được (spec A1.3). Nếu cắt đoạn mà đánh mất vị trí
thì câu trả lời có nguồn cũng không kiểm chứng được — nên mọi bước ở đây đều mang locator theo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from backend.config import settings
from backend.rag.extractors import ExtractedBlock
from backend.rag.language import LangCode

# Tách câu: kết thúc bằng . ! ? … theo sau là khoảng trắng và chữ hoa/số.
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZĐÀ-Ỹ0-9“\"(])")


@dataclass
class Chunk:
    text: str
    locator: str
    lang: LangCode
    block_start: int
    block_end: int


def _locator_range(locators: Sequence[str]) -> str:
    """Gộp nhiều vị trí thành một chuỗi ngắn: 'trang 3' hoặc 'đoạn 12–15'."""
    if not locators:
        return ""
    first, last = locators[0], locators[-1]
    if first == last:
        return first

    # Cùng loại đơn vị ("trang" / "đoạn") thì rút thành khoảng.
    m1 = re.match(r"(\D+)\s*(\d+)", first)
    m2 = re.match(r"(\D+)\s*(\d+)", last)
    if m1 and m2 and m1.group(1).strip() == m2.group(1).strip():
        return f"{m1.group(1).strip()} {m1.group(2)}–{m2.group(2)}"
    return f"{first} → {last}"


def _split_long_text(text: str, limit: int) -> list[str]:
    """Khối đơn lẻ dài quá giới hạn thì cắt theo câu, không cắt giữa chừng câu."""
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_RE.split(text):
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        # Câu đơn lẻ vẫn dài hơn giới hạn (bảng biểu, danh sách dài) → cắt cứng.
        while len(sentence) > limit:
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        current = sentence
    if current:
        pieces.append(current)
    return pieces


def chunk_document(
    blocks: Sequence[ExtractedBlock],
    block_languages: Sequence[LangCode],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Gom các khối liền nhau thành đoạn cỡ `chunk_size`, chồng lấn `overlap` ký tự."""
    size = chunk_size or settings.chunk_size_chars
    lap = overlap if overlap is not None else settings.chunk_overlap_chars

    if not blocks:
        return []

    langs = list(block_languages) + ["unknown"] * (len(blocks) - len(block_languages))
    chunks: list[Chunk] = []

    buffer_texts: list[str] = []
    buffer_locators: list[str] = []
    buffer_langs: list[LangCode] = []
    start_index = 0

    def flush(end_index: int) -> None:
        if not buffer_texts:
            return
        text = "\n\n".join(buffer_texts).strip()
        if not text:
            return
        # Ngôn ngữ của đoạn = ngôn ngữ chiếm đa số trong các khối hợp thành.
        known = [l for l in buffer_langs if l in ("vi", "en")]
        lang: LangCode = max(set(known), key=known.count) if known else "unknown"
        chunks.append(
            Chunk(
                text=text,
                locator=_locator_range(buffer_locators),
                lang=lang,
                block_start=start_index,
                block_end=end_index,
            )
        )

    for index, block in enumerate(blocks):
        for piece in _split_long_text(block.text, size):
            current_len = sum(len(t) for t in buffer_texts)
            if buffer_texts and current_len + len(piece) > size:
                flush(index)
                # Chồng lấn: giữ lại phần đuôi của đoạn vừa xong để không đứt mạch ngữ nghĩa.
                if lap > 0:
                    tail = "\n\n".join(buffer_texts)[-lap:]
                    buffer_texts = [tail]
                    buffer_locators = buffer_locators[-1:]
                    buffer_langs = buffer_langs[-1:]
                else:
                    buffer_texts, buffer_locators, buffer_langs = [], [], []
                start_index = index

            if not buffer_texts:
                start_index = index
            buffer_texts.append(piece)
            buffer_locators.append(block.locator)
            buffer_langs.append(langs[index])

    flush(len(blocks) - 1)
    return chunks
