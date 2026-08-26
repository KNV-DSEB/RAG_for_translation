"""C9 — nhãn ⭐⭐⭐ chỉ được gắn khi câu THẬT SỰ xuất hiện nguyên văn trong tài liệu.

Vào:  hai chuỗi văn bản.
Ra:   assert. Không chạm cơ sở dữ liệu, không gọi mạng.

Cách đo cũ là tỷ lệ TỪ VỰNG trùng nhau theo tập hợp, ngưỡng 0.6 — hỏng theo đúng chiều
nguy hiểm nhất: mẫu số là số từ của MỘT CÂU còn đống rơm là TOÀN BỘ phần tiếng Anh của
tài liệu, nên tài liệu càng dài càng dễ dương tính giả. Mà tài liệu dài mới là loại hay
gặp trong nghề.
"""

from __future__ import annotations

import pytest

from backend.simulation.generator import _is_verbatim_in, _normalize_for_verbatim

# Một tài liệu song ngữ thật sẽ dài và đầy từ vựng hành chính lặp đi lặp lại.
DOCUMENT = """
On behalf of Latter-Day Saint Charities, I would like to express our sincere gratitude
to the People's Committee of Thu Cuc commune and the Department of Foreign Affairs of
Phu Tho province for their close cooperation throughout this project. The total funding
value of this project is six billion seven hundred and eighty million Vietnamese dong,
supporting the construction of houses for 113 disadvantaged households in Thu Cuc commune.
We look forward to continuing this partnership in the years ahead.
"""


def test_c9_exact_sentence_is_recognised() -> None:
    """Câu lấy đúng nguyên văn thì phải được công nhận."""
    lifted = "The total funding value of this project is six billion seven hundred and eighty million Vietnamese dong"
    assert _is_verbatim_in(lifted, DOCUMENT)


def test_c9_punctuation_and_spacing_differences_are_tolerated() -> None:
    """Khác dấu câu và khoảng trắng vẫn là cùng một câu — không bắt bẻ vụn vặt."""
    lifted = "the  total FUNDING value, of this project:   is six billion"
    assert _is_verbatim_in(lifted, DOCUMENT)


def test_c9_ai_sentence_sharing_vocabulary_is_rejected() -> None:
    """ĐÂY là ca mà cách đo cũ làm hỏng.

    Câu dưới do AI viết, dùng toàn từ vựng có sẵn trong tài liệu — "project", "funding",
    "households", "Thu Cuc", "cooperation" — nhưng KHÔNG phải câu trong tài liệu. Cách đo
    theo tập hợp từ sẽ cho nó vượt ngưỡng 0.6 và gắn nhãn "bản dịch của người thật".
    """
    ai_written = (
        "This project provides funding for households in Thu Cuc commune, and we value "
        "the cooperation of the provincial Department of Foreign Affairs."
    )
    assert not _is_verbatim_in(ai_written, DOCUMENT)


def test_c9_reordered_words_are_rejected() -> None:
    """Đảo thứ tự từ thì đổi nghĩa — với phiên dịch, đó là sai chứ không phải gần đúng."""
    reordered = "six billion Vietnamese dong is the total funding value of this project"
    assert not _is_verbatim_in(reordered, DOCUMENT)


def test_c9_longer_document_does_not_make_false_positives_easier() -> None:
    """Bất biến quan trọng nhất: tài liệu dài ra KHÔNG làm câu sai dễ được công nhận hơn.

    Cách đo cũ có đúng tính chất ngược lại, và đó là lý do phải bỏ nó.
    """
    ai_written = (
        "The commune received funding from the organisation for the construction of houses."
    )
    short_doc = DOCUMENT
    long_doc = DOCUMENT * 50

    assert not _is_verbatim_in(ai_written, short_doc)
    assert not _is_verbatim_in(ai_written, long_doc)


@pytest.mark.parametrize("empty", ["", "   ", "\n"])
def test_c9_empty_input_is_never_verbatim(empty: str) -> None:
    """Chuỗi rỗng là chuỗi con của mọi thứ — phải chặn tay, nếu không mọi lượt đều ⭐⭐⭐."""
    assert not _is_verbatim_in(empty, DOCUMENT)
    assert not _is_verbatim_in("bất kỳ", empty)


def test_c9_normalisation_is_stable() -> None:
    assert _normalize_for_verbatim("  Thu Cúc,  Phú Thọ!! ") == "thu cúc phú thọ"
