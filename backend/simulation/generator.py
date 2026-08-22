"""Sinh kịch bản mock buổi dịch, có KIỂM TRA trước khi trả về giao diện.

Input:  workspace_id + cấu hình buổi (hình thức, độ khó, số lượt).
Output: bản ghi `mock_sessions` + các dòng `mock_turns`, kèm cảnh báo nếu chưa đạt chuẩn.

Kiểm tra là phần quan trọng nhất ở đây. LLM rất hay sinh kịch bản 6 lượt thay vì 8, hoặc
nhồi thuật ngữ thành danh sách, hoặc viết lượt một câu. Không kiểm thì chuyên gia luyện trên
kịch bản sai chuẩn mà không biết. Không đạt thì tự sinh lại MỘT lần rồi mới hiện, kèm ghi chú
nếu vẫn chưa đạt (spec edge case §4.3).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field

from backend.config import settings
from backend.db import get_conn
from backend.research.terminology import normalize_term
from backend.security import llm
from backend.security.llm import LLMSchema
from backend.simulation.prompts import SCRIPT_SYSTEM, build_script_prompt

# Số thuật ngữ tối thiểu phải xuất hiện trong cả kịch bản, tính theo số lượt.
MIN_TERMS_RATIO = 0.75
# Đưa tối đa bấy nhiêu thuật ngữ vào prompt — nhiều quá thì mô hình nhồi cho đủ.
MAX_TERMS_IN_PROMPT = 24
# Độ dài tài liệu thật đưa vào prompt.
MAX_AUTHENTIC_CHARS = 5000
# Tỷ lệ từ trùng tối thiểu để công nhận một lượt đúng là lấy nguyên văn từ tài liệu.
VERBATIM_MIN_OVERLAP = 0.6

_SENTENCE_SPLIT = re.compile(r"[.!?…]+(?:\s|$)")


class CharacterOut(LLMSchema):
    name: str = Field(description="Tên nhân vật, đặt theo văn hoá tương ứng")
    role: str = Field(description="Chức danh và tổ chức, ví dụ 'Chủ tịch UBND xã Thu Cúc'")


class TurnOut(LLMSchema):
    speaker: Literal["A", "B"] = Field(description="A nói tiếng Việt, B nói tiếng Anh")
    source_lang: Literal["vi", "en"]
    text: str = Field(description="Lời thoại, khoảng 5 câu")
    reference_translation: str = Field(description="Bản dịch chuẩn sang ngôn ngữ còn lại")
    terms_used: list[str] = Field(
        description="Các thuật ngữ trong bảng đã dùng ở lượt này, ghi dạng tiếng Việt"
    )
    verbatim_from_document: bool = Field(
        description="True nếu lượt này dùng lại nguyên văn câu chữ từ tài liệu thật được cung cấp"
    )


class ScriptOut(LLMSchema):
    setting: str = Field(description="Một câu mô tả bối cảnh buổi làm việc")
    character_a: CharacterOut
    character_b: CharacterOut
    turns: list[TurnOut]


@dataclass
class GeneratedTurn:
    turn_index: int
    speaker_name: str
    speaker_role: str
    source_lang: str
    target_lang: str
    source_text: str
    reference_translation: str
    reference_tier: str
    terms_used: list[int]
    est_duration_sec: float


@dataclass
class GeneratedScript:
    session_id: int
    setting: str
    character_a: dict[str, str]
    character_b: dict[str, str]
    turns: list[GeneratedTurn] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_terms_used: int = 0
    regenerated: bool = False


# ============================== Dựng bối cảnh ==============================


def _profile_text(workspace_id: int) -> str:
    """Gom hồ sơ các bên thành văn bản ngắn để đưa vào prompt."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.entity_name, p.entity_role, f.field_key, f.value
            FROM profiles p JOIN profile_fields f ON f.profile_id = p.id
            WHERE p.workspace_id = ?
              AND p.id = (SELECT MAX(p2.id) FROM profiles p2
                          WHERE p2.workspace_id = p.workspace_id AND p2.entity_name = p.entity_name)
            ORDER BY CASE p.entity_role WHEN 'client' THEN 0 ELSE 1 END, p.entity_name, f.id
            """,
            (workspace_id,),
        ).fetchall()

    grouped: dict[str, list[str]] = {}
    for row in rows:
        role = "Khách hàng" if row["entity_role"] == "client" else "Đối tác"
        key = f"{row['entity_name']} ({role})"
        grouped.setdefault(key, []).append(f"  - {row['field_key']}: {row['value']}")

    return "\n".join(f"{name}:\n" + "\n".join(items) for name, items in grouped.items())


def _glossary_for_prompt(workspace_id: int) -> tuple[str, dict[str, int]]:
    """Trả về (văn bản bảng thuật ngữ, tra cứu chuẩn hoá → id) để đối chiếu sau khi sinh."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, term_vi, term_vi_norm, term_en, definition, category
            FROM glossary WHERE workspace_id = ? AND status <> 'skipped'
            ORDER BY CASE status WHEN 'expert_edited' THEN 0 ELSE 1 END,
                     CASE confidence WHEN 'human_translated' THEN 0 ELSE 1 END,
                     frequency DESC
            LIMIT ?
            """,
            (workspace_id, MAX_TERMS_IN_PROMPT),
        ).fetchall()

    lines: list[str] = []
    lookup: dict[str, int] = {}
    for row in rows:
        lookup[str(row["term_vi_norm"])] = int(row["id"])
        definition = f" — {row['definition']}" if row["definition"] else ""
        lines.append(f"  - {row['term_vi']} = {row['term_en']}{definition}")
    return "\n".join(lines), lookup


def _authentic_material(workspace_id: int) -> tuple[str, str]:
    """Lấy văn bản song ngữ thật (nếu có) để kịch bản dùng lại nguyên văn.

    Trả về (văn bản đưa vào prompt, toàn bộ phần tiếng Anh dùng để kiểm chứng verbatim).
    """
    with get_conn() as conn:
        docs = conn.execute(
            """
            SELECT id, filename FROM documents
            WHERE workspace_id = ? AND status = 'ready' AND language = 'parallel'
            ORDER BY id LIMIT 1
            """,
            (workspace_id,),
        ).fetchall()
        if not docs:
            return "", ""
        doc_id = int(docs[0]["id"])
        chunks = conn.execute(
            "SELECT text, lang FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()

    vi_text = "\n\n".join(str(c["text"]) for c in chunks if str(c["lang"]) == "vi")
    en_text = "\n\n".join(str(c["text"]) for c in chunks if str(c["lang"]) == "en")
    if not vi_text or not en_text:
        return "", ""

    half = MAX_AUTHENTIC_CHARS // 2
    material = (
        f"[Bản tiếng Việt]\n{vi_text[:half]}\n\n[Bản tiếng Anh tương ứng]\n{en_text[:half]}"
    )
    return material, en_text


# ============================== Kiểm tra kịch bản ==============================


def estimate_duration_sec(text: str, lang: str) -> float:
    """Ước lượng thời lượng đọc lên, để chặn lượt quá ngắn/quá dài NGAY LÚC SINH."""
    words = len(text.split())
    wpm = settings.words_per_min_vi if lang == "vi" else settings.words_per_min_en
    return round(words / wpm * 60, 1)


def count_sentences(text: str) -> int:
    parts = [p for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    return max(1, len(parts))


def _token_overlap(a: str, b: str) -> float:
    """Tỷ lệ từ của `a` xuất hiện trong `b`. Dùng để kiểm lời khai verbatim."""
    tokens_a = {w for w in re.findall(r"\w+", a.lower()) if len(w) > 3}
    if not tokens_a:
        return 0.0
    tokens_b = {w for w in re.findall(r"\w+", b.lower()) if len(w) > 3}
    return len(tokens_a & tokens_b) / len(tokens_a)


def validate_script(
    script: ScriptOut,
    *,
    n_turns: int,
    lookup: dict[str, int],
) -> list[str]:
    """Kiểm kịch bản có đạt chuẩn không. Trả về danh sách vấn đề (rỗng = đạt)."""
    problems: list[str] = []
    turns = script.turns

    if not (n_turns - 1 <= len(turns) <= n_turns + 1):
        problems.append(f"sinh {len(turns)} lượt thay vì {n_turns}")

    langs = {t.source_lang for t in turns}
    if "vi" not in langs or "en" not in langs:
        problems.append("thiếu một chiều dịch (phải có cả lượt tiếng Việt và tiếng Anh)")

    too_short = [
        i + 1
        for i, t in enumerate(turns)
        if estimate_duration_sec(t.text, t.source_lang) < settings.turn_min_sec * 0.6
    ]
    too_long = [
        i + 1
        for i, t in enumerate(turns)
        if estimate_duration_sec(t.text, t.source_lang) > settings.turn_max_sec * 1.6
    ]
    if too_short:
        problems.append(f"lượt {too_short} quá ngắn so với mốc 30–60 giây")
    if too_long:
        problems.append(f"lượt {too_long} quá dài so với mốc 30–60 giây")

    missing_ref = [i + 1 for i, t in enumerate(turns) if not t.reference_translation.strip()]
    if missing_ref:
        problems.append(f"lượt {missing_ref} thiếu bản dịch tham chiếu")

    if lookup:
        matched = {
            lookup[normalize_term(term)]
            for t in turns
            for term in t.terms_used
            if normalize_term(term) in lookup
        }
        required = max(2, int(len(turns) * MIN_TERMS_RATIO))
        if len(matched) < required:
            problems.append(
                f"chỉ dùng {len(matched)} thuật ngữ trong bảng, cần ít nhất {required}"
            )

    return problems


# ============================== Sinh kịch bản ==============================


def generate_script(
    workspace_id: int,
    topic: str,
    *,
    client_name: str,
    partner_names: list[str],
    mode: str = "consecutive",
    difficulty: str = "medium",
    n_turns: int = 8,
    hide_script: bool = True,
    glossary_scope: str = "all",
    engagement_id: int | None = None,
) -> GeneratedScript:
    """Sinh kịch bản, kiểm, sinh lại một lần nếu chưa đạt, rồi lưu."""
    profile_text = _profile_text(workspace_id)
    glossary_text, lookup = _glossary_for_prompt(workspace_id)
    authentic_text, authentic_en = _authentic_material(workspace_id)

    warnings: list[str] = []
    if not profile_text:
        warnings.append(
            "Chưa có hồ sơ khách hàng — kịch bản sẽ chung chung. "
            "Chạy Nghiên cứu trước sẽ sát thực tế hơn nhiều."
        )
    if not lookup:
        warnings.append(
            "Bảng thuật ngữ đang rỗng — kịch bản không chèn được thuật ngữ chuyên ngành."
        )

    prompt = build_script_prompt(
        client_name=client_name,
        partner_names=partner_names,
        topic=topic,
        profile_text=profile_text,
        glossary_text=glossary_text,
        authentic_text=authentic_text,
        n_turns=n_turns,
        difficulty=difficulty,
        turn_sentences=settings.turn_sentences,
    )

    script = llm.generate_json(
        module="simulation.generate",
        prompt=prompt,
        schema=ScriptOut,
        workspace_id=workspace_id,
        system_instruction=SCRIPT_SYSTEM,
        temperature=0.75,
        summary=f"Sinh kịch bản {n_turns} lượt: {topic[:70]}",
        tier="quality",
    )

    problems = validate_script(script, n_turns=n_turns, lookup=lookup)
    regenerated = False

    if problems:
        # Tự sinh lại MỘT lần, nói rõ sai gì để mô hình sửa đúng chỗ.
        regenerated = True
        retry_prompt = (
            f"{prompt}\n\n"
            "LẦN TRƯỚC KỊCH BẢN CHƯA ĐẠT, cụ thể: "
            + "; ".join(problems)
            + ".\nHãy viết lại cho đúng yêu cầu."
        )
        script = llm.generate_json(
            module="simulation.generate.retry",
            prompt=retry_prompt,
            schema=ScriptOut,
            workspace_id=workspace_id,
            system_instruction=SCRIPT_SYSTEM,
            temperature=0.7,
            summary=f"Sinh lại kịch bản (lần trước: {problems[0][:50]})",
            tier="quality",
        )
        problems = validate_script(script, n_turns=n_turns, lookup=lookup)
        if problems:
            warnings.append(
                "Kịch bản vẫn chưa đạt chuẩn sau khi sinh lại: "
                + "; ".join(problems)
                + ". Bạn có thể bấm Sinh lại, hoặc sửa tay lời thoại."
            )

    # ---- Lưu ----
    characters = {
        "A": (script.character_a.name, script.character_a.role),
        "B": (script.character_b.name, script.character_b.role),
    }

    with get_conn() as conn:
        session_id = int(
            conn.execute(
                """
                INSERT INTO mock_sessions
                    (workspace_id, engagement_id, mode, difficulty, n_turns, hide_script,
                     glossary_scope, script_json, gen_warnings, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated')
                """,
                (
                    workspace_id, engagement_id, mode, difficulty, len(script.turns),
                    int(hide_script), glossary_scope,
                    script.model_dump_json(),
                    json.dumps(warnings, ensure_ascii=False),
                ),
            ).lastrowid
            or 0
        )

        turns: list[GeneratedTurn] = []
        used_term_ids: set[int] = set()

        for index, turn in enumerate(script.turns):
            name, role = characters.get(turn.speaker, ("?", "?"))
            target_lang = "en" if turn.source_lang == "vi" else "vi"

            term_ids = [
                lookup[normalize_term(t)]
                for t in turn.terms_used
                if normalize_term(t) in lookup
            ]
            used_term_ids.update(term_ids)

            # Kiểm lời khai "lấy nguyên văn từ tài liệu" thay vì tin ngay: chỉ công nhận
            # mức ⭐⭐⭐ khi bản dịch thật sự trùng nhiều với bản tiếng Anh trong tài liệu.
            tier = "ai"
            if turn.verbatim_from_document and authentic_en:
                overlap = _token_overlap(turn.reference_translation, authentic_en)
                if overlap >= VERBATIM_MIN_OVERLAP:
                    tier = "human"

            duration = estimate_duration_sec(turn.text, turn.source_lang)

            conn.execute(
                """
                INSERT INTO mock_turns
                    (session_id, turn_index, speaker_name, speaker_role, source_lang,
                     target_lang, source_text, reference_translation, reference_tier,
                     terms_used, est_duration_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id, index, name, role, turn.source_lang, target_lang,
                    turn.text.strip(), turn.reference_translation.strip(), tier,
                    json.dumps(term_ids), duration,
                ),
            )
            turns.append(
                GeneratedTurn(
                    turn_index=index,
                    speaker_name=name,
                    speaker_role=role,
                    source_lang=turn.source_lang,
                    target_lang=target_lang,
                    source_text=turn.text.strip(),
                    reference_translation=turn.reference_translation.strip(),
                    reference_tier=tier,
                    terms_used=term_ids,
                    est_duration_sec=duration,
                )
            )

    n_human = sum(1 for t in turns if t.reference_tier == "human")
    if n_human:
        warnings.append(
            f"{n_human} lượt dùng bản dịch của người thật từ tài liệu buổi làm việc — "
            "những lượt này chấm theo chuẩn đáng tin nhất."
        )

    return GeneratedScript(
        session_id=session_id,
        setting=script.setting,
        character_a={"name": script.character_a.name, "role": script.character_a.role},
        character_b={"name": script.character_b.name, "role": script.character_b.role},
        turns=turns,
        warnings=warnings,
        n_terms_used=len(used_term_ids),
        regenerated=regenerated,
    )
