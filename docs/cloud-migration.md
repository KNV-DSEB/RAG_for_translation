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

---

## 7. Phase 6 — công cụ chuyển dữ liệu

Ba bước tách bạch: **plan → migrate → verify**.

```
python scripts/migrate_local_to_cloud.py plan
python scripts/migrate_local_to_cloud.py migrate --owner-user-id <UUID> [--dry-run]
python scripts/migrate_local_to_cloud.py verify  --owner-user-id <UUID>
python scripts/migrate_local_to_cloud.py history
```

### 7.1 Dữ liệu BỀN và trạng thái CHẠY

21 bảng, phân loại hết, không sót không thừa (`backend/migration/spec.py`).

**17 bảng dữ liệu bền — chuyển.** `workspaces` · `engagements` · `documents` ·
`document_chunks` · `glossary` · `glossary_conflicts` · `research_runs` · `profiles` ·
`profile_fields` · `profile_sources` · `mock_sessions` · `mock_turns` · `turn_attempts` ·
`scores` · `expert_verdicts` · `qa_history` · `egress_log`.

**4 bảng trạng thái chạy — CỐ Ý không chuyển.** Đây không phải mất dữ liệu:

| Bảng | Dòng ở nguồn | Vì sao không mang sang |
|---|---:|---|
| `operations` | 9 | `operation_id` chỉ có nghĩa trong tiến trình đã sinh ra nó |
| `operation_calls` | 10 | bộ đếm ngân sách của các thao tác trên |
| `consent_grants` | 0 | **đồng ý cho ứng dụng chạy trên MÁY MÌNH không phải đồng ý cho một máy chủ ở nơi khác** |
| `pending_consents` | 4 | challenge tuổi thọ 10 phút |

`verify` khẳng định bốn bảng này **không có dòng nào trùng id với nguồn** ở đích.

### 7.2 Vector: dựng lại từ văn bản chuẩn

`document_chunks.text` đầy đủ (73 chunk, 0 rỗng, 73.402 ký tự) nên vector được **tạo
lại** bằng đúng model hiện tại, không xuất biểu diễn nội bộ của Chroma.

Lý do: tái lập được, kiểm chứng được, không phụ thuộc định dạng lưu trữ cũ. Xuất vector
thô từ Chroma thì phải *tin* rằng chúng do đúng model đó tạo ra — mà không có gì chứng
minh điều đó.

### 7.3 Tính chất giữ được, và cách giữ

| | Cách bảo đảm |
|---|---|
| **không phá nguồn** | SQLite mở bằng `mode=ro` — hệ điều hành chặn, không dựa vào việc mã không viết lệnh ghi |
| **chạy lại được** | UPSERT theo khoá chính, GIỮ id gốc. Không dùng "có rồi thì bỏ qua" — kiểu đó bỏ sót thay đổi ở nguồn |
| **hỏng thì dừng** | mỗi bảng một giao dịch; sổ cái ghi `failed` kèm tên lớp lỗi; chạy lại tiếp tục được |
| **không diễn giải lại** | 121 cột nghiệp vụ được so từng dòng; nhãn tin cậy và trạng thái nhật ký chuyển nguyên trạng |

### 7.4 Sổ cái `migration_runs`

Trả lời một câu: *trạng thái cloud này dựng từ ảnh chụp local nào?* Ghi vân tay nguồn,
commit git, chủ sở hữu, thời điểm, và **phân biệt `failed` với `completed`**.

### 7.5 Tài liệu — CHƯA tải lên

Phase 6 chỉ **kiểm kê**: đường dẫn, kích thước, SHA256, ánh xạ hồ sơ. Mọi mục mang trạng
thái `pending_upload`, và báo cáo ghi thẳng `đã tải lên cloud: 0`.

Kho lưu trữ riêng là việc của Phase 7. Ghi bất kỳ trạng thái nào khác ở đây là tuyên bố
một việc chưa xảy ra.

**Đã ghi nhận:** `documents.stored_path` là đường dẫn tuyệt đối trên máy này. Phase 7
phải dựng đường dẫn chuẩn theo (người dùng, hồ sơ), không mang đường dẫn cũ sang.

### 7.6 `plan` không ghi gì

`plan` và `migrate --dry-run` không ghi vào PostgreSQL, không sửa SQLite, không sửa
Chroma, không tải tệp, không tạo quyền đồng ý, không ghi cả vào sổ cái. `MIG1` đối chiếu
số dòng ở đích trước và sau khi chạy thử.

Chạy được cả khi chưa có UUID thật — để xem trước sẽ chuyển những gì.

### 7.7 Chủ sở hữu phải là UUID THẬT

`migrate` từ chối chạy nếu thiếu `--owner-user-id`, nếu chuỗi không đúng dạng UUID, hoặc
nếu nó là UUID điền tạm (`00000000-…`). Gắn nhầm chủ thì mọi hồ sơ thuộc về một tài
khoản không tồn tại — và **không ai mở được chúng nữa**, vì hồ sơ chưa có chủ đúng thì
không ai đọc được (xem `backend/auth/ownership.py`).

---

## 8. Parity sau khi chuyển: ĐO trên bộ tài liệu THẬT

§6 đo trên một fixture 5 đoạn dựng sẵn. Phần này đo trên **bộ LDSC thật, 73 đoạn**, và
kết quả buộc phải đính chính một khẳng định trước đó của chính tài liệu này.

### 8.1 Parity: khớp tuyệt đối

Cùng ba truy vấn, chạy qua Chroma (kho hiện tại) rồi qua pgvector (sau khi chuyển):

| Truy vấn | Chroma | pgvector | Xếp hạng |
|---|---:|---:|---|
| "Tổng giá trị tài trợ của dự án là bao nhiêu?" | 0.4857 | 0.4857 | **khớp** |
| "Bao nhiêu hộ dân được hỗ trợ?" | 0.4139 | 0.4139 | **khớp** |
| "Công thức nấu phở bò Hà Nội?" (lạc đề) | 0.6613 | 0.6613 | **khớp** |

Lệch khoảng cách lớn nhất: **1.0e-06** — chỉ là làm tròn ở chữ số thứ sáu.

**Kết luận parity: ĐẠT.** pgvector tái hiện Chroma trên dữ liệu thật.

### 8.2 Đính chính: ngưỡng 0.75 KHÔNG tách được câu lạc đề trên bộ thật

§6 của tài liệu này (và commit `89f46b7`) viết: *"ngưỡng 0.75 tách đúng: hai câu đúng
chủ đề nằm dưới, câu lạc đề nằm trên"*. Câu đó **chỉ đúng trên fixture 5 đoạn**.

Trên bộ LDSC thật, câu hỏi về phở bò cho khoảng cách **0.6613** — *dưới* ngưỡng 0.75,
nên nó **không** được đánh dấu là ngữ cảnh yếu.

Ba điều phải nói rõ, không gộp làm một:

1. **Không phải hồi quy do migration.** Chroma cho đúng 0.6613 trên cùng dữ liệu. Bản
   chạy local vốn đã như vậy từ trước.
2. **`WEAK_CONTEXT_DISTANCE` chỉ bật cảnh báo, không chặn.** Xem `backend/rag/qa.py:189`
   — nó thêm câu "dựa trên ngữ cảnh hạn chế", không từ chối trả lời. Việc từ chối bịa
   dựa vào lời nhắc gửi cho LLM (tiêu chí nghiệm thu T5), không dựa vào ngưỡng này.
3. **Ngưỡng KHÔNG được đổi trong đợt này.** Không có bằng chứng cho một giá trị tốt hơn,
   và đổi nó để một test nào đó xanh là đúng thứ dự án này cấm. Đây là việc còn để ngỏ,
   ghi lại ở đây để không ai tưởng nó đã được giải quyết.

`test_c13f` đã được đổi tên và thu hẹp khẳng định cho khớp bằng chứng.

---

## 9. Giới hạn còn lại của Phase 6

Ghi rõ để không ai đọc nhầm mức bảo đảm:

- **Chưa có credential Supabase.** Toàn bộ kiểm chứng chạy trên PostgreSQL 16.2 +
  pgvector 0.6.2 nhúng bằng `pgserver`. Đó là **cùng engine**, nhưng KHÔNG phải một lần
  chạy thật trên Supabase. Trạng thái đúng: *tương thích PostgreSQL/pgvector đã kiểm
  chứng; tích hợp Supabase thật còn chờ credential.*
- **Tệp tài liệu chưa được tải lên.** Đã kiểm kê kèm SHA256, trạng thái `pending_upload`,
  số đã tải lên là **0**.
- **Chưa deploy Railway hoặc Vercel.**
- **Docker không chạy được trên máy dev** (`com.docker.service` dừng, thiếu quyền admin).
  Không phải blocker: `pgserver` cho PostgreSQL thật mà không cần Docker.

---

## 10. Phase 7 — kho tài liệu riêng

### 10.1 Một đính chính phải nói trước

CLAUDE.md từng viết hệ thống có **"đúng ba đường dữ liệu ra khỏi máy"**. Câu đó đã sai
**từ commit `044fc1f`** — khi thêm PostgreSQL, `psycopg` mở một kết nối mạng thứ tư mà
invariant C1a không hề thấy, vì `psycopg` không nằm trong danh sách thư viện nó canh.
Tôi viết commit đó và không nhận ra.

Cách sửa không phải là thêm `psycopg` vào danh sách cấm, mà là **phân đúng hai hạng mục**:

| | Gồm | Nhật ký | Hồ sơ mật |
|---|---|---|---|
| **Bên thứ ba** — dữ liệu rời khỏi tổ chức | Gemini · DuckDuckGo · edge-tts · gTTS | `egress_log` | phải xin phép trước |
| **Hạ tầng của chính ứng dụng** — dữ liệu được CẤT | PostgreSQL · Supabase Storage | `storage_events` | lớp đồng ý tải lên (Phase 8) |

Gộp hai thứ này hỏng theo cả hai chiều: hoặc mỗi lần lưu tệp lại hỏi xin phép gửi ra
ngoài — vô nghĩa, và làm chuyên gia quen tay bấm đồng ý; hoặc nhật ký gửi-ra-ngoài đầy
dòng lưu trữ nội bộ khiến lần gửi thật cho Gemini chìm trong đó.

`test_c16` §ST9 khoá điều này lại: lưu một tệp phải sinh **0** dòng trong `egress_log`.

### 10.2 Hai cửa, mỗi cửa có tên

C1b trước đây nói "chỉ `security/gateway.py` được import `providers/`". Nay là danh sách
`DOOR_MODULES` gồm hai mục, mỗi mục kèm lý do trong chính tệp test. Thêm mục vào đó là
thay đổi có chủ đích, nhìn thấy được trong diff — không phải nới lỏng im lặng.

C1e mới: kho lưu trữ **không được** nằm trong `gateway._REGISTRY`.

### 10.3 Luồng ba bước

```
1. create_intent   máy chủ kiểm quyền, kiểm cỡ/kiểu, TỰ DỰNG khoá,
                   tạo dòng `documents` ở trạng thái awaiting_upload, phát giấy phép
2. (trình duyệt)   tải tệp THẲNG tới URL trong giấy phép — không đi vòng qua backend
3. finalize        máy chủ kiểm đối tượng CÓ THẬT, đọc lại nội dung, TỰ tính SHA256
```

Bước 3 không tin bất cứ điều gì trình duyệt nói. Trình duyệt có thể báo "xong" mà chưa
tải gì, hoặc tải một tệp khác hẳn — `ST6` dựng đúng ca đó và khẳng định máy chủ ghi theo
nội dung thật.

Trạng thái `awaiting_upload` là có chủ đích: trình duyệt bỏ ngang thì dòng đó **vẫn nằm
lại và nhìn thấy được**, thay vì im lặng biến mất.

### 10.4 Khoá đối tượng do MÁY CHỦ dựng

```
users/{user_id}/workspaces/{workspace_id}/documents/{document_id}/{tên-đã-làm-sạch}
```

Client chỉ nói tên tệp gốc. Nó **không khai được nơi ghi** — khai được thì ghi đè được
tệp của người khác. Ba mảnh danh tính nằm ngay trong đường dẫn nên chính sách của kho
(RLS trên Supabase Storage) chặn được theo tiền tố mà không cần tra cơ sở dữ liệu. **Đây
là chỗ RLS thật sự có tác dụng** — khác với truy vấn từ backend, nơi vai trò quyền cao
bỏ qua RLS.

`document_id` nằm trong đường dẫn nên hai tệp trùng tên trong cùng hồ sơ không đè nhau.
Tên người dùng đặt không được dùng làm định danh: nó không duy nhất, và người dùng đổi được.

Làm sạch tên giữ dấu tiếng Việt dưới dạng ASCII: `Kế hoạch tổng thể(en).docx` →
`Ke-hoach-tong-the-en.docx`, không thành `.docx`.

### 10.5 Xoá phải nói thật

Kho và cơ sở dữ liệu **không chung một giao dịch**. Xoá dòng rồi coi như tệp cũng mất là
tự lừa mình — và tệ hơn, là nói với chuyên gia rằng tài liệu khách hàng đã bị xoá trong
khi nó vẫn nằm trên kho.

`delete_document_object` trả về thứ **thật sự** xảy ra, và ghi `delete_failed` vào cả
`documents.storage_state` lẫn `storage_events`. `ST10` ép kho từ chối xoá rồi khẳng định
hệ thống không báo là đã xoá.

### 10.6 Giới hạn — đọc kỹ trước khi tin

- **`SupabaseStorage` CHƯA TỪNG CHẠY.** Toàn bộ
  `security/providers/supabase_storage.py` viết theo tài liệu HTTP API của Supabase.
  Máy phát triển không có credential, nên **không một dòng nào từng gọi tới máy chủ thật**.
- **Test chạy trên `LocalStorage`** — kho thật của bản chạy trên máy, không phải bản giả
  lập Supabase. Nó chứng minh **luồng** đúng: giấy phép dùng một lần, có trần, khoá do máy
  chủ đặt, chốt tự băm, xoá nói thật. Nó **không** chứng minh Supabase hành xử như tài
  liệu mô tả.
- Trạng thái đúng: *luồng tải lên đã kiểm chứng trên kho local; tích hợp Supabase Storage
  còn chờ credential.*

---

## 11. Phase 8 — đồng ý tải lên: hai lớp, không gộp

### 11.1 Ranh giới tin cậy mới

Trên máy cá nhân, "tải tệp lên" là chép từ thư mục này sang thư mục khác **trên cùng cái
máy đó**. Trên web, nó là tệp **rời khỏi thiết bị** của chuyên gia sang một máy chủ ở nơi
khác. Hai việc hoàn toàn khác nhau mang cùng một cái tên.

| | Câu hỏi | Ai trả lời |
|---|---|---|
| **Lớp A** | "Tệp có rời khỏi thiết bị của tôi sang kho của ứng dụng không?" | `storage/service.upload_notice` |
| **Lớp B** | "Dữ liệu có sang Gemini / DuckDuckGo / Microsoft / Google không?" | `security/gateway` |

Gộp lại thì mỗi lần chọn tệp lại hiện hộp thoại "gửi dữ liệu ra ngoài" — và chuyên gia sẽ
**quen tay bấm đồng ý**, đúng lúc hộp thoại thật sự quan trọng xuất hiện. `UP2` khoá lại:
xem thông báo tải lên phải chạm **0** dòng của `egress_log`, `pending_consents`,
`operations`, `consent_grants`.

### 11.2 Ba khẳng định sai đã gỡ

Màn Bảo mật có một panel viết cứng. Nó mắc **ba lỗi cùng lúc**:

| Câu | Sai vì |
|---|---|
| "nhận dạng giọng nói … chạy trên máy này" | STT **đã bị gỡ khỏi dự án từ lâu** — sai ngay cả trên bản local |
| "cơ sở dữ liệu … chạy trên máy này" | trên cloud nó ở Supabase |
| "Toàn hệ thống có đúng ba đường dữ liệu ra ngoài" | trên cloud còn kết nối PostgreSQL và kho lưu trữ |

Thay bằng `backend/security/datamap.py` — **sinh từ cấu hình quyết định nơi dữ liệu nằm**.
Một câu viết tay không tự đúng lên được khi kiến trúc đổi.

Ba mức `boundary`, và chúng khác nhau:

```
device       trên chính máy đang chạy tiến trình
app_cloud    hạ tầng của ứng dụng — ĐÃ rời thiết bị, CHƯA sang bên thứ ba
third_party  gửi sang tổ chức khác
```

Gộp `app_cloud` vào `device` là nói dối chuyên gia. Gộp nó vào `third_party` là làm nhật
ký gửi-ra-ngoài mất tác dụng. **Ba mức, không phải hai.**

### 11.3 Câu chữ lớp B nói rõ dữ liệu đi TỪ ĐÂU

```
local  "Thao tác này sẽ gửi dữ liệu ra ngoài: …"
cloud  "Thao tác này sẽ gửi dữ liệu từ kho riêng của ứng dụng sang dịch vụ bên thứ ba: …"
```

Trên cloud, giữ nguyên "rời khỏi máy này" là nói dối **theo chiều nguy hiểm nhất**:
chuyên gia tin rằng tài liệu khách hàng vẫn trong tầm tay mình, trong khi nó đã ở một máy
chủ khác từ lúc tải lên.

### 11.4 `UP6` — quét chuỗi viết cứng trong nguồn

Quét **nguồn JS**, không quét kết quả render: một chuỗi viết cứng vẫn nằm im trong mã cho
tới đúng lúc nó được hiện ra, và lúc đó thì đã muộn. Ba cụm bị cấm trong chuỗi hiển thị:
`rời khỏi máy này` · `đều chạy trên máy này` · `có đúng ba đường dữ liệu ra ngoài`.

Chú thích được miễn — chú thích giải thích *lịch sử* của mấy câu này thì phải nhắc lại chúng.

`UP6` bắt được một tàn dư thật khi mới viết: `ui.js` vẫn giữ câu của bản local làm giá trị
dự phòng `??`. Đặt câu local làm mặc định nghĩa là khi máy chủ không cấp nhãn, giao diện
sẽ nói dối trên cloud. Cùng lỗi đó có ở `schemas.py`; đã sửa cả hai thành câu trung tính.

### 11.5 Một lỗ hổng trong chính bộ test, do phép thử phá hoại tìm ra

Bản đầu của `UP4` chỉ kiểm dòng *Tệp tài liệu*. Ép dòng *Cơ sở dữ liệu* luôn báo `device`
thì test **vẫn xanh** — dòng tệp tài liệu che mất. Mà đúng dòng "Cơ sở dữ liệu" mới là
khẳng định từng sai trên cloud.

Nay `UP4` kiểm cả `Cơ sở dữ liệu` lẫn `Chỉ mục ngữ nghĩa`, theo `driver.is_postgres()`.
