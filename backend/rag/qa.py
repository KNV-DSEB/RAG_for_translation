"""Hỏi đáp trên tài liệu: truy hồi ngữ cảnh → hỏi LLM → trả lời KÈM TRÍCH DẪN.

Input:  workspace_id + câu hỏi (tiếng Việt hoặc tiếng Anh) + phạm vi tài liệu tuỳ chọn.
Output: `Answer` gồm câu trả lời, danh sách trích dẫn trỏ đúng tệp và vị trí, phần suy luận
        tách riêng, và mức độ chắc chắn.

Ba ràng buộc nghiệp vụ quan trọng nhất:
    A1.3 — mọi câu trả lời phải có ít nhất một trích dẫn trỏ đúng tệp và đúng đoạn
    A1.4 — không có trong tài liệu thì nói KHÔNG CÓ, tuyệt đối không bịa
    A1.6 — câu hỏi suy luận phải tách rõ phần đọc được từ tài liệu và phần suy đoán

Chỉ các đoạn ngữ cảnh đã truy hồi mới được gửi ra ngoài, không bao giờ gửi cả tài liệu (§7.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Sequence

from pydantic import Field

from backend.config import settings
from backend.db import get_conn
from backend.rag import store
from backend.rag.language import detect_language
from backend.security import llm
from backend.security.llm import LLMSchema

# Khoảng cách cosine lớn hơn mức này nghĩa là ngữ cảnh tìm được đã khá xa câu hỏi.
WEAK_CONTEXT_DISTANCE = 0.75


class QaLLMOut(LLMSchema):
    """Cấu trúc JSON bắt buộc mà LLM phải trả về.

    Mọi trường đều BẮT BUỘC (không đặt default). Khi để trường có giá trị mặc định,
    Gemini coi đó là tuỳ chọn và hay bỏ qua — đo thực tế: câu hỏi suy luận bị nhồi hết
    vào `answer` còn `inference` để rỗng, làm mất ranh giới giữa dữ kiện và suy đoán.
    """

    found: bool = Field(description="Tài liệu có chứa thông tin trả lời được câu hỏi không")
    answer: str = Field(description="Câu trả lời, cùng ngôn ngữ với câu hỏi")
    used_context_ids: list[int] = Field(
        description="Số thứ tự các đoạn ngữ cảnh đã thực sự dùng. Bắt buộc khi found=true"
    )
    key_figures: list[str] = Field(
        description=(
            "MỌI số liệu cụ thể liên quan tới câu hỏi tìm thấy trong ngữ cảnh: số tiền kèm "
            "đơn vị, số lượng, ngày tháng, số hiệu văn bản, tên riêng, chức danh. "
            "Danh sách rỗng nếu ngữ cảnh không có số liệu nào liên quan."
        )
    )
    is_inferential: bool = Field(
        description="Câu hỏi có yêu cầu dự đoán/suy luận vượt ra ngoài dữ kiện tài liệu không"
    )
    inference: str = Field(
        description=(
            "Phần suy đoán của bạn, tách hẳn khỏi answer. BẮT BUỘC có nội dung khi "
            "is_inferential=true, và phải nêu suy đoán dựa trên căn cứ nào. "
            "Chuỗi rỗng khi is_inferential=false."
        )
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Mức độ chắc chắn của câu trả lời"
    )


@dataclass
class Citation:
    document_id: int
    filename: str
    locator: str
    snippet: str
    chunk_id: int


@dataclass
class Answer:
    question: str
    answer: str
    citations: list[Citation] = field(default_factory=list)
    inference: str = ""
    # Số liệu tách riêng để chuyên gia soi nhanh — với phiên dịch, sai một con số
    # là hỏng cả buổi, nên không để chúng chìm trong văn xuôi.
    key_figures: list[str] = field(default_factory=list)
    confidence: str = "medium"
    found: bool = True
    warnings: list[str] = field(default_factory=list)


SYSTEM_INSTRUCTION = """\
Bạn hỗ trợ một chuyên gia phiên dịch Việt–Anh chuẩn bị cho buổi dịch. Bạn trả lời DỰA HOÀN TOÀN
trên các đoạn tài liệu được cung cấp.

Quy tắc bắt buộc:
1. CHỈ dùng thông tin có trong các đoạn ngữ cảnh. Tuyệt đối KHÔNG dùng kiến thức bên ngoài để
   khẳng định điều gì về khách hàng, dự án, con số, hay ngày tháng.
2. Nếu các đoạn ngữ cảnh không chứa thông tin trả lời được, đặt found=false và nói rõ là không
   tìm thấy trong tài liệu. KHÔNG được đoán, KHÔNG được bịa ra số liệu hay tên riêng.
3. Ghi số thứ tự các đoạn bạn thực sự dùng vào used_context_ids.
4. Nếu câu hỏi mang tính DỰ ĐOÁN hoặc SUY LUẬN (ví dụ "dự đoán nội dung sẽ trao đổi",
   "buổi làm việc có thể bàn gì"), thì đặt is_inferential=true và:
   - trường answer CHỈ chứa những gì ĐỌC ĐƯỢC từ tài liệu, không thêm suy đoán;
   - toàn bộ phần suy đoán của bạn để riêng trong trường inference, nêu rõ dựa trên căn cứ nào.
   Không được để inference rỗng khi is_inferential=true.
5. Trả lời cùng ngôn ngữ với câu hỏi. Số liệu và tên riêng phải giữ nguyên chính xác như tài liệu.
6. QUAN TRỌNG — người dùng là PHIÊN DỊCH, bỏ sót số liệu là lỗi nghiêm trọng: nếu trong các đoạn
   ngữ cảnh có con số cụ thể liên quan tới câu hỏi (số tiền, số lượng, tỷ lệ, diện tích, ngày
   tháng, số hiệu văn bản, tên riêng, chức danh) thì PHẢI nêu đầy đủ và chính xác từng con số đó,
   kèm đơn vị. Không được tóm tắt chung chung kiểu "một khoản tài trợ lớn" khi tài liệu ghi rõ số.
7. Trả về JSON thuần đúng schema, không kèm giải thích, không bọc trong dấu ```."""


def _fetch_chunks(chunk_ids: Sequence[int]) -> dict[int, dict[str, object]]:
    """Lấy văn bản gốc + vị trí + tên tệp từ SQLite (nguồn sự thật cho trích dẫn)."""
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.id, c.text, c.locator, c.document_id, d.filename
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id IN ({placeholders})
            """,
            tuple(chunk_ids),
        ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def _build_context(
    hits: Sequence[store.SearchHit], chunks: dict[int, dict[str, object]]
) -> tuple[str, list[dict[str, object]]]:
    """Dựng khối ngữ cảnh đánh số, và bảng tra ngược từ số thứ tự về đoạn thật."""
    parts: list[str] = []
    ordered: list[dict[str, object]] = []

    for index, hit in enumerate(hits, start=1):
        chunk = chunks.get(hit.chunk_id)
        if chunk is None:
            continue
        ordered.append({**chunk, "context_id": index, "distance": hit.distance})
        parts.append(
            f"[Đoạn {index}] (tệp: {chunk['filename']} · {chunk['locator']})\n{chunk['text']}"
        )

    return "\n\n---\n\n".join(parts), ordered


def ask(
    workspace_id: int,
    question: str,
    document_ids: Sequence[int] | None = None,
    save_history: bool = True,
) -> Answer:
    """Trả lời một câu hỏi trên tài liệu của hồ sơ khách hàng."""
    question = question.strip()
    if not question:
        raise ValueError("Câu hỏi đang để trống.")

    hits = store.search(
        workspace_id=workspace_id,
        query=question,
        top_k=settings.retrieval_top_k,
        document_ids=document_ids,
    )

    if not hits:
        answer = Answer(
            question=question,
            answer=(
                "Không tìm thấy thông tin này trong tài liệu đã nạp. "
                "Bạn có thể nạp thêm tài liệu, hoặc thử tìm trên web ở tab Nghiên cứu."
            ),
            confidence="not_found",
            found=False,
        )
        if save_history:
            _save_history(workspace_id, answer)
        return answer

    chunks = _fetch_chunks([h.chunk_id for h in hits])
    context_text, ordered = _build_context(hits, chunks)

    warnings: list[str] = []
    best_distance = min(h.distance for h in hits)
    if best_distance > WEAK_CONTEXT_DISTANCE:
        warnings.append(
            "Câu trả lời dựa trên ngữ cảnh hạn chế — nên kiểm tra lại nguồn trước khi dùng."
        )

    lang = detect_language(question)
    language_hint = "tiếng Việt" if lang != "en" else "tiếng Anh"

    prompt = (
        f"CÁC ĐOẠN TÀI LIỆU:\n\n{context_text}\n\n"
        f"---\n\nCÂU HỎI: {question}\n\n"
        f"Trả lời bằng {language_hint}. Nhớ: chỉ dùng thông tin trong các đoạn trên."
    )

    result = llm.generate_json(
        module="rag.qa",
        prompt=prompt,
        schema=QaLLMOut,
        workspace_id=workspace_id,
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,
        summary=f"Hỏi đáp tài liệu: {question[:80]}",
    )

    # Ánh xạ số thứ tự đoạn LLM đã dùng về trích dẫn thật.
    by_context_id = {int(item["context_id"]): item for item in ordered}
    citations: list[Citation] = []
    for context_id in result.used_context_ids:
        item = by_context_id.get(int(context_id))
        if item is None:
            continue
        text = str(item["text"])
        citations.append(
            Citation(
                document_id=int(item["document_id"]),
                filename=str(item["filename"]),
                locator=str(item["locator"]),
                snippet=text[:400] + ("…" if len(text) > 400 else ""),
                chunk_id=int(item["id"]),
            )
        )

    # Có trả lời khẳng định thì phải có trích dẫn. LLM quên ghi thì lấy đoạn gần nhất
    # làm trích dẫn, và nói rõ là do hệ thống suy ra để chuyên gia còn kiểm.
    if result.found and not citations and ordered:
        item = ordered[0]
        text = str(item["text"])
        citations.append(
            Citation(
                document_id=int(item["document_id"]),
                filename=str(item["filename"]),
                locator=str(item["locator"]),
                snippet=text[:400] + ("…" if len(text) > 400 else ""),
                chunk_id=int(item["id"]),
            )
        )
        warnings.append(
            "Mô hình không chỉ rõ đoạn nguồn — đây là đoạn khớp nhất, nên tự kiểm lại."
        )

    # Câu hỏi suy luận mà không tách phần suy đoán ra thì ranh giới dữ kiện/suy đoán bị mờ.
    if result.is_inferential and not result.inference.strip():
        warnings.append(
            "Đây là câu hỏi suy luận nhưng mô hình không tách riêng phần suy đoán — "
            "hãy coi toàn bộ câu trả lời là có phần suy diễn và tự kiểm lại nguồn."
        )

    answer = Answer(
        question=question,
        answer=result.answer.strip(),
        citations=citations,
        inference=result.inference.strip(),
        key_figures=[f.strip() for f in result.key_figures if f.strip()],
        confidence="not_found" if not result.found else result.confidence,
        found=result.found,
        warnings=warnings,
    )
    if save_history:
        _save_history(workspace_id, answer)
    return answer


def _save_history(workspace_id: int, answer: Answer) -> None:
    citations = [
        {
            "document_id": c.document_id,
            "filename": c.filename,
            "locator": c.locator,
            "snippet": c.snippet,
            "chunk_id": c.chunk_id,
        }
        for c in answer.citations
    ]
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO qa_history
                (workspace_id, question, answer, citations, inference_part, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                answer.question,
                answer.answer,
                json.dumps(citations, ensure_ascii=False),
                answer.inference or None,
                answer.confidence,
            ),
        )


def history(workspace_id: int, limit: int = 50) -> list[dict[str, object]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM qa_history WHERE workspace_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (workspace_id, limit),
        ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["citations"] = json.loads(str(item.get("citations") or "[]"))
        items.append(item)
    return items
