"""C10 · C11 — dữ kiện chưa có nguồn KHÔNG được thành lời thoại.

Vào:  cơ sở dữ liệu tạm với một hồ sơ nghiên cứu dựng sẵn.
Ra:   assert trên đúng ranh giới prompt. Không gọi mạng, không gọi LLM.

Vì sao kiểm ở ranh giới prompt chứ không kiểm kịch bản sinh ra
--------------------------------------------------------------
Kiểm "kịch bản có chứa số đó không" là kiểm một ràng buộc MỀM: nó chỉ nói LLM đã ngoan
trong lần chạy đó, không nói lần sau nó vẫn ngoan. Kiểm ở `_profile_text()` là kiểm một
bảo đảm CỨNG: dữ kiện chưa có nguồn không hề có trong ngữ cảnh, nên không có gì để rò.
"""

from __future__ import annotations

from backend.db import get_conn
from backend.simulation.generator import _profile_text

# Số dễ nhận, lấy từ bộ tài liệu nghiệm thu thật.
SOURCED_FIGURE = "6.780.000.000 VND"
UNSOURCED_FIGURE = "999.888.777 USD"
EXPERT_FIGURE = "113 hộ dân"


def _seed_profile(workspace_id: int) -> None:
    """Một hồ sơ có đủ ba loại trường: có nguồn, chưa nguồn, và chuyên gia đã sửa."""
    with get_conn() as conn:
        run = conn.execute(
            "INSERT INTO research_runs (workspace_id, client_name, topic, status)"
            " VALUES (?, 'LDSC', 'nghiệm thu', 'done')",
            (workspace_id,),
        ).lastrowid
        profile = conn.execute(
            """
            INSERT INTO profiles (workspace_id, research_run_id, entity_name, entity_role)
            VALUES (?, ?, 'Latter-Day Saint Charities', 'client')
            """,
            (workspace_id, run),
        ).lastrowid
        rows = [
            ("funding_sourced", SOURCED_FIGURE, 1, 0),
            ("funding_guessed", UNSOURCED_FIGURE, 0, 0),
            ("households", EXPERT_FIGURE, 0, 1),
        ]
        for key, value, has_source, expert in rows:
            conn.execute(
                """
                INSERT INTO profile_fields
                    (profile_id, field_key, value, has_source, is_expert_edited)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profile, key, value, has_source, expert),
            )


def test_c10_unsourced_facts_never_reach_the_prompt(workspace: int) -> None:
    """C10 — trường không nguồn và chưa ai sửa thì KHÔNG có trong ngữ cảnh của mô hình.

    Trước đây `_profile_text()` lấy tất, không lọc, không đánh dấu. Một trường mà màn
    Nghiên cứu đang hiện badge đỏ "đây là suy luận của máy" vẫn thành lời thoại nhân vật
    nói ra như sự thật — và chuyên gia luyện tập trên số liệu máy bịa.
    """
    _seed_profile(workspace)
    prompt_text = _profile_text(workspace)

    assert UNSOURCED_FIGURE not in prompt_text
    assert SOURCED_FIGURE in prompt_text


def test_c11_expert_edited_fields_are_allowed_even_without_a_source(workspace: int) -> None:
    """C11 — chuyên gia đã sửa thì được dùng, dù không có URL nào.

    Đây là cái làm cho bộ lọc thành một QUY TRÌNH chứ không chỉ một cái chặn: muốn đưa
    một dữ kiện vào kịch bản luyện tập thì xác minh hoặc sửa nó.
    """
    _seed_profile(workspace)
    assert EXPERT_FIGURE in _profile_text(workspace)


def test_c10_empty_profile_yields_empty_text(workspace: int) -> None:
    """Không có hồ sơ thì trả về rỗng, không ném lỗi — kịch bản vẫn sinh được, chỉ chung chung hơn."""
    assert _profile_text(workspace) == ""


def test_c10_profile_with_only_unsourced_fields_yields_nothing(workspace: int) -> None:
    """Toàn trường chưa nguồn → ngữ cảnh rỗng, chứ không phải ngữ cảnh sai."""
    with get_conn() as conn:
        run = conn.execute(
            "INSERT INTO research_runs (workspace_id, client_name, topic, status)"
            " VALUES (?, 'LDSC', 'nghiệm thu', 'done')",
            (workspace,),
        ).lastrowid
        profile = conn.execute(
            """
            INSERT INTO profiles (workspace_id, research_run_id, entity_name, entity_role)
            VALUES (?, ?, 'Tổ chức chưa rõ', 'partner')
            """,
            (workspace, run),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO profile_fields (profile_id, field_key, value, has_source, is_expert_edited)
            VALUES (?, 'size', ?, 0, 0)
            """,
            (profile, UNSOURCED_FIGURE),
        )

    assert _profile_text(workspace) == ""
