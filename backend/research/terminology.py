"""Trích thuật ngữ song ngữ từ BA nguồn, mỗi nguồn một mức độ tin cậy.

Input:  tài liệu đã nạp của hồ sơ + kết quả tìm kiếm web + chủ đề buổi làm việc.
Output: các dòng trong bảng `glossary`, kèm thống kê thêm mới / trùng / xung đột.

Thứ tự tin cậy (quyết định ai thắng khi xung đột bản dịch):
    1. `expert_edited`     — chuyên gia đã sửa tay, KHÔNG BAO GIỜ bị ghi đè (spec A2.13)
    2. `aligned_from_parallel` — trích từ tài liệu SONG NGỮ SONG SONG.

       Tên cũ là `human_translated`, và nó nói quá: hai bản tài liệu đúng là do người
       dịch, nhưng việc GHÉP thuật ngữ A ↔ thuật ngữ B là do LLM suy ra. Nhãn cũ tuyên
       bố một mức xác nhận chưa từng xảy ra. Thứ tự ưu tiên giữ nguyên — cặp ghép từ
       tài liệu người dịch vẫn đáng tin hơn máy suy đoán từ một ngôn ngữ.
    3. `machine_guess`     — suy đoán từ tài liệu một ngôn ngữ hoặc từ web

Thuật ngữ mới vào bảng ở trạng thái `auto` và DÙNG ĐƯỢC NGAY, không có bước duyệt chặn
đường đi (quyết định Q9: tự nhận hết, sửa sau).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from backend.db import get_conn
from backend.research.search import SearchResult
from backend.security import llm
from backend.security.llm import LLMSchema

CATEGORIES = [
    "pháp lý",
    "kỹ thuật",
    "thương mại",
    "tài chính",
    "chính sách",
    "tên riêng/tổ chức",
    "viết tắt",
    "thành ngữ",
]

Confidence = Literal["aligned_from_parallel", "machine_guess"]

# Cắt bớt văn bản đưa vào LLM để không vượt trần payload của cửa egress.
MAX_TEXT_CHARS = 14_000
MAX_WEB_CHARS = 12_000

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


class TermOut(LLMSchema):
    term_vi: str = Field(description="Thuật ngữ tiếng Việt")
    term_en: str = Field(description="Thuật ngữ tiếng Anh tương ứng")
    pronunciation: str = Field(
        description=(
            "Gợi ý cách đọc, CHỈ điền với tên riêng nước ngoài, tên tổ chức, hoặc từ viết tắt "
            "(ví dụ: Latter-Day Saint Charities → 'Lát-tơ Đây Xây-nt Cha-ri-tis'). "
            "Chuỗi rỗng với thuật ngữ thông thường."
        )
    )
    definition: str = Field(description="Định nghĩa ngắn một câu, bằng tiếng Việt")
    category: str = Field(description=f"Một trong: {', '.join(CATEGORIES)}")


class TermListOut(LLMSchema):
    terms: list[TermOut]
    notes: str = Field(description="Ghi chú nếu văn bản quá ít thuật ngữ chuyên ngành")


@dataclass
class TermRecord:
    """Một thuật ngữ ứng viên, chưa vào bảng."""

    term_vi: str
    term_en: str
    pronunciation: str
    definition: str
    category: str
    confidence: Confidence
    source_type: str  # 'document' | 'web' | 'expert'
    source_ref: str


@dataclass
class UpsertStats:
    added: int = 0
    updated: int = 0
    frequency_bumped: int = 0
    conflicts: int = 0
    skipped_expert: int = 0
    notes: list[str] = field(default_factory=list)


def normalize_term(text: str) -> str:
    """Chuẩn hoá để so trùng: NFC, bỏ dấu câu, gộp khoảng trắng, hạ chữ thường."""
    normalized = unicodedata.normalize("NFC", text).strip().lower()
    normalized = _PUNCT_RE.sub(" ", normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


# ============================== Prompt ==============================

_COMMON_RULES = f"""\
Bạn trích thuật ngữ chuyên ngành song ngữ Việt–Anh cho một chuyên gia phiên dịch.

Nguyên tắc:
- CHỈ lấy thuật ngữ CHUYÊN NGÀNH thực sự cần tra: từ pháp lý, kỹ thuật, tài chính, chính sách,
  tên tổ chức, từ viết tắt, thành ngữ hành chính. KHÔNG lấy từ thông dụng ("hôm nay", "rất vui").
- Ưu tiên thuật ngữ liên quan tới chủ đề buổi làm việc.
- Giữ nguyên chính xác cách viết trong văn bản, cả chữ tiếng Việt có dấu.
- Với tên riêng nước ngoài, tên tổ chức và từ viết tắt: BẮT BUỘC điền pronunciation
  (gợi ý cách đọc), vì chuyên gia phải đọc to được trong buổi dịch.
- category phải là một trong: {', '.join(CATEGORIES)}
Trả về JSON thuần đúng schema."""

PARALLEL_SYSTEM = (
    _COMMON_RULES
    + """

ĐẶC BIỆT QUAN TRỌNG: bạn nhận được HAI bản của CÙNG MỘT nội dung — bản tiếng Việt và bản
tiếng Anh, do người thật dịch. Hãy ĐỐI CHIẾU hai bản để lấy ra cặp thuật ngữ tương ứng.
Đây là cặp dịch đáng tin nhất, nên chỉ ghép khi bạn thực sự thấy hai từ ứng với nhau trong
hai bản, không được tự dịch thêm."""
)

MONO_SYSTEM = (
    _COMMON_RULES
    + """

Văn bản chỉ có một ngôn ngữ. Với mỗi thuật ngữ tìm được, bạn tự đưa ra bản dịch phía còn lại
theo cách dùng phổ biến trong ngành. Nếu không chắc bản dịch, vẫn ghi nhưng chọn cách dịch
thông dụng nhất."""
)

WEB_SYSTEM = (
    _COMMON_RULES
    + """

Nguồn là các đoạn trích từ web. Chỉ lấy thuật ngữ liên quan tới chủ đề buổi làm việc và tới
lĩnh vực hoạt động của các bên. Bỏ qua nội dung quảng cáo hoặc điều hướng trang."""
)


# ============================== Trích xuất ==============================


def extract_from_parallel(
    vi_text: str,
    en_text: str,
    topic: str,
    source_ref: str,
    workspace_id: int | None,
) -> list[TermRecord]:
    """Trích cặp thuật ngữ từ tài liệu song ngữ song song → độ tin `aligned_from_parallel`."""
    prompt = (
        f"CHỦ ĐỀ BUỔI LÀM VIỆC: {topic}\n\n"
        f"=== BẢN TIẾNG VIỆT ===\n{vi_text[:MAX_TEXT_CHARS // 2]}\n\n"
        f"=== BẢN TIẾNG ANH (cùng nội dung) ===\n{en_text[:MAX_TEXT_CHARS // 2]}\n\n"
        "Đối chiếu hai bản, trích các cặp thuật ngữ chuyên ngành tương ứng."
    )
    result = llm.generate_json(
        module="research.terms.parallel",
        prompt=prompt,
        schema=TermListOut,
        workspace_id=workspace_id,
        system_instruction=PARALLEL_SYSTEM,
        temperature=0.2,
        summary=f"Trích thuật ngữ từ tài liệu song ngữ: {source_ref}",
        tier="light",
    )
    return [
        TermRecord(
            term_vi=t.term_vi.strip(),
            term_en=t.term_en.strip(),
            pronunciation=t.pronunciation.strip(),
            definition=t.definition.strip(),
            category=t.category.strip(),
            confidence="aligned_from_parallel",
            source_type="document",
            source_ref=source_ref,
        )
        for t in result.terms
        if t.term_vi.strip() and t.term_en.strip()
    ]


def extract_from_monolingual(
    text: str,
    lang: str,
    topic: str,
    source_ref: str,
    workspace_id: int | None,
) -> list[TermRecord]:
    """Trích thuật ngữ từ tài liệu một ngôn ngữ → độ tin `machine_guess`."""
    lang_label = "tiếng Việt" if lang == "vi" else "tiếng Anh"
    prompt = (
        f"CHỦ ĐỀ BUỔI LÀM VIỆC: {topic}\n\n"
        f"=== VĂN BẢN ({lang_label}) ===\n{text[:MAX_TEXT_CHARS]}\n\n"
        "Trích thuật ngữ chuyên ngành và đưa ra bản dịch phía ngôn ngữ còn lại."
    )
    result = llm.generate_json(
        module="research.terms.document",
        prompt=prompt,
        schema=TermListOut,
        workspace_id=workspace_id,
        system_instruction=MONO_SYSTEM,
        temperature=0.25,
        summary=f"Trích thuật ngữ từ tài liệu {lang_label}: {source_ref}",
        tier="light",
    )
    return [
        TermRecord(
            term_vi=t.term_vi.strip(),
            term_en=t.term_en.strip(),
            pronunciation=t.pronunciation.strip(),
            definition=t.definition.strip(),
            category=t.category.strip(),
            confidence="machine_guess",
            source_type="document",
            source_ref=source_ref,
        )
        for t in result.terms
        if t.term_vi.strip() and t.term_en.strip()
    ]


def extract_from_web(
    results: list[SearchResult],
    topic: str,
    workspace_id: int | None,
) -> list[TermRecord]:
    """Trích thuật ngữ từ kết quả tìm kiếm → độ tin `machine_guess`, nguồn là URL."""
    if not results:
        return []

    blocks: list[str] = []
    used = 0
    url_by_index: dict[int, str] = {}
    for index, item in enumerate(results, start=1):
        block = f"[Nguồn {index}] {item.title}\n{item.snippet}"
        if used + len(block) > MAX_WEB_CHARS:
            break
        blocks.append(block)
        url_by_index[index] = item.url
        used += len(block)

    prompt = (
        f"CHỦ ĐỀ BUỔI LÀM VIỆC: {topic}\n\n"
        f"=== CÁC ĐOẠN TRÍCH TỪ WEB ===\n" + "\n\n".join(blocks) + "\n\n"
        "Trích thuật ngữ chuyên ngành liên quan tới chủ đề."
    )
    result = llm.generate_json(
        module="research.terms.web",
        prompt=prompt,
        schema=TermListOut,
        workspace_id=workspace_id,
        system_instruction=WEB_SYSTEM,
        temperature=0.25,
        summary=f"Trích thuật ngữ từ {len(blocks)} nguồn web",
        tier="light",
    )
    ref = f"web ({len(blocks)} nguồn)"
    return [
        TermRecord(
            term_vi=t.term_vi.strip(),
            term_en=t.term_en.strip(),
            pronunciation=t.pronunciation.strip(),
            definition=t.definition.strip(),
            category=t.category.strip(),
            confidence="machine_guess",
            source_type="web",
            source_ref=ref,
        )
        for t in result.terms
        if t.term_vi.strip() and t.term_en.strip()
    ]


# ============================== Ghi vào bảng glossary ==============================

_RANK = {"expert_edited": 3, "aligned_from_parallel": 2, "machine_guess": 1}


def _rank_of(status: str, confidence: str) -> int:
    if status == "expert_edited":
        return _RANK["expert_edited"]
    return _RANK.get(confidence, 1)


def upsert_terms(workspace_id: int, terms: list[TermRecord]) -> UpsertStats:
    """Ghi thuật ngữ vào bảng, chống trùng và xử lý xung đột theo thứ tự ưu tiên."""
    stats = UpsertStats()

    with get_conn() as conn:
        for term in terms:
            key = normalize_term(term.term_vi)
            if not key:
                continue

            existing = conn.execute(
                "SELECT * FROM glossary WHERE workspace_id = ? AND term_vi_norm = ?",
                (workspace_id, key),
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO glossary
                        (workspace_id, term_vi, term_vi_norm, term_en, pronunciation,
                         definition, category, confidence, status, source_type, source_ref,
                         frequency)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto', ?, ?, 1)
                    """,
                    (
                        workspace_id, term.term_vi, key, term.term_en, term.pronunciation or None,
                        term.definition or None, term.category, term.confidence,
                        term.source_type, term.source_ref,
                    ),
                )
                stats.added += 1
                continue

            old_status = str(existing["status"])
            old_confidence = str(existing["confidence"])
            same_translation = normalize_term(str(existing["term_en"])) == normalize_term(
                term.term_en
            )

            # Bản dịch giống nhau: chỉ tăng tần suất, và bổ sung cách đọc nếu trước đó thiếu.
            if same_translation:
                conn.execute(
                    """
                    UPDATE glossary
                    SET frequency = frequency + 1,
                        pronunciation = COALESCE(NULLIF(pronunciation, ''), ?),
                        definition = COALESCE(NULLIF(definition, ''), ?),
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (term.pronunciation or None, term.definition or None, int(existing["id"])),
                )
                stats.frequency_bumped += 1
                continue

            # Bản dịch khác nhau -> so thứ hạng tin cậy.
            old_rank = _rank_of(old_status, old_confidence)
            new_rank = _RANK.get(term.confidence, 1)

            if new_rank > old_rank:
                # Nguồn mới đáng tin hơn (ví dụ: bản dịch người thật thay cho máy suy đoán).
                conn.execute(
                    """
                    UPDATE glossary
                    SET term_en = ?, pronunciation = COALESCE(NULLIF(?, ''), pronunciation),
                        definition = COALESCE(NULLIF(?, ''), definition),
                        category = ?, confidence = ?, source_type = ?, source_ref = ?,
                        frequency = frequency + 1, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (
                        term.term_en, term.pronunciation, term.definition, term.category,
                        term.confidence, term.source_type, term.source_ref, int(existing["id"]),
                    ),
                )
                stats.updated += 1
                continue

            # Giữ bản cũ, nhưng GHI LẠI XUNG ĐỘT để chuyên gia tự chọn (spec A2.13).
            already = conn.execute(
                """
                SELECT 1 FROM glossary_conflicts
                WHERE glossary_id = ? AND proposed_term_en = ? AND resolved = 0
                """,
                (int(existing["id"]), term.term_en),
            ).fetchone()
            if already is None:
                conn.execute(
                    """
                    INSERT INTO glossary_conflicts
                        (glossary_id, proposed_term_en, proposed_definition, source_ref, confidence)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        int(existing["id"]), term.term_en, term.definition or None,
                        term.source_ref, term.confidence,
                    ),
                )
                stats.conflicts += 1
            if old_status == "expert_edited":
                stats.skipped_expert += 1

    return stats


# ============================== Lấy văn bản tài liệu để trích ==============================


def document_texts(workspace_id: int) -> list[dict[str, object]]:
    """Gom văn bản từng tài liệu đã nạp, tách sẵn phần Việt/Anh với tài liệu song ngữ."""
    with get_conn() as conn:
        documents = conn.execute(
            """
            SELECT id, filename, language FROM documents
            WHERE workspace_id = ? AND status = 'ready'
            ORDER BY id
            """,
            (workspace_id,),
        ).fetchall()

        items: list[dict[str, object]] = []
        for doc in documents:
            chunks = conn.execute(
                "SELECT text, lang FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
                (int(doc["id"]),),
            ).fetchall()

            vi_parts = [str(c["text"]) for c in chunks if str(c["lang"]) == "vi"]
            en_parts = [str(c["text"]) for c in chunks if str(c["lang"]) == "en"]
            all_parts = [str(c["text"]) for c in chunks]

            items.append(
                {
                    "document_id": int(doc["id"]),
                    "filename": str(doc["filename"]),
                    "language": str(doc["language"]),
                    "vi_text": "\n\n".join(vi_parts),
                    "en_text": "\n\n".join(en_parts),
                    "full_text": "\n\n".join(all_parts),
                }
            )
    return items
