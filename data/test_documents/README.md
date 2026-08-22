# Bộ tài liệu kiểm thử — Dự án LDSC × xã Thu Cúc, Phú Thọ

Bộ tài liệu thật do chuyên gia cung cấp, dùng làm **fixture nghiệm thu** cho các Acceptance Criteria trong [../../\_specs/mvp-spec.md](../../_specs/mvp-spec.md).

> ⚠️ **Không commit lên git, không đưa ra dịch vụ bên ngoài.** Đây là tài liệu công việc thật, có tên người và số tiền tài trợ cụ thể. Thư mục này đã được `.gitignore` loại trừ (trừ chính tệp README này). Xem mục *Bảo mật* của spec.

---

## 1. Danh sách tệp

| Tệp | Định dạng | Ngôn ngữ | Dung lượng | Vai trò khi kiểm thử |
|---|---|---|---|---|
| `10 Phu Tho - Ke hoach tổng thể(en).docx` | DOCX | **Chỉ tiếng Anh** | 68 KB (~52.500 ký tự) | Tài liệu dài, nền tảng pháp lý/chính sách. Nguồn chính để trích thuật ngữ tiếng Anh và test RAG trên tài liệu dài |
| `CHƯƠNG TRÌNH LDSC.doc` | **DOC (định dạng cũ)** | Chỉ tiếng Việt | 36 KB (ngắn) | Chương trình/kịch bản buổi lễ. Nguồn để dự đoán diễn biến buổi làm việc |
| `zPHÁT BIỂU 22 6.doc` | **DOC (định dạng cũ)** | **Song ngữ VI + EN song song** | 36 KB | ⭐ Quan trọng nhất: bài phát biểu có sẵn cả bản Việt và bản Anh → dùng làm **bản dịch chuẩn (gold standard)** để đối chiếu, và để trích cặp thuật ngữ song ngữ |

### Hai phát hiện ảnh hưởng tới spec

1. **Hai trong ba tệp là `.doc` (định dạng Word cũ, nhị phân), không phải `.docx`.** Spec ban đầu chỉ ghi PDF/DOCX/TXT/MD → **phải bổ sung `.doc`**, nếu không thì 2/3 tài liệu kiểm thử không nạp được. Đã cập nhật vào spec (A1.1).
2. **`zPHÁT BIỂU 22 6.doc` là văn bản song song VI-EN.** Đây là loại tài liệu quý nhất cho việc trích thuật ngữ (có sẵn cặp dịch do người thật làm) và cho việc chấm điểm (có sẵn bản dịch chuẩn của người thật, không phải AI sinh). Spec đã ghi nhận là một loại đầu vào riêng.
3. Tệp `10 Phu Tho...(en).docx` **chỉ có bản tiếng Anh**, không có bản tiếng Việt gốc kèm theo. Nếu chuyên gia có bản Việt của Kế hoạch 165/KH-BCĐ thì nên bổ sung — sẽ tăng mạnh chất lượng trích thuật ngữ song ngữ.

---

## 2. Bối cảnh buổi làm việc (dữ liệu để kiểm chứng kết quả)

Các thông tin dưới đây **đọc được trực tiếp từ tài liệu**, dùng làm đáp án đối chiếu khi nghiệm thu — nếu hệ thống trả lời khác thì là sai.

### Các bên tham gia

| Vai | Tên | Nguồn |
|---|---|---|
| **Khách hàng** (nhà tài trợ) | Tổ chức **Latter-Day Saint Charities (LDSC)** / Hoa Kỳ | `zPHÁT BIỂU 22 6.doc` |
| **Đối tác** | **UBND xã Thu Cúc**, tỉnh Phú Thọ (ban lãnh đạo xã) | `CHƯƠNG TRÌNH LDSC.doc`, `zPHÁT BIỂU 22 6.doc` |
| Bên vận động viện trợ | **Sở Ngoại vụ tỉnh Phú Thọ** | cả hai tệp `.doc` |
| Nhân sự LDSC | Ông/Bà **Walker** — chuyên gia nhân đạo (*humanitarian specialist*) | `zPHÁT BIỂU 22 6.doc` |
| Nhân sự LDSC | Ông **Nguyễn Quang Trình** — Đại diện LDSC tại Việt Nam (*Project Manager*) | `zPHÁT BIỂU 22 6.doc` |

### Dự án

| Hạng mục | Giá trị |
|---|---|
| Tên dự án | Hỗ trợ kinh phí xây nhà cho **113 hộ dân** có hoàn cảnh khó khăn tại xã Thu Cúc, tỉnh Phú Thọ |
| Tên tiếng Anh | *Financial support for building houses for 113 disadvantaged households in Thu Cuc commune, Phu Tho province* |
| Tổng giá trị tài trợ | **6.780.000.000 VNĐ** (sáu tỷ bảy trăm tám mươi triệu đồng) |
| Tổng tài trợ LDSC cho Phú Thọ (tích lũy) | khoảng **20 tỷ đồng** |
| Các chương trình LDSC trước đó | trao tặng xe lăn; hỗ trợ cơ sở vật chất và trang thiết bị y tế, giáo dục |
| Sự kiện | **Lễ Tổng kết và bàn giao công trình nhà ở** |
| Thời gian | **22/6/2026** · Địa điểm: xã Thu Cúc |

### Diễn biến buổi lễ (theo `CHƯƠNG TRÌNH LDSC.doc`)

1. Đi thăm một số công trình nhà ở thuộc dự án — *Đoàn LDSC + Đại diện xã Thu Cúc*
2. Ổn định tổ chức / Giới thiệu đại biểu — *BTC (xã Thu Cúc)*
3. Phát biểu tổng kết dự án (báo cáo tổng kết)
4. Phát biểu của Tổ chức LDSC (nhà tài trợ)
5. Phát biểu của Sở Ngoại vụ (đơn vị vận động viện trợ)
6. Trao biểu trưng bàn giao công trình + chụp hình lưu niệm — *LDSC; Sở Ngoại vụ; UBND xã Thu Cúc*

### Nền chính sách (theo tệp DOCX)

Kế hoạch **165/KH-BCĐ ngày 10/01/2025** của Ban Chỉ đạo tỉnh Phú Thọ về xóa nhà tạm, nhà dột nát năm 2025:

- Mức hỗ trợ: **xây mới 60 triệu/nhà**, **sửa chữa 30 triệu/nhà**; hộ nghèo không có khả năng đối ứng **tối đa 130 triệu/nhà**
- Tiêu chí **"3 cứng"** (nền cứng, khung–tường cứng, mái cứng), diện tích tối thiểu **30 m²** (hộ độc thân có thể ≥ 24 m²), tuổi thọ ≥ **20 năm**
- Giải ngân **60% trước / 40% sau khi có xác nhận khối lượng hoàn thành** của UBND xã
- Ba giai đoạn: 30/6/2025 · 30/9/2025 · 31/12/2025; tổng kết đánh giá tháng 1/2026
- Huyện **Tân Sơn** (địa bàn xã Thu Cúc) thuộc nhóm Quỹ "Vì người nghèo" cấp tỉnh hỗ trợ **100%**

---

## 3. Câu hỏi mẫu để nghiệm thu (do chuyên gia đặt)

Dùng đúng ba câu này cho Acceptance A1.3, và câu thứ tư cho Module 3.

### T1 — Hồ sơ khách hàng
> *"Khách là LDSC, đối tác là ban lãnh đạo xã Thu Cúc — tóm tắt thông tin về khách."*

**Đạt** khi câu trả lời nêu được: LDSC là Latter-Day Saint Charities (Hoa Kỳ), là nhà tài trợ; đã đồng hành Phú Thọ với tổng tài trợ ~20 tỷ đồng; các chương trình trước gồm xe lăn, trang thiết bị y tế và giáo dục — **kèm trích dẫn trỏ đúng `zPHÁT BIỂU 22 6.doc`**.

### T2 — Thông tin dự án
> *"Cho tôi thông tin về dự án."*

**Đạt** khi nêu đúng: 113 hộ, xã Thu Cúc tỉnh Phú Thọ, tổng tài trợ 6.780.000.000 VNĐ, hình thức hỗ trợ kinh phí xây nhà, sự kiện là lễ tổng kết và bàn giao — **kèm trích dẫn**. Sai số tiền hoặc sai số hộ = **không đạt**.

### T3 — Dự đoán nội dung buổi nghiệm thu
> *"Dự đoán nội dung sẽ trao đổi trong buổi nghiệm thu."*

**Đạt** khi dự đoán dựa trên chương trình thật (thăm công trình → giới thiệu đại biểu → báo cáo tổng kết → phát biểu LDSC → phát biểu Sở Ngoại vụ → trao biểu trưng bàn giao) và có gắn với các chủ đề nghiệm thu thực tế: tiêu chí "3 cứng", khối lượng hoàn thành, giải ngân 60/40, chất lượng và tuổi thọ nhà. Đây là câu **suy luận có căn cứ** — phải nói rõ phần nào là suy luận, phần nào có trong tài liệu.

### T4 — Mô phỏng hội thoại (Module 3)
> *"Hãy mô phỏng cuộc hội thoại."*

**Đạt** khi sinh được kịch bản **8–10 lượt** giữa đại diện LDSC (nói tiếng Anh) và đại diện xã Thu Cúc / Sở Ngoại vụ (nói tiếng Việt), dùng đúng bối cảnh trên và **chèn tự nhiên** các thuật ngữ ở mục 4.

### T5 — Câu hỏi ngoài phạm vi (kiểm tra chống bịa)
> *"LDSC tài trợ bao nhiêu tiền cho tỉnh Nghệ An?"*

**Đạt** khi hệ thống trả lời **không tìm thấy trong tài liệu** và không suy diễn ra con số nào (Acceptance A1.4).

---

## 4. Thuật ngữ kỳ vọng trích được (chứng minh ngưỡng ≥ 15 khả thi)

Rút trực tiếp từ ba tệp — dùng để đối chiếu Acceptance A2.1 / A2.6:

| Tiếng Việt | Tiếng Anh | Phân loại |
|---|---|---|
| nhà tạm, nhà dột nát | temporary and dilapidated houses | chuyên ngành |
| người có công với cách mạng | people with revolutionary contributions | chính sách |
| hộ nghèo / hộ cận nghèo | poor / near-poor households | chính sách |
| tiêu chí "3 cứng" | "three solids" standards | kỹ thuật |
| Quỹ "Vì người nghèo" | "Fund for the Poor" | tổ chức |
| Chương trình mục tiêu quốc gia | National Target Program | chính sách |
| Giấy chứng nhận quyền sử dụng đất | Land Use Rights Certificate | pháp lý |
| chuẩn nghèo đa chiều | multidimensional poverty standards | chính sách |
| vốn đối ứng | counterpart funding | tài chính |
| giải ngân | disbursement | tài chính |
| nghiệm thu | acceptance | kỹ thuật |
| bàn giao công trình | handover of the works | kỹ thuật |
| xác nhận khối lượng hoàn thành | confirmation of completed volume | kỹ thuật |
| viện trợ phi chính phủ nước ngoài | foreign non-governmental aid | pháp lý |
| xây dựng nông thôn mới | new rural development program | chính sách |
| vùng dân tộc thiểu số và miền núi | ethnic minority and mountainous areas | chính sách |
| Ban Chỉ đạo | Steering Committee | tổ chức |
| Sở Ngoại vụ | Department of Foreign Affairs | tổ chức |
| UBND xã | Commune People's Committee | tổ chức |
| giảm nghèo | poverty reduction | chính sách |
| an cư lạc nghiệp | stable housing and settled livelihood | thành ngữ |
| chuyên gia nhân đạo | humanitarian specialist | chức danh |

→ **22 thuật ngữ** rút được bằng tay, vượt ngưỡng 15 của A2.1. Ngoài ra cần cột **cách đọc tên riêng** (theo Q6): *Walker*, *Latter-Day Saint Charities*, *Thu Cúc*, *Tân Sơn*, *Phú Thọ*.

---

## 5. Ghi chú vận hành

- Ba tệp này là **fixture cố định** — không sửa nội dung, để kết quả nghiệm thu so sánh được giữa các lần chạy.
- Nếu chuyên gia bổ sung tài liệu test mới: đặt vào đúng thư mục này và **cập nhật bảng ở mục 1 + đáp án ở mục 2**, nếu không thì tiêu chí nghiệm thu sẽ lệch.
- Bản trích xuất văn bản thô (dùng khi debug) **không** lưu ở đây; sinh lại khi cần.
