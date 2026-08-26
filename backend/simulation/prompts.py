"""Mẫu prompt cho sinh kịch bản và chấm điểm.

Input:  bối cảnh hồ sơ khách hàng, bảng thuật ngữ, cấu hình buổi mock.
Output: chuỗi prompt và system instruction.

Tách riêng khỏi logic để chỉnh câu chữ prompt không phải đụng vào code xử lý — phần
prompt sẽ còn sửa nhiều theo nhận định của chuyên gia (§6).
"""

from __future__ import annotations

DIFFICULTY_GUIDE: dict[str, str] = {
    "basic": (
        "CƠ BẢN: câu ngắn và rõ, mỗi câu một ý. Mật độ thuật ngữ thấp (1–2 thuật ngữ/lượt). "
        "Ngôn ngữ đời thường, ít thành ngữ hành chính. Người nói diễn đạt mạch lạc, không lạc đề."
    ),
    "medium": (
        "TRUNG BÌNH: câu dài vừa, có mệnh đề phụ. Mật độ thuật ngữ vừa (2–4 thuật ngữ/lượt). "
        "Có số liệu cụ thể cần dịch chính xác. Mức trang trọng của một buổi làm việc chính thức."
    ),
    "hard": (
        "KHÓ: câu dài, nhiều mệnh đề lồng nhau, có chỗ nói vòng. Mật độ thuật ngữ cao "
        "(4+ thuật ngữ/lượt). Nhiều số liệu, mốc thời gian, tên văn bản pháp quy. Văn phong nghi "
        "thức trang trọng, có thành ngữ hành chính. Đôi chỗ người nói tự sửa lời hoặc bổ sung ý "
        "giữa chừng — giống hệt lúc phát biểu thật."
    ),
}


SCRIPT_SYSTEM = """\
Bạn viết kịch bản hội thoại để một chuyên gia PHIÊN DỊCH Việt–Anh luyện tập trước buổi dịch thật.

Đây là công cụ luyện tập nghiêm túc, không phải bài tập ngôn ngữ. Kịch bản phải giống hệt
một buổi làm việc có thật.

QUY TẮC BẮT BUỘC:
1. Đúng HAI nhân vật, nói XEN KẼ nhau. Nhân vật A nói TIẾNG VIỆT, nhân vật B nói TIẾNG ANH.
   Nhờ vậy chuyên gia phải dịch cả hai chiều trong cùng một buổi.
2. Số lượt đúng bằng số được yêu cầu. Lượt đầu tiên là của nhân vật A.
3. Mỗi lượt khoảng 5 câu — đủ dài để thành một đơn vị dịch nối tiếp thật (đọc lên 30–60 giây).
   Không viết lượt một câu, cũng không viết lượt dài cả trang.
4. THUẬT NGỮ phải nằm TỰ NHIÊN trong lời nói. Nhân vật đang phát biểu, không phải đang đọc
   danh sách từ vựng. Sai: "Chúng tôi quan tâm tới nhà tạm, nhà dột nát, hộ nghèo, hộ cận nghèo."
   Đúng: "Qua rà soát, xã còn 113 hộ đang ở nhà tạm, nhà dột nát, phần lớn là hộ nghèo và cận nghèo."
5. Dùng ĐÚNG số liệu và tên riêng trong hồ sơ khách hàng. Không bịa thêm con số mới.
6. Mạch hội thoại theo đúng loại sự kiện: mở đầu và giới thiệu → nội dung chính → trao đổi/
   vướng mắc → cam kết và kết thúc. Không nhảy cóc, không kết thúc đột ngột.
7. reference_translation là bản dịch CHUẨN của lượt đó sang ngôn ngữ còn lại — bản mà một
   phiên dịch giỏi sẽ nói. Giữ nguyên chính xác mọi con số và tên riêng.
8. terms_used liệt kê các thuật ngữ trong bảng đã thực sự xuất hiện ở lượt đó, ghi đúng dạng
   tiếng Việt như trong bảng.

Trả về JSON thuần đúng schema, không kèm giải thích."""


def build_script_prompt(
    *,
    client_name: str,
    partner_names: list[str],
    topic: str,
    profile_text: str,
    glossary_text: str,
    authentic_text: str,
    n_turns: int,
    difficulty: str,
    turn_sentences: int,
) -> str:
    partners = ", ".join(partner_names) if partner_names else "(chưa nêu)"
    sections = [
        f"KHÁCH HÀNG: {client_name}",
        f"ĐỐI TÁC: {partners}",
        f"CHỦ ĐỀ BUỔI LÀM VIỆC: {topic}",
        "",
        "=== HỒ SƠ CÁC BÊN (dùng đúng số liệu và tên riêng ở đây) ===",
        profile_text or "(chưa có hồ sơ — hãy viết kịch bản chung chung hơn)",
        "",
        "=== BẢNG THUẬT NGỮ CẦN CHÈN VÀO LỜI THOẠI ===",
        glossary_text or "(chưa có thuật ngữ)",
    ]

    if authentic_text:
        sections += [
            "",
            "=== TÀI LIỆU THẬT CỦA BUỔI LÀM VIỆC (bản Việt và bản Anh do người thật dịch) ===",
            authentic_text,
            "",
            "Với những lượt mà nội dung trùng với tài liệu thật ở trên, bạn ĐƯỢC PHÉP dùng lại "
            "nguyên văn câu chữ của cả bản Việt lẫn bản Anh, và đặt verbatim_from_document=true. "
            "Đây là cách cho chuyên gia luyện trên chính lời sẽ được nói trong buổi thật.",
        ]

    sections += [
        "",
        f"ĐỘ KHÓ — {DIFFICULTY_GUIDE.get(difficulty, DIFFICULTY_GUIDE['medium'])}",
        "",
        f"Viết kịch bản {n_turns} lượt, mỗi lượt khoảng {turn_sentences} câu.",
    ]
    return "\n".join(sections)


SCORING_SYSTEM = """\
Bạn chấm bài dịch của một chuyên gia phiên dịch Việt–Anh đang luyện tập.

Chấm theo BỐN tiêu chí, mỗi tiêu chí THANG 10 ĐIỂM (0 = hoàn toàn sai, 10 = không chê được):

1. score_meaning (Độ chính xác nghĩa) — có truyền đạt đúng ý người nói không, có chỗ nào
   làm sai lệch nghĩa không.
2. score_terminology (Thuật ngữ) — các thuật ngữ chuyên ngành trong lượt này có được dịch
   đúng theo bảng thuật ngữ không. Phải nêu ĐÍCH DANH từng thuật ngữ đúng/sai.
3. score_completeness (Độ đầy đủ) — có bỏ sót thông tin nào không, đặc biệt là SỐ LIỆU,
   ĐIỀU KIỆN, TÊN RIÊNG, CHỨC DANH. Bỏ sót một con số là lỗi nặng với phiên dịch.
4. score_expression (Diễn đạt) — ngữ pháp, tính tự nhiên, mức trang trọng có hợp bối cảnh
   nghi thức không.

NGUYÊN TẮC CHẤM:
- Chấm nội dung bản dịch, KHÔNG chấm phát âm hay giọng nói.
- Bản dịch rút gọn nhưng vẫn đủ ý và phù hợp nghi thức thì KHÔNG bị trừ Độ đầy đủ.
- Cách diễn đạt khác bản tham chiếu nhưng vẫn đúng nghĩa thì KHÔNG bị trừ điểm. Bản tham
  chiếu là một cách dịch tốt, không phải cách duy nhất đúng.
- Nhận xét phải CỤ THỂ và dùng được ngay: chỉ rõ chỗ nào, sai thế nào, nên dịch ra sao.
  Không viết nhận xét chung chung kiểu "cần cải thiện thêm".
- Viết nhận xét bằng tiếng Việt.

Trả về JSON thuần đúng schema."""


def build_scoring_prompt(
    *,
    source_lang: str,
    target_lang: str,
    source_text: str,
    reference_translation: str,
    reference_tier: str,
    user_translation: str,
    glossary_text: str,
    calibration_text: str = "",
) -> str:
    lang_label = {"vi": "tiếng Việt", "en": "tiếng Anh"}
    tier_label = {
        "verbatim_parallel": (
            "câu tìm được NGUYÊN VĂN trong tài liệu song ngữ của buổi làm việc "
            "(do người dịch, đáng tin hơn bản AI sinh)"
        ),
        "expert_pinned": "bản dịch do chính chuyên gia này chốt trước đó",
        "ai": "bản dịch do AI sinh (chỉ để tham khảo, không phải chuẩn tuyệt đối)",
    }

    sections = [
        f"CHIỀU DỊCH: {lang_label.get(source_lang, source_lang)} → {lang_label.get(target_lang, target_lang)}",
        "",
        "=== LỜI NGƯỜI NÓI (bản gốc) ===",
        source_text,
        "",
        f"=== BẢN DỊCH THAM CHIẾU ({tier_label.get(reference_tier, reference_tier)}) ===",
        reference_translation or "(không có)",
        "",
        "=== BẢN DỊCH CỦA CHUYÊN GIA (cần chấm) ===",
        user_translation,
    ]

    if glossary_text:
        sections += [
            "",
            "=== THUẬT NGỮ LIÊN QUAN TỚI LƯỢT NÀY (bản dịch chuẩn đã chốt) ===",
            glossary_text,
        ]

    if calibration_text:
        sections += [
            "",
            "=== NHẬN ĐỊNH CHUYÊN GIA ĐÃ ĐƯA RA Ở CÁC BUỔI TRƯỚC ===",
            "Đây là cách chuyên gia này muốn được chấm. Tôn trọng các nhận định dưới đây:",
            calibration_text,
        ]

    return "\n".join(sections)
