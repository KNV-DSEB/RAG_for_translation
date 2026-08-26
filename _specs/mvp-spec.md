# MVP Spec — AI Assistant cho chuyên gia dịch thuật

> **Phiên bản 2** · Trạng thái: **đã duyệt, đã chốt Q1–Q15** · Phạm vi: dùng cá nhân, chi phí 0đ
> Tài liệu này mô tả **hành vi sản phẩm**, không mô tả kiến trúc hay thư viện. Chi tiết kỹ thuật thuộc bước Plan.

### Thay đổi so với v1 (bản đã duyệt)

Toàn bộ 15 Open Question đã được chuyên gia trả lời và chuyển thành **quyết định** (§8). Các thay đổi thực chất:

| Thay đổi | Nguồn |
|---|---|
| Bổ sung định dạng **`.doc`** (Word cũ) — 2/3 tài liệu kiểm thử thật là `.doc` | phát hiện từ tài liệu Q1 |
| Bổ sung loại đầu vào **tài liệu song ngữ song song** làm bản dịch chuẩn của người thật | phát hiện từ tài liệu Q1 |
| Thêm **§6 Vòng phản hồi & hiệu chỉnh chấm điểm** — chuyên gia phản biện điểm AI, hệ thống dùng lại | Q2 |
| Thang điểm **10 điểm**, độ dài lượt **5 câu / 30–60 giây** | Q3, Q4 |
| Glossary thêm cột **cách đọc tên riêng**; thuật ngữ **tự nhận hết, sửa sau** (bỏ bước duyệt bắt buộc) | Q6, Q9 |
| Thêm **§7 Bảo mật & quyền riêng tư** — chế độ hồ sơ mật, nhật ký dữ liệu gửi ra ngoài | Q7 |
| **Bỏ yêu cầu chạy offline**; đổi hướng sang tối ưu chất lượng | Q8 |
| Bản ghi âm **lưu lâu dài** + cơ chế xóa chủ động | Q11 |
| Thêm **§3.6 Tiêu chí UI/UX** thành điều kiện nghiệm thu riêng | Q13 |
| Giữ **đủ 4 module**, không cắt phạm vi; §9 nêu thứ tự xây dựng | Q15 |

---

## 1. Mục tiêu sản phẩm & Người dùng

### 1.1 Người dùng

**Duy nhất một người**: một chuyên gia phiên dịch Việt ↔ Anh, tự chuẩn bị cho các buổi dịch với khách hàng tổ chức. Qua bộ tài liệu thật đã cung cấp, có thể thấy tính chất công việc:

- Khách hàng là **tổ chức viện trợ / phi chính phủ nước ngoài** (ví dụ thật: Latter-Day Saint Charities — Hoa Kỳ), đối tác là **cơ quan nhà nước Việt Nam** (UBND xã, Sở Ngoại vụ, Ban Chỉ đạo tỉnh).
- Buổi dịch là **sự kiện có nghi thức**: lễ tổng kết, bàn giao công trình, nghiệm thu — có chương trình định trước, có bài phát biểu, có phần trao đổi tự do.
- Nội dung dày **thuật ngữ chính sách, pháp lý, tài chính công và xây dựng** cùng lúc → **đa ngành, mỗi khách một ngành khác nhau** (Q5).
- Số lượng: **dưới 10 khách hàng** (Q14) → ưu tiên chiều sâu từng hồ sơ hơn là quản lý danh sách lớn.
- Nhận thông tin trước 1–7 ngày, thường chỉ biết **tên khách hàng, tên đối tác, chủ đề**, kèm vài tài liệu.
- Là người có chuyên môn cao: sản phẩm **hỗ trợ chuẩn bị**, không thay thế phán đoán. Mọi thông tin máy sinh ra đều phải kiểm tra lại được.

### 1.2 Vấn đề đang giải quyết

| Nỗi đau hiện tại | Cách sản phẩm giải quyết |
|---|---|
| Đọc tài liệu rời rạc, không tra nhanh được "khách này có nói gì về điều khoản X chưa?" | Module 1 — hỏi đáp trên tài liệu, có trích dẫn nguồn |
| Tự Google mất 1–2 giờ để hiểu khách hàng/đối tác là ai, làm gì | Module 2 — Research Agent tự tổng hợp hồ sơ kèm nguồn |
| Không có bảng thuật ngữ hệ thống, mỗi buổi làm lại từ đầu | Module 2 — bảng glossary song ngữ, tái sử dụng theo khách hàng |
| Không có ai để luyện dịch trước buổi thật | Module 3 — mock buổi dịch với kịch bản sát thực tế, có chấm điểm |
| Luyện trên giấy không giống thật (không có áp lực nghe–nói) | Module 4 — nghe audio nhân vật, nói bản dịch, máy chuyển thành chữ để chấm |
| Máy chấm sai mà không sửa được, dùng lâu vẫn sai như cũ | §6 — chuyên gia phản biện điểm, hệ thống hiệu chỉnh cho lần sau |
| Tài liệu khách hàng có tính bảo mật, không muốn lộ ra ngoài | §7 — chế độ hồ sơ mật, nhật ký dữ liệu gửi ra ngoài |

### 1.3 Mục tiêu MVP (tuyên bố thành công)

MVP được coi là thành công nếu: **chuyên gia nhập tên một công ty và chủ đề buổi làm việc, trong vòng dưới 10 phút nhận được hồ sơ khách hàng có nguồn trích dẫn, bảng thuật ngữ song ngữ ≥ 15 mục, và có thể ngay lập tức luyện một buổi mock 8–10 lượt trao đổi có dùng đúng các thuật ngữ đó — toàn bộ chạy trên máy cá nhân, không tốn phí, và không có tài liệu khách hàng nào rời khỏi máy ngoài phần chuyên gia biết trước.**

### 1.4 Nguyên tắc thiết kế xuyên suốt

1. **Truy vết được (traceability)** — mọi thông tin do AI sinh ra đều kèm nguồn: URL web, hoặc tên tài liệu + vị trí. Không có nguồn thì phải ghi rõ "chưa xác minh".
2. **Chuyên gia là người quyết định** — AI đề xuất, chuyên gia sửa. Mọi nội dung máy sinh đều sửa được, và bản sửa của chuyên gia luôn thắng.
3. **Thà thiếu hơn bịa** — không tìm thấy thì nói không tìm thấy.
4. **Không mất việc đang làm** — thoát app giữa buổi mock vẫn khôi phục được.
5. **Chỉ gửi ra ngoài những gì cần thiết, và luôn cho biết trước** — xem §7.
6. **Sai một lần thì đừng sai lần hai** — mỗi lần chuyên gia sửa điểm hoặc sửa thuật ngữ, hệ thống phải dùng lại được thông tin đó.

### 1.5 Khái niệm nền tảng

- **Hồ sơ khách hàng (Client Workspace)** — đơn vị tổ chức chính. Mọi tài liệu, kết quả research, glossary, buổi mock, lịch sử đều thuộc về một hồ sơ khách hàng. Có cờ **mật / thường**.
- **Buổi làm việc (Engagement)** — một lần dịch cụ thể trong hồ sơ khách hàng, có chủ đề + đối tác riêng. Một khách hàng có nhiều buổi; glossary chia sẻ giữa các buổi cùng khách.
- **Thuật ngữ (Term)** — cặp Việt–Anh + định nghĩa + cách đọc + phân loại + nguồn + trạng thái.
- **Lượt thoại (Turn)** — một lần phát biểu của một nhân vật trong kịch bản mock; đơn vị để chuyên gia dịch và để máy chấm. Cỡ **5 câu, đọc lên khoảng 30–60 giây**.
- **Nhận định chuyên gia (Expert Verdict)** — đánh giá của chuyên gia về điểm mà AI đã chấm. Đây là dữ liệu hiệu chỉnh, xem §6.

---

## 2. User Flow chi tiết

### 2.0 Luồng xuyên suốt (happy path)

```
Chuyên gia nhận lịch dịch
   │
   ├─▶ [M1] Tạo hồ sơ khách hàng (chọn mật/thường) → nạp tài liệu → hỏi đáp có trích dẫn
   │
   ├─▶ [M2] Nhập tên khách / đối tác / chủ đề → Research Agent
   │         → hồ sơ khách hàng + đối tác (có nguồn)
   │         → bảng glossary song ngữ (từ tài liệu M1 + kết quả search)
   │         → chuyên gia soát / sửa những dòng thấy sai
   │
   ├─▶ [M3] Mock buổi dịch: đọc hồ sơ + glossary → sinh kịch bản 8–10 lượt
   │         → luyện dịch từng lượt (2 chiều) → AI chấm → chuyên gia phản biện → báo cáo
   │
   ├─▶ [M4] Audio phục vụ M3: TTS đọc lời nhân vật, STT ghi lại bản dịch nói
   │         (dùng độc lập được: đọc thuật ngữ, gỡ băng ghi âm buổi thật)
   │
   └─▶ [§6] Nhận định của chuyên gia quay lại hiệu chỉnh cách chấm cho buổi sau
```

---

### 2.1 Module 1 — RAG tài liệu (📚 Tổng hợp tài liệu dịch thuật)

**Mục đích**: biến tập tài liệu rời rạc của một khách hàng thành thứ hỏi được bằng tiếng Việt, câu trả lời luôn chỉ ra nguồn.

#### Flow chính: Nạp tài liệu

1. Chuyên gia mở tab **Tài liệu**, chọn hồ sơ khách hàng hiện có hoặc **tạo hồ sơ mới** (tên khách hàng, ngành nghề nếu biết, **cờ hồ sơ mật**).
2. Kéo–thả hoặc chọn tệp. Định dạng nhận: **PDF, DOCX, `.DOC` (Word cũ), TXT, MD**.
   > `.doc` là **bắt buộc**, không phải tùy chọn: 2 trong 3 tài liệu kiểm thử thật là `.doc`. Bỏ định dạng này thì không nghiệm thu được.
3. Chuyên gia bấm **Nạp tài liệu**. Với mỗi tệp, hiện trạng thái theo thời gian thực:
   `Đang đọc → Đang phân đoạn → Đang lập chỉ mục → ✅ Sẵn sàng` (hoặc `❌ Lỗi + lý do cụ thể + gợi ý xử lý`).
4. Hệ thống **tự nhận diện ngôn ngữ** của mỗi tài liệu và ghi nhãn: `tiếng Việt` · `tiếng Anh` · **`song ngữ song song`**.
   - **Tài liệu song ngữ song song** (cùng một nội dung có cả bản Việt và bản Anh, ví dụ bài phát biểu đã được dịch sẵn) được đánh dấu riêng vì có hai giá trị đặc biệt:
     **(a)** trích được cặp thuật ngữ do **người thật** dịch — chất lượng cao hơn máy suy đoán;
     **(b)** dùng làm **bản dịch chuẩn của người thật** để đối chiếu khi luyện, thay cho bản dịch AI sinh (xem §6).
5. Tệp xong hiện trong **danh sách tài liệu**: tên, định dạng, ngôn ngữ, số trang/đoạn, ngày nạp, trạng thái.
6. Mỗi tài liệu có thao tác: **Xem trước**, **Nạp lại**, **Xóa**.
7. Sau khi nạp, gợi ý bước tiếp: *"Trích xuất thuật ngữ từ tài liệu này?"* → nối sang Module 2.

#### Flow chính: Hỏi đáp trên tài liệu

1. Chuyên gia gõ câu hỏi bằng tiếng Việt hoặc tiếng Anh.
2. Tùy chọn thu hẹp phạm vi: **toàn bộ hồ sơ** hoặc **một số tài liệu được chọn**.
3. Hệ thống trả lời, gồm ba phần luôn có mặt:
   - **Câu trả lời** ngắn gọn, đúng ngôn ngữ câu hỏi.
   - **Trích dẫn**: danh sách nguồn dạng `tên tệp · trang/đoạn`, bấm vào mở đúng đoạn văn gốc.
   - **Mức độ chắc chắn**: nếu ngữ cảnh yếu, cảnh báo *"Câu trả lời dựa trên ngữ cảnh hạn chế — nên kiểm tra lại nguồn."*
4. Với câu hỏi mang tính **suy luận** (ví dụ *"dự đoán nội dung sẽ trao đổi trong buổi nghiệm thu"*): phải **tách rõ hai phần** — phần nào đọc được từ tài liệu (có trích dẫn) và phần nào là suy luận (ghi nhãn `suy luận`).
5. Nếu tài liệu không chứa thông tin: trả lời rõ **"Không tìm thấy thông tin này trong tài liệu đã nạp"**, kèm gợi ý *"Tìm trên web?"* → chuyển sang Module 2. **Tuyệt đối không suy diễn thành câu trả lời khẳng định.**
6. Mỗi câu hỏi–trả lời lưu vào **Lịch sử** của hồ sơ, xem lại và tìm kiếm được.
7. Thao tác trên câu trả lời: **Sao chép**, **Ghim vào ghi chú buổi làm việc**, **Đọc to** (→ Module 4).

---

### 2.2 Module 2 — Research Agent (🔍 Nghiên cứu khách hàng & Thuật ngữ)

**Mục đích**: từ vài cái tên, tự động dựng hồ sơ khách hàng/đối tác có nguồn trích dẫn và bảng thuật ngữ song ngữ tái sử dụng được.

#### Flow chính: Nghiên cứu hồ sơ

1. Chuyên gia mở tab **Nghiên cứu**, chọn hồ sơ khách hàng, nhập **thông tin buổi làm việc**:
   - **Tên khách hàng** (bắt buộc) — ví dụ *"Latter-Day Saint Charities"*
   - **Tên đối tác** (không bắt buộc, cho phép nhiều) — ví dụ *"UBND xã Thu Cúc"*, *"Sở Ngoại vụ tỉnh Phú Thọ"*
   - **Chủ đề buổi làm việc** (bắt buộc) — ví dụ *"lễ tổng kết và bàn giao công trình nhà ở cho 113 hộ khó khăn"*
   - **Ngành nghề / lĩnh vực** (không bắt buộc)
   - **Ghi chú thêm** (không bắt buộc) — website, quốc gia, thông tin chuyên gia đã biết
2. Bấm **Bắt đầu nghiên cứu**. Hệ thống hiện **tiến trình minh bạch theo bước**:
   ```
   ⏳ Lập kế hoạch tìm kiếm … 6 truy vấn
   ⏳ [1/6] "Latter-Day Saint Charities Vietnam aid projects" … 8 kết quả
   ⏳ [2/6] "LDSC Phú Thọ viện trợ" … 5 kết quả
   …
   ⏳ Tổng hợp hồ sơ …
   ⏳ Trích xuất thuật ngữ (tài liệu + web) …
   ✅ Hoàn tất · 6 truy vấn · 23 nguồn · 19 thuật ngữ
   ```
   Có nút **Dừng**; kết quả đã thu được vẫn giữ lại.
3. Giới hạn **5–8 truy vấn mỗi lần nghiên cứu**, hiển thị bộ đếm.
4. **Với hồ sơ mật**: trước khi gửi, hiện danh sách truy vấn để chuyên gia **xem và sửa**, vì truy vấn có chứa tên khách hàng (xem §7).

#### Kết quả A — Hồ sơ khách hàng / đối tác

Trình bày dạng thẻ, mỗi bên một thẻ:

| Trường | Nội dung | Bắt buộc có nguồn |
|---|---|---|
| Tên chính thức & tên gọi khác | Tên đầy đủ, tên viết tắt, tên tiếng Anh | ✅ |
| Ngành nghề / lĩnh vực | Ngành chính và ngành phụ | ✅ |
| Quy mô | Số nhân viên, doanh thu/ngân sách, năm thành lập, phạm vi hoạt động | ✅ |
| Sản phẩm / dịch vụ / chương trình chính | Danh sách ngắn | ✅ |
| Tin tức liên quan gần đây | 3–5 tin, có ngày, ưu tiên liên quan chủ đề | ✅ |
| Bối cảnh liên quan chủ đề | Vì sao bên này quan tâm chủ đề buổi làm việc | ✅ |
| Lịch sử hợp tác với đối tác | Đã làm việc với nhau chưa, dự án nào, giá trị bao nhiêu | ✅ |
| Ghi chú cho phiên dịch | Cách đọc tên riêng, tên viết tắt hay dùng, lưu ý văn hóa/nghi thức | ⚠️ ghi rõ nếu là suy luận |

- **Mỗi dòng kèm ít nhất một nguồn URL**, dạng chip bấm được.
- Thông tin không xác minh được đánh dấu `⚠️ chưa xác minh`, không trộn với thông tin có nguồn.
- Trường không tìm thấy để trống kèm *"không tìm thấy thông tin công khai"* — **không đoán**.
- Chuyên gia sửa trực tiếp mọi trường; sửa tay đánh dấu `✏️ chuyên gia chỉnh` và **không bị ghi đè** ở các lần nghiên cứu sau.

#### Kết quả B — Bảng thuật ngữ song ngữ (Glossary)

Trích xuất từ **ba nguồn**: tài liệu một ngôn ngữ · **tài liệu song ngữ song song** (ưu tiên cao nhất, vì cặp dịch do người thật làm) · nội dung web.

Mỗi thuật ngữ gồm:

| Cột | Mô tả |
|---|---|
| Thuật ngữ tiếng Việt | |
| Thuật ngữ tiếng Anh | |
| **Cách đọc** | Phiên âm / gợi ý đọc cho **tên riêng, tên tổ chức, từ viết tắt** — ví dụ *Latter-Day Saint Charities → "Lát-tơ Đây Xây-nt Cha-ri-tis"*, *Thu Cúc*, *Walker*. Chỉ điền khi cần (Q6) |
| Định nghĩa ngắn | |
| Phân loại | pháp lý · kỹ thuật · thương mại · tài chính · chính sách · tên riêng/tổ chức · viết tắt · thành ngữ |
| Nguồn | tên tài liệu + vị trí, hoặc URL |
| Tần suất | số lần xuất hiện |
| Trạng thái | `tự nhận` (mặc định) · `chuyên gia sửa` · `bỏ qua` |
| Độ tin nguồn | `người dịch` (từ tài liệu song ngữ) · `máy suy đoán` (từ tài liệu một ngôn ngữ hoặc web) |

**Cơ chế duyệt — tự nhận hết, sửa sau (Q9):**

1. Thuật ngữ trích ra **vào bảng luôn ở trạng thái `tự nhận` và dùng được ngay** — không có bước duyệt bắt buộc chặn đường đi. Chuyên gia không phải làm gì cả nếu thấy ổn.
2. Bảng sắp xếp theo độ liên quan chủ đề rồi theo tần suất, có lọc theo phân loại và theo độ tin nguồn.
3. Chuyên gia sửa khi thấy sai: **✏️ Sửa** · **🗑️ Bỏ qua** · **🔗 Mở nguồn**. Dòng đã sửa chuyển sang `chuyên gia sửa` và **được ưu tiên tuyệt đối** về sau.
4. Thêm thuật ngữ thủ công được (nguồn = *chuyên gia nhập*, trạng thái = `chuyên gia sửa`).
5. Thuật ngữ đã tồn tại trong hồ sơ (từ lần research trước): **không tạo dòng trùng**, hiện `↻ đã có`. Nếu bản dịch mới khác bản cũ → **cảnh báo xung đột** cạnh nhau; nếu bản cũ là `chuyên gia sửa` thì bản cũ thắng mặc định.
6. Glossary **thuộc về hồ sơ khách hàng**, tự động dùng lại cho mọi buổi sau với khách đó.
7. Xuất bảng ra tệp (CSV/Excel) để mang đi buổi dịch thật, giữ đúng chữ tiếng Việt có dấu.

#### Kết quả C — Cầu nối sang Simulation

Hiện nút nổi bật **"🎙️ Tạo buổi mock từ hồ sơ này"** → chuyển sang Module 3, mang theo hồ sơ khách hàng + đối tác + chủ đề + glossary.

#### Flow phụ: Nghiên cứu lại / bổ sung

- Chạy lại cùng khách hàng với **chủ đề khác**: hồ sơ cập nhật (giữ phần chuyên gia đã sửa), glossary **cộng thêm**, không xóa cũ.
- Mỗi lần nghiên cứu lưu thành **một lần chạy** trong Lịch sử: thời điểm, các truy vấn đã dùng, số nguồn, kết quả.

---

### 2.3 Module 3 — Mock buổi dịch (🎙️ Simulation Engine)

**Mục đích**: tạo áp lực gần giống buổi dịch thật, dùng đúng bối cảnh khách hàng và thuật ngữ đã chuẩn bị, rồi chỉ ra chuyên gia dịch sai/thiếu ở đâu.

#### Bước 1 — Cấu hình buổi mock

1. Chọn hồ sơ khách hàng. Hệ thống **hiện rõ bối cảnh sẽ dùng**:
   ```
   Bối cảnh: Latter-Day Saint Charities (khách hàng) × UBND xã Thu Cúc (đối tác)
   Chủ đề:   Lễ tổng kết và bàn giao công trình nhà ở cho 113 hộ khó khăn
   Glossary: 22 thuật ngữ · 6 do chuyên gia sửa · 4 từ tài liệu song ngữ
   Tài liệu: 3 tệp đã nạp (1 song ngữ song song)
   ```
   - Nếu hồ sơ **chưa research**: cảnh báo *"Chưa có hồ sơ khách hàng và glossary — kịch bản sẽ chung chung. Chạy nghiên cứu trước?"* kèm nút chuyển sang Module 2. Vẫn cho phép tiếp tục.
2. Cấu hình buổi:

| Cấu hình | Lựa chọn | Mặc định |
|---|---|---|
| **Hình thức dịch** | Dịch nối tiếp / Dịch song song | Nối tiếp |
| **Độ khó** | Cơ bản / Trung bình / Khó | Trung bình |
| **Số lượt trao đổi** | 8 – 10 | 8 |
| **Độ dài mỗi lượt** | **≈ 5 câu, đọc lên 30–60 giây** (Q4) | 5 câu |
| **Chiều dịch** | Hai chiều xen kẽ | Hai chiều |
| **Xem trước kịch bản** | Xem trước / **Ẩn kịch bản** | **Ẩn** (Q10) |
| **Phạm vi thuật ngữ** | Toàn bộ / Chỉ dòng chuyên gia đã sửa / Theo phân loại | Toàn bộ |

3. Bấm **Sinh kịch bản**.

#### Bước 2 — Sinh kịch bản

Hội thoại **8–10 lượt** giữa **hai nhân vật**:
- **Nhân vật A** — đại diện phía Việt Nam (UBND xã / Sở Ngoại vụ), nói **tiếng Việt**, có tên và chức danh
- **Nhân vật B** — đại diện khách hàng nước ngoài, nói **tiếng Anh**, có tên và chức danh

Yêu cầu về kịch bản:
- Hai nhân vật **nói xen kẽ** → chuyên gia phải dịch **cả hai chiều** trong cùng một buổi.
- Đi theo **mạch thật của loại sự kiện đó**. Với buổi tổng kết/bàn giao: chào hỏi và giới thiệu đại biểu → báo cáo kết quả dự án → phát biểu của nhà tài trợ → phát biểu của cơ quan quản lý → trao đổi về nghiệm thu, khối lượng, giải ngân → cam kết hợp tác tiếp → cảm ơn và kết thúc.
- **Thuật ngữ từ glossary chèn tự nhiên vào lời thoại** — nằm trong câu nói bình thường, đúng ngữ cảnh, **không phải liệt kê thuật ngữ**.
- Dùng đúng thông tin từ hồ sơ: tên tổ chức, số liệu, tên dự án, bối cảnh.
- Mỗi lượt **≈ 5 câu, đọc lên 30–60 giây**.
- Kèm **bản dịch tham chiếu**. Nếu lượt đó lấy từ **tài liệu song ngữ song song**, dùng luôn **bản dịch của người thật** làm tham chiếu và ghi nhãn `bản dịch của người thật` — tin cậy hơn bản AI sinh.
- Hiển thị **danh sách thuật ngữ đã dùng trong kịch bản**.

Chuyên gia có thể **Sinh lại** hoặc **Sửa lời thoại** trước khi bắt đầu.

#### Bước 3 — Luyện dịch (chế độ Dịch nối tiếp)

Với mỗi lượt:

1. Hiện **nhân vật đang nói** và chiều dịch: `Nhân vật A (Việt) → bạn dịch sang tiếng Anh`.
2. **Phát audio** lời thoại (Module 4), giọng khác nhau cho hai nhân vật. Có **Nghe lại** (đếm số lần). Chế độ ẩn kịch bản: **không hiện chữ**.
3. Bấm **🎙️ Ghi âm**, nói bản dịch, bấm **Dừng**. Trong lúc ghi hiện thời lượng và mức âm lượng.
   - Lối thay thế: **⌨️ Gõ bản dịch** (khi ồn hoặc mic lỗi).
4. Bản nói chuyển thành chữ, hiện **ở dạng sửa được** — sửa lỗi nhận dạng trước khi chấm, để không bị trừ điểm oan.
5. Bấm **Chấm điểm**. Chấm theo bốn tiêu chí, **thang 10 điểm** mỗi tiêu chí (Q3):

| Tiêu chí | Đánh giá điều gì |
|---|---|
| **Độ chính xác nghĩa** /10 | Có truyền đạt đúng ý người nói không, có sai lệch nghĩa không |
| **Thuật ngữ** /10 | Thuật ngữ trong lượt này dịch đúng theo glossary không — nêu **tên từng thuật ngữ** đúng/sai kèm bản đúng |
| **Độ đầy đủ** /10 | Có bỏ sót thông tin nào (số liệu, điều kiện, tên riêng, chức danh) không |
| **Diễn đạt** /10 | Ngữ pháp, tính tự nhiên, mức trang trọng phù hợp nghi thức |

**Điểm lượt** = trung bình 4 tiêu chí, làm tròn 1 chữ số thập phân. Trọng số 4 tiêu chí **bằng nhau ở mặc định** và điều chỉnh được trong Cài đặt; §6 sẽ tự phát hiện trọng số thực tế mà chuyên gia coi trọng.

6. Hiện đồng thời: điểm 4 tiêu chí, nhận xét cụ thể, **bản dịch tham chiếu** (ghi rõ *của người thật* hay *AI sinh*), **bản gốc dạng chữ**, và **thời gian phản hồi**.
7. **Chuyên gia phản biện điểm** — xem §6. Đây là bước thường xuyên, không phải ngoại lệ.
8. Bấm **Lượt tiếp theo**, **Dịch lại lượt này**, hoặc **Kết thúc sớm**.

#### Bước 3' — Luyện dịch (chế độ Dịch song song)

1. Phát **toàn bộ các lượt liên tục**, khoảng nghỉ ngắn giữa các lượt, không dừng chờ.
2. Mic **thu liên tục** suốt buổi; chuyên gia dịch đè lên tiếng nhân vật.
3. Hiện: lượt đang phát, tiến độ tổng, thời gian còn lại.
4. Kết thúc mới chấm: ghép bản thu theo mốc thời gian từng lượt, chấm như trên, **cộng thêm** nhận xét về **độ trễ** và **các đoạn bỏ trống không dịch**.
5. Có **Tạm dừng** (thoát ra chế độ nối tiếp) nếu quá tải.

#### Bước 4 — Báo cáo cuối buổi

- **Điểm tổng /10** và **điểm từng tiêu chí /10**, kèm biểu đồ so sánh các buổi trước cùng khách hàng.
- **Bảng theo lượt**: chiều dịch, điểm, thuật ngữ đúng/sai, thời gian phản hồi, số lần nghe lại, **có bị chuyên gia phản biện hay không**.
- **Thuật ngữ cần ôn** → nút **"Luyện riêng các thuật ngữ này"**.
- **Thuật ngữ mới phát hiện** → nút **Thêm vào glossary**.
- **Nhận xét tổng hợp**: 3–5 điểm mạnh / điểm cần cải thiện bằng tiếng Việt.
- Thao tác: **Lưu vào lịch sử** (tự động), **Xuất báo cáo**, **Chạy lại buổi này**, **Sinh buổi mới cùng cấu hình**.

#### Flow phụ: Lịch sử luyện tập

Tab **Lịch sử** liệt kê buổi mock theo khách hàng và thời gian: xem lại báo cáo, **nghe lại bản thu của mình** (lưu lâu dài, xem §2.4), biểu đồ tiến bộ theo thời gian và theo tiêu chí.

---

> ### ⚠️ Sửa spec (sau Giai đoạn 7): ĐÃ BỎ TÍNH NĂNG GHI ÂM
>
> Mọi tiêu chí liên quan tới ghi âm và nhận dạng giọng nói (**A4.1–A4.4, A4.9, A4.11–A4.13**)
> **không còn áp dụng**. Chuyên gia **gõ** bản dịch thay vì nói.
>
> Lý do: mô hình nhận dạng chạy trên máy chủ nên mỗi lượt phải chờ 15–30 giây; khi công cụ
> được phục vụ qua đường tunnel cho người dùng ở xa thì còn lâu hơn nữa. Thêm nữa nó hay
> viết sai số liệu và đổi sai đơn vị tiền tệ — đúng thứ mà nghề phiên dịch không được sai.
>
> **Phần NGHE lời thoại (TTS) vẫn giữ nguyên** — đó mới là thứ tạo áp lực giống buổi thật.
> Các tiêu chí A4.5–A4.8, A4.10 về đọc lời thoại vẫn còn hiệu lực.

### 2.4 Module 4 — Audio STT / TTS (🔊 Nghe & Nói)

**Mục đích**: làm việc luyện tập giống buổi dịch thật (nghe bằng tai, dịch bằng miệng), và dùng độc lập để gỡ băng ghi âm.

#### Flow: Nói → Chữ (STT)

1. Điểm dùng: trong mock buổi dịch, hoặc tab riêng để **gỡ băng** tệp audio buổi thật.
2. Hai đường vào:
   - **Ghi âm trực tiếp**: bấm ghi → đồng hồ + mức âm lượng → bấm dừng. Có giới hạn thời lượng mỗi lượt và cảnh báo khi gần tới hạn.
   - **Tải tệp audio lên**: WAV, MP3, M4A.
3. Chọn **ngôn ngữ của bản nói** (Việt / Anh / tự nhận dạng).
4. Hiện trạng thái xử lý; xong thì ra **transcript sửa được**.
5. Chất lượng kém → cảnh báo và **đánh dấu các đoạn máy không chắc**, kèm nút **Ghi lại**.
6. Thao tác: **Sửa**, **Xác nhận**, **Sao chép**, **Ghi lại**.

#### Flow: Chữ → Nói (TTS)

1. Điểm dùng: lời thoại nhân vật trong mock; bản dịch tham chiếu; đọc thuật ngữ khi luyện từ vựng; đọc to câu trả lời Module 1.
2. Tự chọn **ngôn ngữ theo nội dung**.
3. **Hai giọng khác nhau cho hai nhân vật**.
4. Điều khiển: **Phát / Tạm dừng / Nghe lại**, **tốc độ đọc** (chậm / bình thường / nhanh — dùng để tăng độ khó).
5. Audio đã sinh **lưu lại tái dùng**: nghe lại cùng một lượt không phải sinh lại.
6. **Tải audio về** để luyện ngoài app.

#### Flow: Quản lý bản ghi âm (Q11)

- Bản ghi giọng chuyên gia **lưu lâu dài theo mặc định**, gắn với từng lượt trong từng buổi, để nghe lại so sánh tiến bộ.
- Trang **Quản lý dung lượng**: tổng dung lượng đang dùng, chia theo hồ sơ khách hàng và theo buổi.
- **Xóa chủ động** ở ba mức: xóa một lượt · xóa toàn bộ bản thu của một buổi · xóa toàn bộ bản thu của một hồ sơ khách hàng.
- Xóa **hỏi xác nhận** và nói rõ số tệp + dung lượng sẽ mất. Xóa bản thu **không** làm mất báo cáo điểm.
- Có tùy chọn **tự xóa bản thu cũ hơn N ngày** (mặc định: tắt).

#### Flow: Kiểm tra thiết bị

Trước buổi mock đầu tiên: **Kiểm tra âm thanh** — phát một câu mẫu (kiểm loa) và thu 3 giây rồi phát lại (kiểm mic). Không có mic hoặc mic bị chiếm → báo rõ và đề xuất chế độ gõ bản dịch.

---

## 3. Acceptance Criteria

Điều kiện để coi từng module là **hoàn thành**. Mỗi tiêu chí phải kiểm chứng được bằng một lần chạy thật, **trên bộ tài liệu ở [../data/test_documents/](../data/test_documents/README.md)**.

### 3.1 Module 1 — RAG tài liệu

| # | Tiêu chí |
|---|---|
| A1.1 | Nạp thành công **PDF, DOCX, `.DOC`, TXT** — trong đó **cả 3 tệp kiểm thử thật đều nạp được**, nội dung trích xuất đúng (kiểm bằng Xem trước) |
| A1.2 | Tài liệu tiếng Việt có dấu hiển thị và tìm được đúng, không lỗi font/encoding |
| A1.3 | **Ba câu hỏi mẫu T1/T2/T3** (xem manifest tài liệu test) đều trả về đúng nội dung, mỗi câu có **ít nhất một trích dẫn trỏ đúng tệp và đúng đoạn** |
| A1.4 | Câu hỏi **T5 ngoài phạm vi tài liệu** → trả lời "không tìm thấy trong tài liệu", **không bịa ra số liệu** |
| A1.5 | Hỏi tiếng Việt trả lời tiếng Việt; hỏi tiếng Anh trả lời tiếng Anh |
| A1.6 | Câu hỏi suy luận (T3) **tách rõ** phần có trong tài liệu và phần suy luận |
| A1.7 | Hệ thống **nhận đúng nhãn ngôn ngữ** cả 3 tệp, trong đó nhận ra `zPHÁT BIỂU 22 6.doc` là **song ngữ song song** |
| A1.8 | Xóa một tài liệu → nội dung của nó không còn xuất hiện trong bất kỳ câu trả lời nào sau đó |
| A1.9 | Mỗi tệp lỗi có **lý do cụ thể**; một tệp lỗi **không làm hỏng** việc nạp các tệp còn lại trong cùng lô |
| A1.10 | Nạp lại tệp đã có → không tạo bản trùng, không làm câu trả lời bị lặp |
| A1.11 | Lịch sử hỏi đáp lưu và xem lại được sau khi khởi động lại app |

### 3.2 Module 2 — Research Agent

| # | Tiêu chí |
|---|---|
| **A2.1** | **Tiêu chí chính:** nhập **một tên công ty + một chủ đề**, hệ thống trả về đủ ba thứ: **(a)** hồ sơ tóm tắt, **(b)** bảng từ vựng **≥ 15 thuật ngữ liên quan**, **(c)** một kịch bản hội thoại **8–10 lượt có dùng các thuật ngữ đó** |
| A2.2 | Chạy với **"Latter-Day Saint Charities" + chủ đề bàn giao nhà ở Thu Cúc** → hồ sơ nêu đúng: là tổ chức nhân đạo Hoa Kỳ, có hoạt động viện trợ tại Việt Nam/Phú Thọ |
| A2.3 | Hồ sơ tóm tắt có tối thiểu: ngành nghề, quy mô, chương trình chính, ≥ 2 tin tức liên quan, bối cảnh gắn chủ đề |
| A2.4 | **Mỗi thông tin trong hồ sơ có ≥ 1 URL nguồn**, mở được và nội dung trang thực sự chứa thông tin đã nêu (kiểm ngẫu nhiên 5 mục) |
| A2.5 | Thông tin không xác minh được **đánh dấu rõ**, tách khỏi thông tin có nguồn |
| A2.6 | Mỗi thuật ngữ có đủ: thuật ngữ Việt, thuật ngữ Anh, định nghĩa ngắn, phân loại, nguồn, **độ tin nguồn** |
| A2.7 | **Cột cách đọc** có dữ liệu cho ít nhất các tên riêng: *Latter-Day Saint Charities*, *Walker*, *Thu Cúc*, *Phú Thọ* |
| A2.8 | Chạy trên bộ tài liệu test → trích được **≥ 15 thuật ngữ**, và **chuyên gia đánh giá ≥ 12 trong 15 mục đầu là thực sự liên quan** (người dùng xác nhận, không phải máy tự chấm) |
| A2.9 | Có **≥ 3 thuật ngữ gắn nhãn `người dịch`** trích từ tài liệu song ngữ (ví dụ *nhà tạm, nhà dột nát → temporary and dilapidated houses*) |
| A2.10 | Thuật ngữ trích từ **cả tài liệu và web** — nhìn cột nguồn thấy cả hai loại |
| A2.11 | Thuật ngữ mới vào bảng **dùng được ngay** không cần bước duyệt; dòng chuyên gia sửa được ưu tiên về sau |
| A2.12 | Số truy vấn tìm kiếm mỗi lần **không vượt 8**, hiển thị được số đã dùng |
| A2.13 | Chạy nghiên cứu **lần thứ hai** cùng khách hàng → **không tạo thuật ngữ trùng lặp**; xung đột bản dịch nêu ra cho chuyên gia chọn; dòng `chuyên gia sửa` **không bị ghi đè** |
| A2.14 | Glossary **tự động có mặt** ở buổi mock tiếp theo của cùng khách hàng |
| A2.15 | Nhập tên công ty **không có thông tin công khai** → báo rõ không tìm thấy, **không sinh hồ sơ bịa** |
| A2.16 | Xuất glossary ra tệp, mở bằng Excel, giữ đúng chữ tiếng Việt có dấu |

### 3.3 Module 3 — Mock buổi dịch

| # | Tiêu chí |
|---|---|
| A3.1 | Kịch bản có **8–10 lượt**, hai nhân vật rõ ràng, **nói xen kẽ Việt–Anh** |
| A3.2 | Mỗi lượt dài **≈ 5 câu**, đọc lên **30–60 giây** (đo bằng thời lượng audio TTS) |
| A3.3 | Kịch bản **dùng thuật ngữ từ glossary**, **chèn trong lời thoại tự nhiên** — chuyên gia xác nhận đọc lên nghe như người thật nói, không phải câu liệt kê thuật ngữ |
| A3.4 | Kịch bản **dùng đúng bối cảnh hồ sơ** (tên tổ chức, số liệu 113 hộ / 6,78 tỷ, loại sự kiện) — không phải hội thoại chung chung |
| A3.5 | Một buổi có **cả hai chiều dịch**: ít nhất một lượt Việt→Anh và một lượt Anh→Việt |
| A3.6 | Chạy **end-to-end**: phát audio → nói → transcript → chấm → hiện kết quả, **trọn một buổi 8 lượt, ba buổi liên tiếp không lỗi** |
| A3.7 | Mỗi lượt có: **điểm 4 tiêu chí thang 10**, nhận xét cụ thể, bản dịch tham chiếu, danh sách thuật ngữ đúng/sai |
| A3.8 | Bản dịch tham chiếu **ghi rõ** là *của người thật* hay *AI sinh*; lượt lấy từ tài liệu song ngữ phải dùng bản của người thật |
| A3.9 | Nhận xét thuật ngữ **gọi đúng tên thuật ngữ cụ thể** và nêu bản dịch đúng theo glossary |
| A3.10 | Ba mức độ khó tạo kịch bản **khác biệt nhận thấy được** |
| A3.11 | Cả hai hình thức **nối tiếp** và **song song** chạy được hết một buổi |
| A3.12 | Mặc định **ẩn kịch bản**; bản gốc dạng chữ chỉ hiện sau khi đã chấm |
| A3.13 | Báo cáo cuối buổi lưu vào lịch sử, **mở lại được sau khi khởi động lại app**, kèm bản thu |
| A3.14 | Sửa transcript trước khi chấm → điểm chấm theo **bản đã sửa** |
| A3.15 | Thoát app giữa buổi → mở lại **khôi phục được** buổi đang dở hoặc giữ các lượt đã hoàn thành |
| A3.16 | Glossary rỗng vẫn sinh được kịch bản, kèm cảnh báo chất lượng chung chung |

### 3.4 Module 4 — Audio STT/TTS

| # | Tiêu chí |
|---|---|
| A4.1 | Ghi âm liên tục **≥ 60 giây** không mất tiếng, không cắt cụt |
| A4.2 | Transcript **tiếng Việt** đọc hiểu được, đủ dùng để chấm (chuyên gia xác nhận sai sót ở mức sửa nhanh được) |
| A4.3 | Transcript **tiếng Anh** đọc hiểu được, đủ dùng để chấm |
| A4.4 | Transcript luôn **sửa được trước khi chấm điểm** |
| A4.5 | TTS đọc được **cả tiếng Việt và tiếng Anh**, rõ ràng, đúng ngôn ngữ nội dung |
| A4.6 | Hai nhân vật có **hai giọng phân biệt được** khi nghe |
| A4.7 | **Nghe lại** cùng một lượt **không phải chờ sinh lại** audio |
| A4.8 | Không có mic / mic bị chiếm → báo rõ và **vẫn luyện được** bằng chế độ gõ bản dịch |
| A4.9 | Audio im lặng hoặc quá ngắn → báo *"không nhận được tiếng nói"*, **không sinh transcript rỗng rồi chấm 0 điểm** |
| A4.10 | Bước **kiểm tra loa + mic** chạy được và cho kết quả đúng thực tế |
| A4.11 | Bản thu **còn nguyên sau khi khởi động lại app**, nghe lại được từ tab Lịch sử |
| A4.12 | **Xóa bản thu** ở cả ba mức (lượt / buổi / hồ sơ) hoạt động đúng, có xác nhận, và **không làm mất báo cáo điểm** |
| A4.13 | Trang quản lý dung lượng hiện đúng dung lượng thực tế đang dùng |

### 3.5 Vòng phản hồi & hiệu chỉnh (§6)

| # | Tiêu chí |
|---|---|
| A5.1 | Ở mỗi lượt đã chấm, chuyên gia **sửa được điểm từng tiêu chí** và **ghi nhận định của mình** |
| A5.2 | Báo cáo lưu **cả điểm AI và điểm chuyên gia**, không ghi đè lẫn nhau |
| A5.3 | Nhận định chuyên gia **lưu lại được** và xem lại theo hồ sơ khách hàng |
| A5.4 | Từ buổi sau, phần chấm điểm **có dùng lại các nhận định trước đó** — kiểm chứng được: cùng một lỗi đã bị phản biện thì không lặp lại nhận xét kiểu cũ |
| A5.5 | Trang **Đối chiếu chấm điểm**: xem độ lệch trung bình giữa điểm AI và điểm chuyên gia theo từng tiêu chí, theo thời gian |
| A5.6 | Chuyên gia sửa một cặp thuật ngữ → buổi mock sau **dùng bản đã sửa**, không dùng lại bản cũ |

### 3.6 UI / UX (Q13)

| # | Tiêu chí |
|---|---|
| A6.1 | Toàn bộ tính năng trong spec này **có đường vào rõ ràng từ giao diện** — không có tính năng nào chỉ chạy được bằng cách sửa cấu hình |
| A6.2 | Mỗi nút có **nhãn chữ nói rõ hành động** (không chỉ icon trần), nút nguy hiểm (Xóa) khác màu và có xác nhận |
| A6.3 | Mọi tác vụ chạy lâu (nạp tài liệu, nghiên cứu, chấm điểm, sinh audio) có **chỉ báo tiến trình**, không để màn hình đứng im |
| A6.4 | Từ Dashboard tới **bất kỳ tác vụ chính** nào không quá **2 lần bấm** |
| A6.5 | Dashboard hiện: **việc đang dở**, buổi làm việc sắp tới, tiến bộ theo thời gian, thuật ngữ cần ôn |
| A6.6 | Áp dụng đúng theme trong CLAUDE.md (navy + trắng, font Inter/Nunito, emoji có chủ đích), **nhất quán trên mọi tab** |
| A6.7 | Biểu đồ dùng Plotly, đọc được nhãn, có tiêu đề và đơn vị |
| A6.8 | Mọi thông báo lỗi **bằng tiếng Việt**, nói rõ chuyện gì xảy ra và **làm gì tiếp** |
| A6.9 | Chạy thử với người chưa từng dùng: **tự hoàn thành được luồng chính** mà không cần hỏi |

### 3.7 Bảo mật (§7)

| # | Tiêu chí |
|---|---|
| A7.1 | Bật cờ **hồ sơ mật** → trước mỗi lần gửi dữ liệu ra ngoài, hệ thống **hiện trước nội dung sẽ gửi** và chờ đồng ý |
| A7.2 | **Nhật ký gửi ra ngoài** ghi đủ: thời điểm, module, đích đến, số ký tự; xem và xuất được |
| A7.3 | Hệ thống **chỉ gửi các đoạn ngữ cảnh đã truy hồi**, không gửi toàn bộ tài liệu — kiểm chứng bằng nhật ký |
| A7.4 | **Không có API key nào** trong mã nguồn hoặc trong log |
| A7.5 | `git status` sạch: **không tệp tài liệu khách hàng, bản ghi âm, hay DB nào** ở diện chờ commit |
| A7.6 | **Xóa vĩnh viễn một hồ sơ khách hàng** → mất sạch tài liệu, chỉ mục, glossary, bản thu, lịch sử của hồ sơ đó |
| A7.7 | Với hồ sơ mật, **truy vấn tìm kiếm web hiện ra cho chuyên gia sửa** trước khi gửi |

### 3.8 Tiêu chí xuyên suốt

| # | Tiêu chí |
|---|---|
| A0.1 | Chạy được trên máy cá nhân bằng một quy trình khởi động ngắn, có hướng dẫn |
| A0.2 | **Không phát sinh chi phí**: chỉ dùng free tier và thành phần chạy local |
| A0.3 | Dữ liệu (hồ sơ, tài liệu, glossary, lịch sử, bản thu) **còn nguyên sau khi khởi động lại** |
| A0.4 | Bốn tab (Dashboard, Tài liệu, Mock buổi dịch, Lịch sử) + khu vực Nghiên cứu đều mở được, không tab chết |
| A0.5 | Một luồng hoàn chỉnh **từ tên khách hàng đến báo cáo buổi mock** chạy được trong **một lần ngồi máy, dưới 15 phút** |

---

## 4. Edge cases cần xử lý

Nguyên tắc chung: **luôn nói rõ chuyện gì xảy ra, luôn có đường đi tiếp, không bao giờ mất dữ liệu đang làm.**

### 4.1 Tải & xử lý tài liệu

| Tình huống | Hành vi mong đợi |
|---|---|
| **Tệp `.doc` cũ, cấu trúc nhị phân lạ, trích xuất ra ký tự rác** | Nhận biết phần rác và **loại bỏ khỏi chỉ mục**; nếu tỷ lệ rác cao thì cảnh báo *"chất lượng trích xuất thấp"* và cho Xem trước để chuyên gia tự đánh giá — **không đưa ký tự rác vào câu trả lời** |
| **Tệp song ngữ mà máy nhận sai thành một ngôn ngữ** | Cho chuyên gia **đổi nhãn ngôn ngữ thủ công**; đổi nhãn thì trích xuất thuật ngữ lại |
| Định dạng không hỗ trợ (XLSX, PPTX, ảnh, ZIP) | Từ chối trước khi xử lý, nêu rõ danh sách định dạng nhận được |
| Tệp quá lớn | Báo trước ngưỡng dung lượng, đề xuất tách tệp |
| **PDF scan / ảnh chụp, không có lớp chữ** | Báo *"tệp này là ảnh scan, chưa đọc được chữ"*, đề xuất cách thay thế — **không** nạp tài liệu rỗng rồi âm thầm trả lời sai (OCR là non-goal) |
| Tệp hỏng, đọc dở dang | Báo lỗi cho đúng tệp đó, tệp khác trong lô vẫn nạp bình thường |
| Tệp có mật khẩu | Báo rõ tệp được bảo vệ, đề nghị bỏ mật khẩu rồi nạp lại |
| Tệp rỗng hoặc quá ít nội dung | Báo *"tệp không có nội dung để lập chỉ mục"* |
| Tên tệp tiếng Việt có dấu, khoảng trắng, ký tự đặc biệt | Xử lý bình thường, hiển thị đúng tên (cả 3 tệp test đều thuộc dạng này) |
| Nạp lại tệp trùng tên | Hỏi: ghi đè hay giữ cả hai — không âm thầm nhân đôi nội dung |
| Tài liệu lẫn cả tiếng Việt và tiếng Anh nhưng **không song song** (trộn lẫn, không phải bản dịch của nhau) | Không gắn nhãn song ngữ, không trích cặp thuật ngữ từ đó |
| Ngắt giữa lúc nạp | Không để tài liệu ở trạng thái nửa vời gây câu trả lời sai; đánh dấu lỗi để nạp lại |
| Hỏi đáp khi hồ sơ chưa có tài liệu | Báo rõ, gợi ý nạp tài liệu hoặc chuyển sang Nghiên cứu web |

### 4.2 Âm thanh (STT / TTS)

| Tình huống | Hành vi mong đợi |
|---|---|
| Không có mic / không cấp quyền mic | Phát hiện sớm ở bước kiểm tra âm thanh, báo rõ, chuyển sang chế độ gõ bản dịch |
| Mic bị ứng dụng khác chiếm (Zoom, Teams) | Báo cụ thể nguyên nhân, đề nghị đóng ứng dụng kia rồi thử lại |
| Ghi âm im lặng hoàn toàn | Báo *"không nhận được tiếng nói"*, cho ghi lại — **không chấm 0 điểm cho bản trống** |
| **Audio ồn, không nghe rõ** | Vẫn ra transcript nhưng **cảnh báo chất lượng thấp**, đánh dấu đoạn không chắc, đề nghị ghi lại; nếu vẫn chấm thì ghi chú *"chấm trên transcript chất lượng thấp"* vào báo cáo |
| Nói lẫn hai ngôn ngữ trong một lượt | Không coi là lỗi; giữ nguyên phần ngôn ngữ khác, để chuyên gia sửa |
| Nói quá nhỏ / quá xa mic | Cảnh báo mức âm lượng thấp **ngay trong lúc ghi** |
| Ghi âm vượt giới hạn lượt | Cảnh báo trước khi tới hạn; tới hạn thì dừng và **giữ phần đã ghi** |
| Nhận dạng chạy quá lâu | Hiện tiến trình, cho hủy, giữ audio để thử lại |
| TTS không đọc được | Chuyển cách đọc thay thế; vẫn không được thì **hiện lời thoại dạng chữ** để buổi mock tiếp tục |
| **TTS đọc sai tên riêng / viết tắt** (*LDSC*, *Thu Cúc*, *Walker*) | Dùng **cột cách đọc** trong glossary để đọc đúng; chuyên gia sửa được cách đọc rồi phát lại |
| Tệp audio tải lên hỏng / sai định dạng | Báo rõ, không làm treo giao diện |
| **Hết dung lượng đĩa vì bản thu lưu lâu dài** | Báo rõ, mở trang Quản lý dung lượng, gợi ý xóa bản thu cũ |

### 4.3 LLM (sinh nội dung, chấm điểm)

| Tình huống | Hành vi mong đợi |
|---|---|
| **Hết thời gian chờ (timeout)** | Báo rõ, có nút **Thử lại**; **giữ nguyên** những gì đã làm được |
| **Hết quota / vượt free tier** | Báo rõ *"đã dùng hết lượt miễn phí hôm nay"*, nêu thời điểm khả dụng lại, đề nghị dừng và tiếp tục sau |
| Bị giới hạn tốc độ gọi | Tự chờ và thử lại có giới hạn số lần, hiển thị đang chờ; không im lặng |
| Trả về kết quả sai cấu trúc | Thử lại một lần; vẫn lỗi thì báo rõ và **không hiện điểm sai/rỗng** |
| Trả về rỗng hoặc bị chặn nội dung | Báo rõ nguyên nhân, cho sinh lại hoặc sửa đầu vào |
| Sinh kịch bản **< 8 lượt** hoặc **không dùng thuật ngữ nào** | Nhận biết không đạt, tự sinh lại một lần, rồi mới hiện (kèm ghi chú nếu vẫn chưa đạt) |
| Lượt sinh ra **quá ngắn hoặc quá dài** so với 5 câu / 30–60 giây | Nhận biết và sinh lại lượt đó |
| Kịch bản chèn thuật ngữ **thô, nhồi từ khóa** | Có nút **Sinh lại**; ghi nhận vào §6 để lần sau tránh |
| Chấm điểm **quá khắt khe hoặc quá dễ dãi** | Chuyên gia phản biện điểm (§6); báo cáo lưu cả hai; độ lệch vào trang Đối chiếu chấm điểm |
| Tài liệu quá dài, vượt sức xử lý một lần | Xử lý theo phần, không im lặng cắt bỏ nội dung |
| Đang chấm mà bấm sang lượt khác | Không lẫn kết quả giữa các lượt |

### 4.4 Research Agent & Web search

| Tình huống | Hành vi mong đợi |
|---|---|
| **Không có internet** | Báo rõ trước khi bắt đầu; Nghiên cứu web tắt, nhưng **trích xuất thuật ngữ từ tài liệu đã nạp vẫn chạy được** |
| Mất mạng **giữa** quá trình | Giữ kết quả các truy vấn đã xong, báo phần chưa xong, cho **tiếp tục** khi có mạng |
| Công cụ tìm kiếm chặn / giới hạn tần suất | Giảm tốc và thử lại có giới hạn; vẫn bị chặn thì báo rõ và **trả về kết quả một phần** thay vì hỏng cả lần chạy |
| **Không tìm thấy tổ chức** | Báo *"không tìm thấy thông tin công khai"*, gợi ý nhập tên đầy đủ/website/quốc gia — **không sinh hồ sơ suy diễn** |
| **Tên trùng nhiều đơn vị khác nhau** | Nêu các khả năng kèm nguồn để **chuyên gia chọn**, không tự chọn rồi coi là chắc |
| **Tên viết tắt mà web hiểu sai** (ví dụ *LDSC*) | Ưu tiên tên đầy đủ tìm được trong tài liệu đã nạp; nếu lệch thì nêu cả hai khả năng |
| Kết quả **nhầm sang tổ chức khác** cùng tên | Mọi mục đều có nguồn nên chuyên gia kiểm và **xóa/sửa từng dòng**; có nút *"Kết quả không đúng — tìm lại"* |
| Nguồn trả phí, chỉ đọc phần mở đầu | Dùng phần đọc được, ghi rõ *"nguồn giới hạn truy cập"* |
| Nội dung nguồn không phải tiếng Việt/Anh | Nêu ngôn ngữ nguồn; dịch phần dùng đến, giữ liên kết gốc |
| Thông tin trái ngược giữa các nguồn | **Hiện song song cả hai kèm nguồn**, không tự chọn một bên |
| **Thông tin cá nhân về nhân sự** (ví dụ tên người dự lễ) | Chỉ giữ nội dung nghề nghiệp công khai và liên quan buổi làm việc |
| Nguồn quá cũ | Hiện ngày của nguồn để chuyên gia tự đánh giá độ mới |
| **Trích được < 15 thuật ngữ** | Báo rõ số thực tế và lý do, đề xuất: nạp thêm tài liệu, mở rộng chủ đề, hoặc thêm tay |
| Thuật ngữ trùng nhưng **bản dịch khác nhau** | Hiện xung đột cạnh nhau kèm nguồn và độ tin nguồn; bản `chuyên gia sửa` và bản `người dịch` được ưu tiên |
| Bấm Dừng giữa lúc nghiên cứu | Giữ kết quả đã thu, ghi rõ là **kết quả một phần** |

### 4.5 Vòng phản hồi & hiệu chỉnh

| Tình huống | Hành vi mong đợi |
|---|---|
| Chuyên gia phản biện **trái ngược nhau** giữa hai buổi (cùng lỗi, lần khen lần phê) | Không im lặng chọn một bên; hiện *"nhận định trước của bạn khác lần này"* kèm cả hai để tự xử lý |
| Nhận định tích lũy quá nhiều, không dùng hết được | Ưu tiên nhận định **mới nhất** và **cùng khách hàng / cùng phân loại thuật ngữ** |
| Chuyên gia sửa điểm nhưng **không ghi lý do** | Vẫn lưu điểm sửa; nhưng chỉ nhận định **có lý do** mới dùng để hiệu chỉnh cách chấm |
| Nhận định làm chấm điểm **lệch quá xa** | Trang Đối chiếu chấm điểm hiện xu hướng; có nút **Đặt lại hiệu chỉnh về mặc định** |
| Xóa một buổi mock | Nhận định trong buổi đó **vẫn giữ lại** (là kiến thức về cách chấm, không phải dữ liệu buổi) — trừ khi chuyên gia chọn xóa cả |

### 4.6 Bảo mật

| Tình huống | Hành vi mong đợi |
|---|---|
| Chuyên gia bật cờ mật **sau khi** đã nạp tài liệu và đã gửi vài lần ra ngoài | Nói rõ *"đã có N lần gửi trước khi bật chế độ mật"*, chỉ tới nhật ký để tự kiểm |
| Tài liệu mật lỡ nằm ngoài thư mục dữ liệu | `.gitignore` chặn sẵn theo định dạng; ngoài ra app cảnh báo nếu phát hiện tài liệu ngoài thư mục quản lý |
| Thiếu API key trong `.env` | Báo rõ đang thiếu gì và cách bổ sung; **không** in key ra log kể cả khi lỗi |
| Nhật ký gửi ra ngoài phình to | Cho lọc theo hồ sơ/thời gian, cho xuất ra tệp rồi dọn |
| Xóa hồ sơ khách hàng | Xác nhận hai bước, nói rõ số tệp/dung lượng/số buổi sẽ mất, rồi **xóa sạch** cả chỉ mục và bản thu |

### 4.7 Môi trường & hệ thống

| Tình huống | Hành vi mong đợi |
|---|---|
| Máy yếu, xử lý audio rất chậm | Hiện tiến trình và thời gian ước tính; cho hủy; gợi ý chế độ gõ bản dịch |
| Đóng app giữa buổi mock | Mở lại khôi phục buổi đang dở, hoặc giữ các lượt đã hoàn thành |
| Mở hai cửa sổ app cùng lúc | Không làm hỏng dữ liệu; nếu không hỗ trợ thì báo rõ (dùng cá nhân, một phiên) |
| Hết dung lượng đĩa | Báo rõ, chỉ ra thư mục chiếm nhiều chỗ và mở trang Quản lý dung lượng |
| Múi giờ / định dạng ngày | Hiển thị theo giờ máy, nhất quán toàn app |

---

## 5. Non-goals (KHÔNG làm trong MVP này)

### 5.1 Người dùng & triển khai
- ❌ **Nhiều người dùng, đăng nhập, phân quyền** — đúng một người dùng.
- ❌ **Ứng dụng di động** và giao diện tối ưu cho điện thoại.
- ❌ **Triển khai cloud, tên miền, HTTPS, chia sẻ qua mạng** — chỉ chạy local.
- ❌ **Đồng bộ nhiều máy, sao lưu tự động lên cloud** (trái với yêu cầu bảo mật §7).
- ❌ **Cài đặt đóng gói một cú nhấp** — chấp nhận khởi động bằng dòng lệnh.

### 5.2 Chi phí & mô hình
- ❌ **Bất kỳ dịch vụ trả phí** nào ngoài free tier.
- ❌ **Huấn luyện / tinh chỉnh (fine-tune) mô hình riêng.**
  > Lưu ý quan trọng về Q2: "AI học và cải thiện" trong spec này **không phải huấn luyện mô hình**. Nó là cơ chế **lưu nhận định của chuyên gia và đưa lại vào ngữ cảnh khi chấm những lần sau** (§6). Đây là điều làm được trong phạm vi miễn phí; fine-tune thật thì không.
- ❌ **So sánh nhiều mô hình, cho người dùng chọn mô hình.**

### 5.3 Phạm vi ngôn ngữ & nội dung
- ❌ **Cặp ngôn ngữ khác ngoài Việt ↔ Anh.**
- ❌ **OCR tài liệu scan / ảnh chụp** — chỉ báo lỗi rõ ràng.
- ❌ **Đọc bảng biểu, sơ đồ, hình ảnh trong tài liệu** — chỉ xử lý phần chữ.
- ❌ **Dịch máy chất lượng xuất bản** — bản dịch tham chiếu chỉ để đối chiếu khi luyện.
- ❌ **Từ điển chuyên ngành mua bản quyền** — glossary xây từ tài liệu và web.

### 5.4 Phạm vi luyện tập & đánh giá
- ❌ **Đánh giá phát âm, ngữ điệu, độ trôi chảy, giọng** — chỉ chấm nội dung bản dịch.
- ❌ **Dịch song song thời gian thực độ trễ thấp** — chế độ song song ở MVP là bản đơn giản: phát liên tục, thu song song, chấm sau.
- ❌ **Nhiều hơn hai nhân vật** trong một kịch bản; tạp âm hội trường, chồng tiếng, ngắt lời.
- ❌ **Nhận diện người nói** trong bản ghi âm buổi thật.
- ❌ **Chấm điểm chuẩn hóa theo thang nghề nghiệp** — điểm chỉ để so sánh tiến bộ của chính người dùng.
- ❌ **Lộ trình học tập tự động, nhắc nhở, gamification, streak.**
- ❌ **Chế độ dịch viết** (đọc chữ → gõ bản dịch) như một module riêng (Q12). Gõ bản dịch chỉ tồn tại như **lối thay thế khi mic lỗi**.

### 5.5 Bảo mật — mức KHÔNG làm
- ❌ **Mã hóa toàn bộ dữ liệu trên đĩa, mật khẩu mở app, khóa theo phiên.** Máy cá nhân một người dùng; bảo mật ở MVP là **kiểm soát dữ liệu gửi ra ngoài** + **không commit dữ liệu khách hàng**, không phải chống truy cập vật lý.
- ❌ **Chạy hoàn toàn không có internet** (Q8) — nêu ra ở đây để rõ: yêu cầu offline đã **bị loại khỏi phạm vi**, đổi lấy chất lượng kết quả tốt nhất.
- ❌ **Kiểm toán bảo mật độc lập, chống rò rỉ ở mức doanh nghiệp.**

### 5.6 Tích hợp & vận hành
- ❌ **Tích hợp CRM, lịch, email, Zoom/Teams.**
- ❌ **Chia sẻ hồ sơ/glossary cho người khác, cộng tác.**
- ❌ **API công khai cho ứng dụng bên ngoài dùng.**
- ❌ **Xuất báo cáo trình bày chuyên nghiệp** (PDF có thương hiệu).
- ❌ **Đo lường sử dụng, phân tích hành vi, telemetry** — cũng là yêu cầu bảo mật.
- ❌ **Kiểm thử tự động độ phủ cao** — kiểm thử tập trung vào các đường chính trong Acceptance Criteria.

---

## 6. Vòng phản hồi & hiệu chỉnh chấm điểm (Q2)

**Vấn đề**: bản dịch tham chiếu và điểm số do AI sinh chưa đủ tin cậy để coi là chuẩn. Nhưng chuyên gia thì có chuyên môn — nên để chuyên gia là người phán quyết, và hệ thống phải nhớ phán quyết đó.

### 6.1 Ba mức độ tin của bản dịch tham chiếu

| Mức | Nguồn | Dùng khi nào |
|---|---|---|
| ⭐⭐⭐ **Bản dịch của người thật** | Tài liệu song ngữ song song đã nạp (ví dụ bài phát biểu đã dịch sẵn) | Ưu tiên cao nhất. Lượt nào lấy từ đây thì dùng bản này làm chuẩn |
| ⭐⭐ **Bản chuyên gia tự đặt** | Chuyên gia gõ bản dịch chuẩn cho một lượt | Khi chuyên gia muốn chốt cách dịch cho lượt quan trọng |
| ⭐ **AI sinh** | LLM | Mặc định khi không có hai nguồn trên. **Luôn ghi rõ nhãn này** |

### 6.2 Flow phản biện điểm

Ngay sau khi AI chấm một lượt, dưới phần điểm luôn có khối **"Nhận định của bạn"**:

1. **Đồng ý** — một nút, xong. (Đường nhanh, không tạo ma sát.)
2. **Sửa điểm** — sửa điểm từng tiêu chí trong 4 tiêu chí, thang 10.
3. **Ghi nhận định** — ô chữ tự do, ví dụ: *"'nghiệm thu' ở đây phải dịch là acceptance, không phải inspection — AI chấm sai tiêu chí Thuật ngữ"*, hoặc *"bản dịch của tôi rút gọn nhưng đúng nghi thức, không nên bị trừ Độ đầy đủ"*.
4. **Chốt cách dịch** — nâng bản dịch của chính mình lên thành bản tham chiếu chuẩn cho lượt đó (mức ⭐⭐).
5. Nếu nhận định liên quan một thuật ngữ: nút **Sửa luôn trong glossary** → cập nhật ngay, dòng đó thành `chuyên gia sửa`.

Báo cáo lưu **cả điểm AI và điểm chuyên gia**, hiển thị cạnh nhau, không ghi đè.

### 6.3 Hệ thống dùng lại nhận định thế nào

Từ buổi sau, khi chấm điểm, hệ thống **đưa lại các nhận định liên quan vào ngữ cảnh chấm**, ưu tiên theo thứ tự: cùng khách hàng → cùng phân loại thuật ngữ → mới nhất. Cụ thể:

- Thuật ngữ đã bị chuyên gia sửa → **chấm theo bản đã sửa**, không theo bản cũ.
- Nhận định dạng *"đừng trừ điểm vì X"* → đưa vào như một quy tắc chấm cho hồ sơ khách hàng đó.
- Bản dịch chuyên gia đã chốt (⭐⭐) → dùng làm tham chiếu, thay bản AI.

> Nói cho rõ: đây là **hiệu chỉnh bằng ngữ cảnh và bằng dữ liệu đã lưu**, không phải huấn luyện lại mô hình (xem §5.2). Giới hạn: lượng nhận định đưa vào mỗi lần chấm có hạn, nên hệ thống chọn phần liên quan nhất chứ không đưa tất cả.

### 6.4 Trang Đối chiếu chấm điểm

Cho chuyên gia thấy AI đang chấm lệch bao nhiêu so với mình:

- Độ lệch trung bình giữa **điểm AI** và **điểm chuyên gia**, tách theo từng tiêu chí, theo thời gian.
- Tiêu chí nào AI hay chấm sai nhất → biết mà không tin phần đó.
- Xu hướng: độ lệch có giảm dần không (nếu không giảm thì cơ chế hiệu chỉnh không hiệu quả — cần xem lại).
- Nút **Đặt lại hiệu chỉnh về mặc định**.
- Vì trọng số 4 tiêu chí mặc định bằng nhau, trang này cũng cho thấy **trọng số thực tế** mà chuyên gia coi trọng, để chỉnh lại cho đúng.

---


> **⚠️ Sửa spec (đợt sửa lớp tin cậy) — §7 đã đổi ở bốn chỗ.** Xem `CLAUDE.md > Bảo mật`.
>
> 1. **Cửa ra đổi tên và đổi bản chất.** `security/egress.py` (context manager bọc quanh
>    lệnh gọi) → `security/gateway.py` (`execute()` đích thân gọi provider). Client mạng
>    dồn hết vào `security/providers/`. Ba invariant tự động canh: C1a, C1b, C1c.
> 2. **Đơn vị đồng ý là THAO TÁC, không phải lệnh gọi.** Một lần `/research/run` gọi ra
>    ngoài tới ~13 lần; hỏi từng lệnh thì thao tác không bao giờ hoàn thành được vì giao
>    diện thử lại cả request. **Hệ quả phải nói rõ: thao tác nhiều lệnh gọi KHÔNG hiện
>    trước được nội dung** — đây là mức bảo đảm THẤP HƠN mô tả gốc của §7.
> 3. **Nhật ký có 3 trạng thái** thay cho cờ `consented` nhị phân. Nhà cung cấp ném lỗi
>    KHÔNG chứng minh dữ liệu chưa rời máy, nên `attempt_failed` vẫn tính là "đã cố gửi".
> 4. **`sentence-transformers` tải model từ HuggingFace** — lệnh gọi mạng không mang dữ
>    liệu khách hàng và không đi qua gateway. Con số "ba đường ra" chỉ nói về dữ liệu hồ sơ.

## 7. Bảo mật & quyền riêng tư (Q7)

### 7.1 Điểm mấu chốt: chỉ có ba đường dữ liệu ra khỏi máy

Đây là lý do yêu cầu bảo mật (Q7) và yêu cầu chất lượng (Q8) **không xung đột nhiều như tưởng**. Theo tech stack trong CLAUDE.md, phần lớn xử lý đã chạy local: tạo embedding, vector DB, nhận dạng giọng nói, đọc văn bản, cơ sở dữ liệu — **tất cả trên máy**. Chỉ còn **ba đường ra**:

| # | Đường ra | Nội dung gửi đi | Kiểm soát |
|---|---|---|---|
| **E1** | Gọi LLM trên mạng (sinh nội dung, chấm điểm, tổng hợp hồ sơ) | **Chỉ các đoạn ngữ cảnh đã truy hồi** + câu hỏi + lời nhắc — **không bao giờ gửi toàn bộ tài liệu** | Xem trước nội dung sẽ gửi (hồ sơ mật); ghi nhật ký mọi lần gửi |
| **E2** | Truy vấn tìm kiếm web | Chuỗi truy vấn, **có chứa tên khách hàng và chủ đề** | Hiện danh sách truy vấn cho chuyên gia **sửa trước khi gửi** (hồ sơ mật); tối đa 8 truy vấn |
| **E3** | Đọc lời thoại thành giọng nói (edge-tts → Microsoft, gTTS → Google) | Lời thoại của kịch bản, **có chứa tên khách hàng, số liệu dự án, tên địa phương** | Xem trước nội dung sẽ đọc (hồ sơ mật); ghi nhật ký. **Lần nghe lại lấy từ cache KHÔNG gọi mạng** nên không tính là egress |

Ngoài E1, E2 và E3, **không có gì rời khỏi máy**: không telemetry, không đồng bộ cloud, không phân tích hành vi.

> **Ghi chú sửa spec (Giai đoạn 4).** Bản v2 của spec ghi chỉ có HAI đường ra, vì lúc đó
> tech stack còn dùng Coqui TTS chạy local. Khi đổi sang edge-tts (quyết định D1), việc đọc
> lời thoại trở thành một đường ra thật. Bỏ sót điều này nghĩa là hồ sơ mật bị gửi dữ liệu
> đi mà không hỏi — nên E3 đã được bổ sung và cho đi qua đúng cửa egress như E1/E2.
> **Hệ quả cần biết:** với hồ sơ mật, không có phương án đọc lời thoại hoàn toàn offline.
> Bạn chọn: đồng ý gửi lời thoại cho dịch vụ TTS, hoặc luyện với lời thoại dạng chữ.

### 7.2 Chế độ hồ sơ mật

Mỗi hồ sơ khách hàng có cờ **mật / thường**, đổi được lúc nào cũng được.

Khi bật **mật**:
- Trước **mỗi** lần gửi ra ngoài (E1, E2, E3): hiện **đúng nội dung sẽ gửi** và chờ đồng ý. Có tùy chọn *"đồng ý cho cả buổi làm việc này"* để không bị hỏi liên tục.
- Truy vấn tìm kiếm hiện ra dạng **sửa được** — chuyên gia có thể bỏ tên riêng, tìm bằng từ chung.
- Nhãn `🔒 MẬT` hiện thường trực trên mọi màn hình của hồ sơ đó.
- Xuất tệp (glossary, báo cáo) có cảnh báo trước.

### 7.3 Nhật ký dữ liệu gửi ra ngoài

Ghi lại **mọi** lần dữ liệu rời khỏi máy, kể cả hồ sơ thường:

`thời điểm · hồ sơ khách hàng · module · đích đến (LLM / tìm kiếm) · số ký tự đã gửi · nội dung tóm lược`

Xem theo hồ sơ và theo thời gian, xuất ra tệp được. Đây là công cụ để chuyên gia **tự kiểm chứng** cam kết ở §7.1 chứ không phải tin lời.

### 7.4 Dữ liệu trên máy

- Toàn bộ dữ liệu nằm trong thư mục dữ liệu của project: tài liệu đã nạp, chỉ mục, cơ sở dữ liệu, bản ghi âm, cache audio.
- **`.gitignore` đã chặn** toàn bộ thư mục dữ liệu, cộng thêm lưới an toàn theo định dạng (`*.doc`, `*.docx`, `*.pdf`, các tệp audio) để tài liệu khách hàng lỡ để ngoài cũng không bị commit. Chỉ manifest tài liệu test được commit.
- **API key** chỉ nằm trong `.env`, không vào mã nguồn, **không in ra log** kể cả khi báo lỗi.
- **Xóa vĩnh viễn một hồ sơ khách hàng**: xóa sạch tài liệu, chỉ mục, glossary, bản thu, lịch sử của hồ sơ đó, có xác nhận hai bước.

---

## 8. Quyết định đã chốt (Q1–Q15)

| # | Câu hỏi | Quyết định | Ảnh hưởng tới spec |
|---|---|---|---|
| Q1 | Tài liệu kiểm thử | Đã có 3 tệp thật (LDSC × xã Thu Cúc, Phú Thọ), lưu tại `data/test_documents/` kèm manifest. Câu hỏi mẫu T1–T5 | §3 toàn bộ nghiệm thu chạy trên bộ này; phát sinh yêu cầu `.doc` và tài liệu song ngữ |
| Q2 | Độ tin của bản dịch tham chiếu | AI chấm trước, chuyên gia phản biện, hệ thống dùng lại nhận định | **§6** (mục mới) |
| Q3 | Thang điểm | **10 điểm** mỗi tiêu chí, 4 tiêu chí, trọng số bằng nhau ở mặc định | §2.3 bước 3.5 |
| Q4 | Độ dài lượt thoại | **≈ 5 câu, đọc lên 30–60 giây** | §2.3, A3.2 |
| Q5 | Ngành của glossary | **Đa ngành**, mỗi khách một ngành | Phân loại thuật ngữ mở, không cố định danh mục ngành |
| Q6 | Cách đọc tên riêng | **Có** — glossary thêm cột *Cách đọc* | §2.2, A2.7, dùng cho TTS |
| Q7 | Bảo mật / NDA | **Có** — chế độ hồ sơ mật + nhật ký gửi ra ngoài | **§7** (mục mới), §3.7 |
| Q8 | Yêu cầu offline | **Không cần offline** — ưu tiên chất lượng tốt nhất | Bỏ tiêu chí offline; ghi rõ ở §5.5 |
| Q9 | Duyệt thuật ngữ | **Tự nhận hết, sửa sau** | §2.2 mục "Cơ chế duyệt" |
| Q10 | Mặc định kịch bản | **Ẩn kịch bản** | §2.3 bảng cấu hình, A3.12 |
| Q11 | Bản ghi âm | **Lưu lâu dài** + xóa chủ động 3 mức + tự xóa theo tuổi (tắt mặc định) | §2.4, A4.11–A4.13 |
| Q12 | Chế độ dịch viết | **Không cần** module riêng; chỉ là lối thay thế khi mic lỗi | §5.4 |
| Q13 | UI | Dễ dùng, đẹp, hiệu quả, đủ tính năng, nút bấm rõ ràng | **§3.6** (9 tiêu chí nghiệm thu UI) |
| Q14 | Số hồ sơ khách hàng | **< 10** | Ưu tiên chiều sâu hồ sơ hơn quản lý danh sách lớn |
| Q15 | Phạm vi | **Giữ đủ 4 module, không cắt**, hoàn thiện nhất có thể | §9 |

---

## 9. Phạm vi & thứ tự xây dựng

Chuyên gia yêu cầu **giữ đủ 4 module và hoàn thiện nhất có thể** (Q15). Spec giữ nguyên toàn bộ phạm vi, không cắt gì.

Một điều cần nói thẳng: phạm vi hiện tại **lớn hơn mốc "2 tuần"** ghi trong CLAUDE.md, vì hai mục mới (§6 vòng phản hồi, §7 bảo mật) và các tiêu chí UI ở §3.6 là công việc thật, không phải phần thêm nhẹ. Cách xử lý được đề xuất: **không cắt tính năng, nhưng xây theo thứ tự dưới đây**, để bất kỳ thời điểm nào dừng lại cũng đã có một sản phẩm dùng được đầu–cuối chứ không phải bốn nửa module.

| Thứ tự | Khối | Vì sao trước |
|---|---|---|
| 1 | **Nền dữ liệu + nạp tài liệu (M1)** kèm `.doc` và nhận diện song ngữ | Mọi module khác đều đọc từ đây; bộ tài liệu test phải nạp được trước đã |
| 2 | **Research Agent + Glossary (M2)** | Tạo ra tài sản tái dùng (hồ sơ + thuật ngữ) mà M3 phụ thuộc; cũng là phần chuyên gia thấy giá trị sớm nhất |
| 3 | **Mock buổi dịch (M3)** ở chế độ chữ trước, chưa cần audio | Kiểm được chất lượng kịch bản và chấm điểm mà chưa phải lo STT/TTS |
| 4 | **Audio (M4)** ghép vào M3 | Biến M3 thành trải nghiệm thật; là phần nặng máy nhất nên làm khi mọi thứ khác đã đứng |
| 5 | **Vòng phản hồi (§6)** | Cần có dữ liệu điểm thật từ vài buổi mock mới hiệu chỉnh được |
| 6 | **Hoàn thiện UI (§3.6)** xuyên suốt, siết lại ở cuối | Làm dần từ đầu, nhưng đợt siết cuối cần thấy toàn bộ tính năng đã có |

**§7 Bảo mật không nằm trong thứ tự này** vì nó phải có **từ dòng code đầu tiên**: `.gitignore` đã xong, còn nhật ký gửi ra ngoài và cờ hồ sơ mật phải được xây cùng lúc với M1, không phải khâu vào sau — khâu sau thì đã có dữ liệu lọt ra rồi.

---

## 10. Câu hỏi còn mở

Không có câu nào chặn bước Plan. Ba điểm nhỏ có thể quyết trong lúc làm:

| # | Câu hỏi | Mặc định đang dùng nếu không đổi |
|---|---|---|
| O1 | Trọng số 4 tiêu chí chấm điểm — bạn chưa nói tiêu chí nào quan trọng nhất | Để **bằng nhau**, và §6.4 sẽ tự cho thấy trọng số thực tế bạn coi trọng qua các lần bạn sửa điểm |
| O2 | Bản tiếng Việt gốc của Kế hoạch 165/KH-BCĐ (tệp DOCX hiện chỉ có bản tiếng Anh) | Chạy với những gì đang có. Nếu bạn bổ sung được bản Việt thì chất lượng trích thuật ngữ song ngữ tăng đáng kể |
| O3 | Với hồ sơ mật, mặc định nên hỏi xác nhận **từng lần gửi** hay **một lần cho cả buổi** | Hỏi **một lần cho cả buổi làm việc**, vì hỏi từng lần sẽ làm việc luyện tập bị ngắt liên tục |

---

*Bước tiếp theo theo workflow trong CLAUDE.md: **Plan Mode** — lập kế hoạch kỹ thuật chi tiết → chuyên gia review kế hoạch → mới bắt đầu code.*
