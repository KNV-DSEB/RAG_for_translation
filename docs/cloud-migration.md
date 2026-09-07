# Chuyển lên cloud — inventory và ánh xạ

Tài liệu này ghi **trạng thái thật đo được** trước khi chuyển, để sau này đối chiếu số
liệu chứ không tin vào trí nhớ. Mọi con số dưới đây lấy từ máy đang chạy, không ước lượng.

Điểm quay lui: tag `v0.9-local-baseline` → commit `3f11664`.
Dữ liệu local (SQLite, Chroma, `documents/`, `tts_cache/`) **không bị migration đụng tới**.

---

## 1. Ánh xạ local → cloud

| Local | Cloud | Ghi chú |
|---|---|---|
| SQLite `data/app.db` | Supabase PostgreSQL | 21 bảng, 400 dòng |
| ChromaDB `data/chroma/` | PostgreSQL + pgvector | 73 vector, 384 chiều |
| `data/documents/` | Supabase private storage | 3 tệp, 141.087 byte |
| `data/tts_cache/` | Supabase private storage | 17 tệp, 2.712.432 byte |
| quyền `session` xoá lúc khởi động | quyền gắn với **phiên trình duyệt**, TTL 8 giờ | xem §4 |
| không có danh tính | Supabase Auth, `owner_user_id` = UUID (`sub`) | xem §3 |

---

## 2. Trạng thái đã kiểm kê

### 2.1 SQLite — 21 bảng, 400 dòng

| Bảng | Dòng | Có `workspace_id`? |
|---|---:|---|
| `workspaces` | 1 | — (chính nó) |
| `documents` | 3 | có |
| `document_chunks` | 73 | có |
| `glossary` | 30 | có |
| `glossary_conflicts` | 0 | không (qua FK `glossary`) |
| `profiles` | 3 | có |
| `profile_fields` | 22 | không (qua FK `profiles`) |
| `profile_sources` | 134 | không (qua FK `profile_fields`) |
| `research_runs` | 1 | có |
| `engagements` | 0 | có |
| `mock_sessions` | 1 | có |
| `mock_turns` | 8 | không (qua FK `mock_sessions`) |
| `turn_attempts` | 4 | không (qua FK `mock_turns`) |
| `scores` | 4 | không (qua FK `turn_attempts`) |
| `expert_verdicts` | 4 | có |
| `qa_history` | 9 | có |
| `operations` | 9 | có |
| `operation_calls` | 10 | không (qua FK `operations`) |
| `consent_grants` | 0 | có |
| `pending_consents` | 4 | có |
| `egress_log` | 80 | có |

**7 bảng không mang `workspace_id`** mà thừa kế qua khóa ngoại. Khi thêm quyền sở hữu,
mỗi truy vấn tới các bảng đó phải join lên tới `workspaces.owner_user_id` — không được
tin `workspace_id` do client gửi.

### 2.2 Cấu trúc riêng của SQLite phải xử lý

Đếm trên `backend/` + `tests/`:

| | Số lần | Cách xử lý |
|---|---:|---|
| `get_conn()` | 95 | **cửa duy nhất** — đặt adapter ở đây |
| `conn.execute(...)` | 159 | giữ nguyên chữ SQL, adapter dịch `?` → `%s` |
| `lastrowid` | 18 | Postgres không có; adapter tự thêm `RETURNING id` |
| `AUTOINCREMENT` | 18 | chỉ trong `_SCHEMA` của `db.py` |
| `INSERT OR REPLACE/IGNORE` | 1 | đổi sang `ON CONFLICT` |
| `PRAGMA` | 4 | chỉ dùng cho schema/health, tách theo dialect |

Không có `datetime('now')` trong truy vấn nghiệp vụ ngoài `DEFAULT`, không có
`json_*()`, `group_concat`, `strftime`. Nghĩa là **một adapter mỏng là đủ** — không cần
ORM, và cũng không được nhân đôi business logic thành `sqlite_version()`/`postgres_version()`.

### 2.3 Chroma — đo, không đoán

| | Giá trị đo được |
|---|---|
| model | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| **chiều vector** | **384** |
| chuẩn hoá | `normalize_embeddings=True` — L2 norm đo được **1.000000** |
| metric | `hnsw:space = cosine` |
| collection | một collection `documents` duy nhất, lọc bằng metadata |
| id vector | chính là `document_chunks.id` của SQLite (dạng chuỗi) |
| số vector | 73 — khớp đúng 73 dòng `document_chunks` |
| `top_k` | 10 |
| ngưỡng ngữ cảnh yếu | `WEAK_CONTEXT_DISTANCE = 0.75` |

**Hệ quả cho parity:** vector đã chuẩn hoá L2 nên cosine distance của Chroma là
`1 − cos_sim`. Toán tử `<=>` của pgvector cũng là `1 − cos_sim`. Về mặt toán học là
**cùng thang đo**, nên ngưỡng 0.75 có cơ sở để giữ nguyên — nhưng §5 vẫn phải **đo** rồi
mới được kết luận, không suy từ lý thuyết.

Chroma còn giữ cả `documents=` (bản sao văn bản). pgvector chỉ cần vector: văn bản gốc
đã nằm trong `document_chunks.text` và **đó mới là nguồn dựng trích dẫn**.

### 2.4 Tệp trên đĩa

| Thư mục | Số tệp | Byte |
|---|---:|---:|
| `data/documents/` | 3 | 141.087 |
| `data/tts_cache/` | 17 | 2.712.432 |
| `data/chroma/` | 6 | 2.928.928 |

### 2.5 Trạng thái bảo mật

`operations` 9 · `operation_calls` 10 · `consent_grants` 0 · `pending_consents` 4 ·
`egress_log` 80.

`consent_grants` rỗng vì `_migrate()` xoá quyền `session` mỗi lần khởi động — đúng như
nhãn "cho tới khi đóng ứng dụng" hứa. Ngữ nghĩa này **không còn đúng trên cloud** và
được thiết kế lại ở §4.

---

## 3. Quyền sở hữu

`workspaces` thêm `owner_user_id` = UUID từ `sub` của Supabase Auth JWT.
**Không dùng email làm khóa sở hữu** — email đổi được, `sub` thì không.

Hiện chỉ một chuyên gia được dùng, nhưng đó là **chính sách xác thực**, không phải mô
hình dữ liệu. Không có `SINGLE_USER = True` hay `USER_ID = 1` ở bất kỳ đâu.

Backend nối Postgres bằng vai trò có quyền cao (bỏ qua RLS). Vì vậy:

> **Ranh giới phân quyền chính là kiểm tra sở hữu trong backend, KHÔNG phải RLS.**
> Không được nói "RLS bảo vệ dữ liệu" cho đường đi mà vai trò backend bỏ qua RLS.

RLS vẫn bắt buộc cho tài nguyên trình duyệt chạm thẳng vào Supabase — trước hết là Storage.

---

## 4. Ngữ nghĩa phiên trên cloud

Bản local nói: *quyền `session` chết khi đóng ứng dụng* — đúng, vì `init_db()` xoá chúng
lúc tiến trình khởi động.

Backend cloud **không có** khái niệm đó. Giữ nguyên câu chữ cũ là nói dối: backend
restart (deploy, scale, crash) không được phép đổi ngữ nghĩa quyền.

Thiết kế mới: trình duyệt sinh `client_session_id` ngẫu nhiên mạnh, giữ trong
`sessionStorage`, gửi kèm header `X-Client-Session-Id`. Quyền phiên gắn với
`(user_id, client_session_id, destination, provider, expires_at)`, TTL tối đa **8 giờ**.

Câu chữ trên giao diện đổi thành:

> **"Cho phép trong phiên trình duyệt này, tối đa 8 giờ"**

Không được nói "cho tới khi đóng ứng dụng" hay "cho tới khi máy chủ tắt".

---

## 5. Ranh giới tin cậy MỚI: tải tệp lên

Bản local: tệp nằm trên máy chuyên gia. Bản web: tệp **rời khỏi thiết bị** ngay khi tải
lên, trước cả khi Gemini/tìm kiếm/TTS xuất hiện.

Phải tách hai lớp, không được gộp:

- **Lớp A — kho riêng của ứng dụng.** Trước khi tải lên, giao diện nói rõ tệp sẽ lên
  Supabase private storage. Sau khi tải lên, **không được** nói "dữ liệu chưa rời máy".
- **Lớp B — bên thứ ba.** Trust Gateway vẫn kiểm soát Gemini / DDGS / edge-tts / gTTS.

Nhật ký `egress_log` giữ nguyên nghĩa cũ: **cố gửi sang bên thứ ba**. Không biến nó
thành nhật ký tải tệp.

---

## 6. Parity Chroma → pgvector: ĐO, không suy

Ngưỡng `WEAK_CONTEXT_DISTANCE = 0.75` được giữ nguyên, và dưới đây là lý do có bằng chứng
chứ không phải lý do có vẻ hợp lý.

### 6.1 Vì sao cùng thang đo

`sentence-transformers` được gọi với `normalize_embeddings=True`. Đo lại: L2 norm =
**1.000000**. Với vector đơn vị:

- Chroma (`hnsw:space = cosine`) trả `1 − cos_sim`
- pgvector (toán tử `<=>`) cũng trả `1 − cos_sim`

Nhưng cùng công thức vẫn lệch được — float32 của pgvector so với float64 của Python, thứ
tự khi hai khoảng cách bằng nhau, hoặc một chỉ mục xấp xỉ đổi tập ứng viên. Nên phải đo.

### 6.2 Kết quả đo trên PostgreSQL thật

| Truy vấn | Xếp hạng so với cosine tính tay | Khoảng cách gần nhất |
|---|---|---:|
| "Tổng giá trị tài trợ của dự án là bao nhiêu đồng?" | **khớp** | 0.2258 |
| "Bao nhiêu hộ dân được hỗ trợ?" | **khớp** | 0.5681 |
| "Công thức nấu phở bò Hà Nội?" (lạc đề) | **khớp** | 0.7973 |

- chiều vector: **384** (đo, không lấy từ tài liệu)
- lệch khoảng cách lớn nhất: **4.446e-08** — đúng mức sai số float32
- ngưỡng 0.75 **tách đúng**: hai câu đúng chủ đề nằm dưới, câu lạc đề nằm trên

**Kết luận: không đổi ngưỡng.** Không phải vì công thức giống nhau, mà vì đo trên thang
của pgvector nó vẫn phân loại đúng.

### 6.3 Chỉ mục: cố ý CHƯA thêm

Chưa tạo HNSW/IVFFlat. Chỉ mục xấp xỉ đổi tập ứng viên, tức đổi kết quả truy hồi — thêm
nó mà không đo lại parity là phá đúng thứ mục này vừa chứng minh. Với khối lượng hiện tại
(73 vector, một chuyên gia) quét tuần tự vừa đủ nhanh vừa **chính xác**.

Chỉ mục duy nhất đang có là B-tree trên `workspace_id`, để lọc hồ sơ trước khi xếp hạng.
Nó không đổi kết quả.

### 6.4 Vector nằm ngay trên `document_chunks`

Chroma là kho tách rời, nên xoá tài liệu phải nhớ xoá ở hai nơi. Đặt cột `embedding` ngay
trên `document_chunks` thì `ON DELETE CASCADE` lo phần đó: không có cửa sổ nào vector còn
sống sau khi văn bản đã chết. `test_c13e` kiểm bằng cách xoá **tài liệu** rồi khẳng định
vector biến mất — không gọi hàm xoá vector nào cả.
