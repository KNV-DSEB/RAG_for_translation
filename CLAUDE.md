# CLAUDE.md

## Project Overview
AI Assistant hỗ trợ chuyên gia dịch thuật cá nhân, gồm 3 module chính:
1. Tổng hợp tài liệu dịch thuật (RAG knowledge base)
2. Mock buổi dịch (Simulation Engine)
3. Audio hỗ trợ (chỉ TTS — đọc lời thoại; đã bỏ ghi âm)
Mục đích: dùng cá nhân, chi phí 0 đồng, hoàn thành trong 2 tuần.

## Tech Stack
- Backend: FastAPI — **Python 3.11.9 pin cứng** (`D:\Python\python.exe`), venv tạo bằng `uv`.
  KHÔNG dùng Python 3.14 mặc định của máy: hệ sinh thái ML chưa chắc có wheel.
- Frontend: **HTML/CSS/JS tự viết, KHÔNG dùng Streamlit, KHÔNG có bước build.**
  ES module thuần chạy thẳng trên trình duyệt; FastAPI phục vụ luôn tệp tĩnh ở cùng cổng 8000.
  Lý do bỏ Streamlit: nó áp layout khối dọc và widget hình dạng cố định, nên giao diện
  không thể có bản sắc riêng — CSS đè lên chỉ tới được mức "dashboard Streamlit tử tế".
  KHÔNG thêm React/bundler/node_modules: dự án quản bằng `uv`, 9 màn hình không đáng đổi
  lấy một chuỗi công cụ JS.
- Biểu đồ: **SVG tự vẽ** trong `web/js/charts.js`, KHÔNG dùng Plotly.
  Biểu đồ Plotly trông ra biểu đồ Plotly — đúng cái "nhìn như template" cần tránh.
  Ba biểu đồ của dự án đều đơn giản và dùng chung bảng màu/bộ chữ với phần còn lại.
- LLM: Gemini Flash API (free tier), **hai bậc model**. Không có phương án offline (Q8).
  Free tier giới hạn `GenerateRequestsPerDayPerProjectPerModel` — tính riêng cho TỪNG model.
  Đo thực tế trên key của dự án: `gemini-2.5-flash` chỉ **20 request/ngày**. Vì vậy:
  - `GEMINI_MODEL` (bậc *quality*, mặc định `gemini-3.5-flash`) — việc ít nhưng khó:
    sinh kịch bản mock, tổng hợp hồ sơ khách hàng, hỏi đáp tài liệu
  - `GEMINI_MODEL_LIGHT` (bậc *light*, mặc định `gemini-3.5-flash-lite`) — việc nhiều nhưng
    có cấu trúc: trích thuật ngữ, chấm điểm, lập kế hoạch truy vấn
  - `GEMINI_FALLBACKS` — hết hạn mức ngày của một model thì tự chuyển sang model kế tiếp
  - Giới hạn theo PHÚT thì chờ rồi thử lại; theo NGÀY thì chờ vô ích, phải đổi model.
    Logic này nằm trong `backend/security/llm.py`, KHÔNG lặp lại ở nơi khác.
- Vector DB: ChromaDB (local, persistent)
- Embedding: sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
- STT: **KHÔNG CÓ.** Đã bỏ tính năng ghi âm — chuyên gia GÕ bản dịch, không nói.
  Lý do: nhận dạng chạy trên máy chủ nên mỗi lượt chờ 15–30 giây, qua đường tunnel còn
  lâu hơn; và mô hình hay viết sai số liệu (nghe "sáu tỷ bảy trăm tám mươi triệu đồng"
  thành "$6,780 million") — đúng thứ phiên dịch không được sai.
  Bỏ được `faster-whisper`, `ctranslate2`, `av` khỏi phần cài đặt.
  LƯU Ý: `torch` VẪN CẦN — `sentence-transformers` dùng nó để tạo embedding cho RAG.
  Phần NGHE lời thoại vẫn giữ: đó mới là cái tạo áp lực giống buổi thật.
- TTS: **edge-tts (chính) — gTTS (fallback)**.
  Không dùng Coqui TTS: nặng 1.5–2 GB RAM, chậm trên CPU, tiếng Việt yếu, dự án đã ngừng phát triển.
- Database: SQLite (đơn giản cho dùng cá nhân)
- Orchestration: **KHÔNG dùng LangChain.** Gọi thẳng SDK Gemini + ChromaDB, tự viết vòng lặp
  retrieval và vòng lặp research agent. Lý do chính: mọi lệnh gọi ra ngoài BẮT BUỘC đi qua
  `backend/security/gateway.py` để ghi nhật ký và chặn khi hồ sơ mật — framework che giấu
  lệnh gọi thì không bảo đảm được điều này.

## Ràng buộc phần cứng (đã khảo sát)
- RAM 7.8 GB → ngân sách chặt: nạp model kiểu lười, giữ tiến trình backend dưới ~2.5 GB
- CPU 12 nhân logic, không dùng GPU
- Không có ffmpeg trên PATH — không còn cần nữa từ khi bỏ nhận dạng giọng nói

## Architecture
- `/backend` — FastAPI app (`main.py`, `config.py`, `db.py`, `schemas.py`)
- `/backend/routes` — workspaces, documents, research, glossary, simulate, speech, feedback, history, security
- `/backend/security` — ⭐ `gateway.py` (cửa duy nhất ra ngoài) + `providers/` (nơi DUY NHẤT
  giữ client mạng: gemini, ddgs, tts_edge, tts_gtts) + `llm.py` (chuỗi model dự phòng, quota)
- `/backend/rag` — extractors, nhận diện ngôn ngữ, chunking, embedding, retrieval
- `/backend/research` — search, dựng hồ sơ khách hàng, trích thuật ngữ
- `/backend/simulation` — LLM prompt templates, sinh kịch bản, scoring logic
- `/backend/feedback` — §6 vòng phản hồi: lưu nhận định chuyên gia, hiệu chỉnh chấm điểm
- `/backend/speech` — STT/TTS wrappers
- `/web` — giao diện: `index.html` + `static/css` + `js/` (ES module, không build)
- `/web/js/screens` — 9 màn hình: dashboard, documents, research, glossary, mock,
  calibration, history, security, storage
- `/web/js/api.js` — cổng duy nhất gọi backend; bắt 409 consent ở MỘT chỗ rồi tự chạy lại
- `/data` — SQLite DB, ChromaDB, `documents/`, `recordings/`, `tts_cache/`, `test_documents/`
- `/_specs` — spec files cho từng feature (do Claude Code tạo trong Plan Mode)

## Coding Conventions
- Python: PEP8, type hints bắt buộc cho function signatures
- Đặt tên biến/function tiếng Anh, comment tiếng Việt nếu cần giải thích logic nghiệp vụ
- Mỗi module có docstring mô tả input/output rõ ràng
- Không hardcode API key — dùng .env + python-dotenv
- Error handling: luôn try/except cho gọi API bên ngoài (Gemini, tìm kiếm, TTS)

## UI/Design System
- ⭐ **Signature — "cái sống"**: mọi khối song ngữ dựng thành cặp cột có một đường kẻ
  mảnh chạy dọc ở giữa, số lượt nằm trong máng giữa, nguồn trái → đích phải.
  Đường kẻ đó CHÍNH LÀ việc phiên dịch. Dùng ở: lượt mock, dòng glossary, bản dịch
  tham chiếu, xem trước tài liệu song ngữ. Đây là thứ để nhớ ra sản phẩm này.
- Chữ: **Be Vietnam Pro** (vẽ riêng cho dấu tiếng Việt — tuyên bố lấy tiếng Việt làm gốc)
  + **JetBrains Mono** cho số giây/điểm/số lượt. Đúng hai họ chữ. Tự host `.woff2`,
  KHÔNG gọi Google Fonts CDN (nhanh hơn và không lộ việc sử dụng ra ngoài).
- Màu: `--ink #0E1A2B` · `--paper #FAFBFD` (giấy lạnh, CỐ Ý không ngả kem) ·
  `--vi #1B4079` navy cho phía tiếng Việt · `--en #175E63` mòng két cho phía tiếng Anh ·
  `--flag #A8324A` carmine cho việc cần soát. Hai màu ngôn ngữ dùng KIỀM CHẾ:
  vạch 3px bên trái + nhãn, không tô nền.
- CSS trong `/web/static/css`: `tokens.css` → `base.css` → `components.css` → `screens.css`
- Chuyển động: dashboard nghề nghiệp thì gọn và nhanh. Chỉ animate `transform`/`opacity`,
  nêu đích danh thuộc tính (không `transition: all`), dưới 300ms, easing tự đặt
  `cubic-bezier(0.23, 1, 0.32, 1)`. Nút có `:active { scale(0.97) }`. Hover phải bọc
  `@media (hover: hover) and (pointer: fine)`. Tôn trọng `prefers-reduced-motion`.
  Đúng MỘT khoảnh khắc được dàn dựng: chuyển lượt trong buổi mock.
- Màn Mock chạy TOÀN KHUNG, bỏ hết chrome — dạng buồng lái, không phải biểu mẫu.

## Testing & Acceptance Criteria
- Nguồn sự thật: **79 tiêu chí trong `_specs/mvp-spec.md` §3** (A1.x → A7.x, A0.x)
- Fixture nghiệm thu: **`data/test_documents/README.md`** — bộ tài liệu thật LDSC × xã Thu Cúc,
  kèm đáp án đối chiếu và 5 câu hỏi mẫu T1–T5. Không nghiệm thu bằng dữ liệu bịa.
- Test RAG bằng T1/T2/T3 (phải có trích dẫn đúng) và T5 (phải từ chối bịa)
- Test mock dịch end-to-end: nghe lời thoại → gõ bản dịch → LLM chấm điểm → hiển thị kết quả,
  3 buổi liên tiếp. KHÔNG còn bước ghi âm.
- Không viết code khi chưa qua Plan Mode review

## Bảo mật (bắt buộc, xem `_specs/mvp-spec.md` §7)
- Chỉ có **đúng ba đường dữ liệu ra khỏi máy**: (E1) gọi LLM, (E2) truy vấn tìm kiếm,
  (E3) đọc lời thoại bằng edge-tts/gTTS. Cả ba BẮT BUỘC đi qua `backend/security/gateway.py`.
  Lần TTS lấy từ cache không gọi mạng nên không tính là egress.
  LƯU Ý: `sentence-transformers` còn TẢI MODEL từ HuggingFace lần đầu chạy. Đó là lệnh gọi
  mạng nhưng KHÔNG mang dữ liệu khách hàng, và không đi qua gateway — nêu ra để con số
  "ba đường" không bị hiểu là "không còn gói tin nào khác rời máy".
- **`gateway.execute()` gọi provider, không chỉ bọc quanh nó.** Context manager kiểu cũ
  (`egress()`) thì luôn có thể quên bọc; gateway đích thân gọi thì không có đường vòng.
  Ba invariant tự động canh, nằm trong `tests/test_c1_single_door.py`:
  - **C1a** chỉ `security/providers/**` được import `httpx`/`requests`/`gtts`/`edge_tts`/`ddgs`/`google.genai`
  - **C1b** chỉ `security/gateway.py` được import `security.providers`
  - **C1c** (runtime) gọi `execute()` ngoài `gateway.operation()` → chặn trước khi chạm mạng
- **Đơn vị đồng ý là THAO TÁC, không phải lệnh gọi.** Một lần `/research/run` gọi ra ngoài
  tới ~13 lần; hỏi từng lệnh thì giao diện thử lại cả request và lần chạy không bao giờ kết
  thúc. Mỗi route egress mở `gateway.operation(kind=..., declares=[...])` khai TRƯỚC gọi ai
  và tối đa bao nhiêu lần; `max_calls` do MÁY thực thi, câu chữ trên hộp thoại SINH RA từ
  chính khai báo đó nên không thể lệch. Nhật ký vẫn ghi RIÊNG từng lệnh gọi.
  Đánh đổi: thao tác nhiều lệnh gọi **không hiện trước được nội dung** — hộp thoại nói thẳng.
- Quyền cấp bằng `consent_request_id` do máy chủ phát ra; giao diện không khai được đích hay
  nhà cung cấp. Thao tác vào lại qua header `X-Operation-Id`, phải qua **6 kiểm tra** (tồn
  tại · đúng hồ sơ · đúng loại · đúng `request_fingerprint` · chưa hết hạn · chưa xong).
- Nhật ký có **3 trạng thái**: `blocked` (chưa chạm mạng) · `attempt_succeeded` ·
  `attempt_failed`. Cả hai `attempt_*` đều tính là "đã cố gửi": nhà cung cấp ném lỗi KHÔNG
  chứng minh dữ liệu chưa rời máy. **Không dùng chữ "đã gửi thành công" ở bất kỳ đâu.**
- Quyền `session` bị xoá lúc `init_db()` khởi động, nên nhãn "cho tới khi đóng ứng dụng"
  đúng nghĩa đen.
- Chỉ gửi **đoạn ngữ cảnh đã truy hồi**, không bao giờ gửi toàn bộ tài liệu.
- Hồ sơ có cờ mật → chờ chuyên gia đồng ý trước, và hiện trước nội dung **khi biết được**.
  Thao tác một lệnh gọi (đọc lời thoại, chấm điểm, hỏi tài liệu) thì hiện ĐỦ, không cắt.
  Thao tác nhiều lệnh gọi (nghiên cứu) thì truy vấn do bước đầu sinh ra nên chưa biết trước
  — hộp thoại phải NÓI THẲNG điều đó, không hiện khối rỗng cho có.
- API key chỉ nằm trong `.env`. Không hardcode, **không in ra log kể cả khi báo lỗi**.
- `.gitignore` đã chặn `/data/*` + `*.doc|docx|pdf` + tệp audio. Trước khi commit luôn kiểm
  `git status` không có tài liệu khách hàng, bản ghi âm, hay DB.

## Đồng bộ tài liệu
Bất cứ thay đổi nào xung khắc với CLAUDE.md phải cập nhật CLAUDE.md **trong cùng lần thay đổi đó**,
không tích lại sửa sau. CLAUDE.md luôn phải là mô tả đúng của hệ thống thật.

## Constraints
- KHÔNG dùng API trả phí ngoài free tier Gemini
- KHÔNG cần authentication/multi-user (chỉ 1 người dùng)
- KHÔNG deploy cloud, chạy local trên máy cá nhân
- Ưu tiên tốc độ triển khai hơn tối ưu hiệu năng (MVP mindset)

## Workflow
Luôn theo quy trình: Spec (mô tả tính năng, không code) → Plan Mode (kế hoạch kỹ thuật chi tiết) → Review (tôi duyệt plan trước khi code) → Implement.

## Research Agent Module (NEW)
- Tool tìm kiếm: duckduckgo-search / `ddgs` (free, primary), Tavily API (free tier, fallback nếu cần)
- Framework: **không dùng LangChain/LangGraph**. Vòng lặp tuần tự tự viết:
  lập kế hoạch truy vấn → gọi search qua `gateway.py` → tổng hợp → trích thuật ngữ.
  Đơn giản, kiểm soát được, và bảo đảm mọi lệnh gọi ra ngoài đều qua đúng một cửa.
- Input: tên khách hàng, tên đối tác, chủ đề buổi làm việc (do chuyên gia nhập)
- Output: 
  1. Hồ sơ khách hàng/đối tác (JSON: ngành nghề, quy mô, tin tức liên quan, nguồn trích dẫn)
  2. Bảng từ vựng song ngữ (JSON: term_source, term_target, definition, category, nguồn)
  3. Kịch bản mô phỏng hội thoại (dùng cho module Simulation)
- Luôn lưu URL nguồn kèm mỗi thông tin thu thập để chuyên gia kiểm tra lại (traceability)
- Giới hạn: tối đa 5-8 query search mỗi lần research để tránh vượt free tier

## Terminology Extraction Logic
- Input **ba nguồn**, không phải hai:
  1. **Tài liệu song ngữ song song** (cùng nội dung có sẵn cả bản Việt và bản Anh) — ưu tiên cao nhất
     vì cặp dịch do người thật làm. Gắn nhãn `aligned_from_parallel` — **không** phải
     `human_translated`: hai bản tài liệu đúng là do người dịch, nhưng việc GHÉP thuật ngữ
     A ↔ B là do LLM suy ra, nên nhãn cũ tuyên bố một mức xác nhận chưa từng xảy ra.
  2. Tài liệu một ngôn ngữ đã nạp → `độ tin = máy suy đoán`
  3. Kết quả web research → `độ tin = máy suy đoán`
- Method: LLM prompt trích thuật ngữ chuyên ngành. Với tài liệu song ngữ: đưa khối VI + khối EN
  và yêu cầu trả về cặp thuật ngữ (không tự viết thuật toán căn chỉnh câu).
- Output format: `{term_vi, term_en, pronunciation, definition, category, source, confidence, frequency, status}`
  - `pronunciation` — cách đọc tên riêng/viết tắt, dùng cho cả TTS đọc đúng (Q6)
  - `status` — `tự nhận` (mặc định, **dùng được ngay không cần duyệt** — Q9) → `chuyên gia sửa` → `bỏ qua`
- Lưu vào SQLite table `glossary`, khóa duy nhất `(workspace_id, term_vi_normalized)` để chống trùng
- Thứ tự ưu tiên khi xung đột: `expert_edited` > `aligned_from_parallel` > `machine_guess`.
  Dòng chuyên gia đã sửa KHÔNG BAO GIỜ bị lần research sau ghi đè.
- Tái sử dụng cho mọi buổi dịch sau với cùng khách hàng

## Simulation with Research Context
- Trước khi tạo kịch bản mock dịch, Simulation Engine PHẢI query bảng `glossary` và hồ sơ khách hàng đã research
- Prompt LLM sinh hội thoại phải chèn tự nhiên các từ vựng đã trích xuất vào lời thoại nhân vật
- Độ khó kịch bản có thể điều chỉnh theo mức độ chuyên gia chọn (cơ bản/trung bình/khó)
- Kịch bản: **8–10 lượt**, hai nhân vật nói xen kẽ Việt–Anh → chuyên gia dịch **cả hai chiều**
- Mỗi lượt **≈ 5 câu, đọc lên 30–60 giây** (Q4). Validate ngay lúc sinh bằng ước lượng số từ,
  không đạt thì tự sinh lại một lần rồi mới hiện cho chuyên gia
- Mặc định **ẩn kịch bản** (Q10) — chỉ hiện bản gốc dạng chữ sau khi đã chấm
- Chấm điểm: 4 tiêu chí (nghĩa / thuật ngữ / đầy đủ / diễn đạt), **thang 10 điểm** mỗi tiêu chí,
  trọng số bằng nhau ở mặc định (Q3)
- Bản dịch tham chiếu theo thứ tự tin cậy: **người thật** (từ tài liệu song ngữ) → **chuyên gia đã chốt**
  → **AI sinh**. Luôn hiện nhãn đang dùng mức nào

## Feedback Loop (spec §6)
- Sau mỗi lượt chấm, chuyên gia phản biện: Đồng ý / Sửa điểm / Ghi nhận định / Chốt cách dịch
- Lưu **cả điểm AI và điểm chuyên gia**, không ghi đè lẫn nhau
- Buổi sau: `feedback/calibration.py` lấy nhận định liên quan (cùng workspace → cùng category → mới nhất)
  chèn vào prompt chấm điểm như luật chấm. Sửa thuật ngữ được **áp cứng**, không để LLM đoán lại.
- LƯU Ý: đây là **hiệu chỉnh bằng ngữ cảnh**, KHÔNG phải fine-tune mô hình. Đừng mô tả sai với người dùng.