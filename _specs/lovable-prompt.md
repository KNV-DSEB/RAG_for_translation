# Prompt cho Lovable — Trợ lý phiên dịch Việt ⇄ Anh

Viết bằng tiếng Anh vì Lovable bám chỉ dẫn tiếng Anh tốt hơn hẳn. **Toàn bộ chữ hiện lên
màn hình phải là tiếng Việt** — các chuỗi tiếng Việt đã cho sẵn nguyên văn trong prompt.

Dán **Prompt 1** trước, đợi Lovable dựng xong và xem trang `/gallery` rồi mới dán tiếp.
Dán cả 6 cái một lúc thì nó làm hời hợt hết.

---

## Prompt 1 — Tổng quan dự án + hệ thiết kế + dữ liệu

```
Build a preparation tool for ONE professional Vietnamese⇄English conference interpreter.
Not a team product, not a SaaS. One expert, preparing for a real assignment a few days
before it happens — NGO handover ceremonies, government meetings, negotiations.

The tool's single job: take them from "I know the client's name" to "I have practiced this
session and I know which terms I'm weak on."

## The whole product in one paragraph
The interpreter creates a CLIENT WORKSPACE. They upload the documents they were sent
(agendas, speeches, project reports) and can ask questions against them with citations.
They run a web RESEARCH pass on the client and partner organisations, which produces a
sourced profile and a bilingual GLOSSARY. Then they run a MOCK SESSION: an AI-generated
8-10 turn dialogue between two people, one speaking Vietnamese and one English, using their
own glossary terms. Each turn is read aloud; the interpreter types their translation; the
AI scores it on four criteria; the interpreter then OVERRULES the AI where it is wrong, and
those verdicts become scoring rules for later sessions.

## Nine screens
  Chuẩn bị:   Bảng điều khiển · Tài liệu · Nghiên cứu · Thuật ngữ
  Luyện tập:  Buổi mock · Hiệu chỉnh · Lịch sử
  Hệ thống:   Bảo mật · Dung lượng

## CRITICAL: all UI text in Vietnamese
Every label, button, heading, error, empty state, toast is Vietnamese. Never English UI
text. Never machine-translate — use the exact Vietnamese strings I give you, and write new
ones as natural Vietnamese aimed at a working professional.

## Design direction — read carefully, this is the whole point
A previous version of this app was rejected for looking templated. Do NOT produce the
default shadcn dashboard: no generic card grid, no indigo/violet accent, no lucide icon in
a rounded square above every card title. Also avoid the three clichés of AI-generated
design: (1) cream background + high-contrast serif + terracotta accent, (2) near-black +
one acid-green accent, (3) broadsheet layout with hairline rules and zero border-radius.

### The signature element: "the spine"
This is the one thing the product is remembered by. EVERY bilingual block renders as two
columns with a thin 1px vertical rule down the middle, and the turn number sitting in the
gutter. Source language left, target right, with a small arrow under the number.

      ┌──────────────────────────┬─┬──────────────────────────┐
      │ TIẾNG VIỆT               │ │ TIẾNG ANH                │
      │ Ông Nguyễn Minh Hòa      │ │ Mr. David Walker         │
 03   │ Phó GĐ Sở Ngoại vụ       │ │ Humanitarian Specialist  │
  →   │                          │ │                          │
      │ Báo cáo với ông Walker,  │ │ Reporting to Mr. Walker, │
      │ dự án lần này có tổng    │ │ this project has a total │
      │ giá trị tài trợ là...    │ │ funding value of...      │
      └──────────────────────────┴─┴──────────────────────────┘

That centre line IS the act of interpreting — moving from one side to the other. Reuse the
exact same component for: mock session turns, glossary rows (compact variant), reference
translations, bilingual document previews. It carries real information — which side is
source, which is target, which turn number — so it is not decoration.
Below 720px it stacks vertically and the centre rule disappears.

### Typography — exactly two families
- "Be Vietnam Pro" for everything. This typeface was drawn specifically for Vietnamese
  diacritics; using it states that this tool is Vietnamese-first. Load 400/500/700/900 with
  the vietnamese subset. Weight 900 for page titles, tracking -0.03em. Most designs reach
  for Inter — do not.
- "JetBrains Mono" for ALL numbers: scores, durations, turn numbers, byte counts, dates.
  Always font-variant-numeric: tabular-nums so number columns align.
- No serif display face anywhere.

### Colour tokens (CSS variables, light + dark)
  --ink     #0E1A2B   body text
  --paper   #FAFBFD   page background — cool, deliberately NOT cream
  --vi      #1B4079   navy — the Vietnamese side
  --en      #175E63   deep teal — the English side
  --flag    #A8324A   carmine — needs review / destructive
  --ok      #16704F      --warn #8A5300

The two language colours teach the eye the VI→EN axis. Use them with RESTRAINT: a 3px left
border plus a small label. Never fill a whole block with them.

### Motion — professional dashboard: crisp, fast, minimal
- Custom easing only: --ease-out: cubic-bezier(0.23, 1, 0.32, 1)
- Every button gets transform: scale(0.97) on :active, 140ms. Mandatory.
- Never `transition: all` — always name the properties.
- Only animate transform and opacity. All UI durations under 300ms.
- Gate every hover behind @media (hover: hover) and (pointer: fine).
- Respect prefers-reduced-motion: drop movement, keep opacity and colour.
- Exactly ONE choreographed moment in the entire app: advancing to the next turn in a mock
  session (new turn slides up 10px + fades in, 220ms). Nothing else animates on entry — no
  staggered card reveals, no page transitions.
- Visible :focus-visible ring everywhere. Never outline:none without a replacement.

### Layout
Fixed narrow left rail (236px) with the client-workspace switcher pinned at the top and nav
grouped under the three headings above. Content column max 1100px. The mock session screen
runs FULL BLEED with the rail hidden entirely — it should feel like a cockpit, not a form.

## Stack and data
React + TypeScript + Tailwind + Supabase.

AUTH IS MANDATORY. Supabase email auth, one user. Every table has a user_id column and an
RLS policy scoped to auth.uid(). This is not optional — the data is confidential client
material and the app is on a public URL.

Tables:
- workspaces        id, user_id, name, industry, is_confidential, notes, timestamps
                    -- the central unit; everything else belongs to one workspace
- documents         workspace_id, filename, storage_path, ext, size_bytes,
                    language ('vi'|'en'|'parallel'|'mixed'|'unknown'),
                    language_source ('auto'|'manual'), status, error_message,
                    n_chars, n_chunks
- document_chunks   document_id, workspace_id, chunk_index, text, locator, lang,
                    embedding vector(768)          -- enable the pgvector extension
- glossary          workspace_id, term_vi, term_vi_norm, term_en, pronunciation,
                    definition, category, frequency,
                    confidence ('human_translated'|'machine_guess'),
                    status ('auto'|'expert_edited'|'skipped'), source_type, source_ref
                    UNIQUE (workspace_id, term_vi_norm)
- glossary_conflicts glossary_id, proposed_term_en, proposed_definition, source_ref,
                    confidence, resolved
- profiles          workspace_id, entity_name, entity_role ('client'|'partner')
- profile_fields    profile_id, field_key, value, is_verified, is_expert_edited
                    -- ONE ROW PER FIELD, so every fact carries its own sources
- profile_sources   profile_field_id, url, title, published_at
- mock_sessions     workspace_id, topic, difficulty, n_turns, hide_script, status,
                    overall_score, started_at, completed_at
- mock_turns        session_id, turn_index, speaker_name, speaker_role, source_lang,
                    target_lang, source_text, reference_translation,
                    reference_tier ('human'|'expert_pinned'|'ai'), terms_used jsonb,
                    est_duration_sec
- turn_attempts     turn_id, session_id, transcript, input_mode
- scores            attempt_id, score_meaning, score_terminology, score_completeness,
                    score_expression, score_overall, comment, term_verdicts jsonb
- expert_verdicts   attempt_id, workspace_id, action, the same four scores,
                    score_overall, note, related_category, pinned_translation
- egress_log        workspace_id, module, destination ('llm'|'search'|'tts'), endpoint,
                    n_chars, summary, consented, created_at

All AI calls go through Supabase Edge Functions. The Gemini API key lives in edge function
secrets and must NEVER reach the browser.

## Build ONLY this in this prompt
1. App shell: left rail, workspace switcher, routing, design tokens, both fonts loaded.
2. "Bảng điều khiển" — create/select a client workspace, plus stat tiles labelled
   "Tài liệu", "Thuật ngữ", "Buổi mock", "Nhận định đã ghi".
3. A component gallery at /gallery showing every component in every state: buttons,
   inputs, selects, badges, the spine component, toasts, dialogs, empty states, loading
   states, error states. I will review the design direction there BEFORE you build the
   other screens.

Use this real content in the gallery instead of lorem ipsum so I can judge it honestly:
client "Latter-Day Saint Charities"; partners "UBND xã Thu Cúc" and "Sở Ngoại vụ tỉnh
Phú Thọ"; project "Hỗ trợ kinh phí xây nhà cho 113 hộ dân có hoàn cảnh khó khăn tại xã
Thu Cúc, tỉnh Phú Thọ"; funding 6.780.000.000 ₫.

Also render this string at weight 400 and 900 so I can verify the Vietnamese diacritics:
"Phường Thuỵ Khuê — Đề nghị duyệt".
```

---

## Prompt 2 — Tài liệu và hỏi đáp có trích dẫn

```
Build the "Tài liệu" screen.

Upload: drag-and-drop into Supabase Storage. Accept PDF, DOCX, TXT, MD.
Do NOT accept legacy .doc — you cannot parse it server-side. If the user drops one, say so
plainly: "Định dạng .doc cũ chưa đọc được. Hãy mở bằng Word rồi lưu lại thành .docx."

After upload an edge function extracts text, splits it into chunks that RETAIN a locator
("trang 3" / "đoạn 12"), embeds them with Gemini text-embedding-004 into pgvector, and
detects the language of each chunk.

Language detection matters: if a document has >=30% Vietnamese paragraphs AND >=30% English
paragraphs, label it 'parallel' — a bilingual document holding the same content in both
languages, e.g. a speech that was already translated. Badge it "song ngữ song song". These
are the most valuable documents in the system, because the term pairs inside them were
produced by a real human translator. The user must be able to override the language label
by hand from a dropdown on the row.

Q&A block: the user asks in Vietnamese or English. An edge function retrieves the top ~6
chunks and asks Gemini. The response MUST be structured:
  answer        string
  found         boolean
  confidence    'high' | 'medium' | 'low'
  citations     [{document_id, filename, locator, snippet}]
  key_figures   string[]    -- numbers, amounts, dates; these matter most to an interpreter
  inference     string      -- anything inferred rather than read from the documents

Rendering rules — these ARE the feature:
- Every citation is a clickable chip "tên tệp · trang N". Clicking opens a real dialog with
  the verbatim source passage. Not a tooltip — something they can read and check.
- found === false: show a warning note plus a button "Tìm trên web thay vì trong tài liệu"
  that navigates to the research screen. NEVER invent an answer.
- confidence === 'low': show "Câu trả lời dựa trên ngữ cảnh hạn chế — nên kiểm tra lại
  nguồn trước khi dùng."
- key_figures render as separate small badges under the answer.
- inference renders BELOW a dashed divider with the badge "suy luận — không đọc được trực
  tiếp từ tài liệu". Never mix inferred content into the answer body.
- Zero citations: "Câu trả lời này không có trích dẫn — hãy tự kiểm lại trong tài liệu."

Quick-ask buttons under the input: "Tóm tắt thông tin về khách hàng", "Cho tôi thông tin
về dự án", "Dự đoán nội dung sẽ trao đổi trong buổi nghiệm thu".

Keep a Q&A history list below the input.
```

---

## Prompt 3 — Nghiên cứu khách hàng và bảng thuật ngữ

```
Build "Nghiên cứu" and "Thuật ngữ".

### Nghiên cứu
Form: client name, partner names (comma separated), topic of the working session, industry,
extra notes. On submit an edge function runs a SEQUENTIAL loop — do not reach for an agent
framework:
  1. ask Gemini to plan search queries (max 8, mixing Vietnamese and English, because a
     foreign organisation has English coverage while its Vietnam activity is written up in
     Vietnamese)
  2. run the searches (Brave Search API or Tavily)
  3. ask Gemini to synthesise one profile per entity

Source URLs attach PER FIELD, not per profile. Fields: official_names, industry, size,
products, recent_news, topic_context, cooperation_history, interpreter_notes.

Hard rules for the synthesis prompt:
- Every field carries source_urls copied VERBATIM from the supplied search results. Never
  invent or alter a URL.
- Anything inferred rather than read gets is_inference=true and an EMPTY source list.
- Anything not found goes to not_found_notes. Never guess a headcount, a revenue, a number.
- If the sources describe several DIFFERENT organisations sharing the name, put that in
  ambiguity_warning and list the candidates for the user to choose between. Never silently
  pick one and present it as fact.
- Sources that contradict each other: show both with their sources, do not pick a side.

UI: one card per entity. Each field row shows a green badge "có nguồn" or an amber "chưa
xác minh". Source chips show hostname and date, open in a new tab. A field with no sources
shows "Không có nguồn — đây là suy luận của máy, tự kiểm lại trước khi dùng."
Every field is editable inline; once edited it gets the badge "bạn đã sửa" and a later
research run must NEVER overwrite it.
Add a collapsible panel listing the exact search queries that were sent out.

### Thuật ngữ
Terms come from THREE sources at different trust levels:
  1. parallel bilingual documents -> confidence 'human_translated' (highest: a real human
     produced these pairs). Feed the VI block and the EN block to Gemini and ask for term
     PAIRS. Do not write a sentence-alignment algorithm.
  2. single-language documents -> 'machine_guess'
  3. web search results -> 'machine_guess'

New terms land as status='auto' and are USABLE IMMEDIATELY. There is no approval queue
blocking the workflow — the user edits only what looks wrong.

Conflict resolution when the same term_vi arrives with a different term_en:
precedence is expert_edited > human_translated > machine_guess. If the newcomer does not
win, do NOT overwrite it away — write a glossary_conflicts row and render BOTH options side
by side in a carmine-bordered box with two buttons: "Dùng bản mới" / "Giữ bản đang dùng".
The system never decides for the user.

Each glossary row uses the COMPACT spine component: Vietnamese left, English right, thin
rule between. A "pronunciation" line sits under the English side when present, e.g.
"đọc: Lát-tơ Đây Xây-nt Cha-ri-tis". This column exists because the interpreter has to say
foreign names out loud under pressure, and it is also used to make text-to-speech pronounce
them correctly.

Add a search box, a category filter, and CSV export written with a UTF-8 BOM so Excel on
Windows shows the Vietnamese diacritics correctly.
```

---

## Prompt 4 — Buổi mock, chạy toàn khung

```
Build "Buổi mock". This screen runs FULL BLEED — hide the left rail entirely while a
session is running. It should feel like a cockpit, not a form. This is the most important
screen in the product.

### Generating a script
Config: topic, partner names, difficulty (Cơ bản / Trung bình / Khó), turns (8-10), and a
checkbox "Ẩn kịch bản" that is ON by default.

Before generating, show the context that will be used: how many profiles, how many glossary
terms, how many of those are 'human_translated', how many parallel documents. With no
profile yet, warn "Chưa có hồ sơ khách hàng — kịch bản sẽ chung chung. Chạy Nghiên cứu
trước sẽ sát thực tế hơn nhiều." but still allow it.

The edge function asks Gemini for a dialogue between exactly two characters who ALTERNATE:
character A speaks Vietnamese, character B speaks English. The interpreter therefore works
in BOTH directions within one session.

Each turn is about 5 sentences — a real consecutive-interpreting unit, roughly 30-60
seconds read aloud.

Glossary terms must appear NATURALLY inside spoken sentences, never as a list.
  Wrong: "Chúng tôi quan tâm tới nhà tạm, nhà dột nát, hộ nghèo, hộ cận nghèo."
  Right: "Qua rà soát, xã còn 113 hộ đang ở nhà tạm, nhà dột nát, phần lớn là hộ nghèo
          và cận nghèo."

VALIDATE before showing, and regenerate ONCE on failure: exactly 8-10 turns, both
directions present, every turn has a reference translation, each turn roughly the right
length (estimate spoken duration from word count — Vietnamese ~228 wpm, English ~158 wpm;
these are measured values, not guesses), and enough glossary terms actually used. If the
second attempt still fails, show it anyway with a note saying what is off.

### Running a session
Top bar only: speaker name and role, direction ("tiếng Việt → tiếng Anh"), estimated
duration, a row of small progress pills (green = scored, navy = current), turn count.

Per turn:
1. Button "🔊 Phát lời thoại" — an edge function generates speech for the source text and
   returns audio. A speed selector (Chậm / Bình thường / Nhanh) raises the difficulty.
   Cache the audio; replaying must not regenerate it.
   Before speaking, substitute any glossary pronunciation hints into the text so foreign
   names are read correctly — but ONLY for the Vietnamese voice. The English voice already
   pronounces English names correctly.
2. With "Ẩn kịch bản" on, do NOT show the source text yet — show a note explaining why, and
   a button to reveal it if they truly need to.
3. A textarea where the user TYPES the translation. There is NO recording and no
   speech-to-text in this product. Show a word counter and support Ctrl+Enter to submit.
   Nudge copy: "Cố gắng dịch một lượt, đừng nghe đi nghe lại — buổi thật không cho phép."
4. "Chấm điểm" calls an edge function scoring FOUR criteria, each 0-10:
   score_meaning (Nghĩa), score_terminology (Thuật ngữ), score_completeness (Đầy đủ),
   score_expression (Diễn đạt). Overall = mean, one decimal.

Scoring prompt rules:
- Name each specific term that was right or wrong, with the correct rendering. Never
  generic feedback like "cần cải thiện thêm".
- Missing NUMBERS, names, titles and conditions are the most serious omission an
  interpreter can make — list them explicitly in missing_items.
- A shortened translation that still carries the full meaning and suits the formal register
  must NOT lose completeness points.
- Wording different from the reference is NOT wrong. The reference is one good rendering,
  not the only correct one.
- Write all feedback in Vietnamese.

After scoring, reveal the original AND the reference translation using the SPINE component,
with a badge for the reference trust tier:
  ⭐⭐⭐ "bản dịch của người thật"   (lifted from a parallel bilingual document)
  ⭐⭐  "bạn đã chốt"               (the user pinned their own rendering earlier)
  ⭐   "AI sinh"                    (generated — reference only, not absolute truth)

Score tiles colour by value: under 5 carmine, 5-7.5 amber, above 7.5 green. Numbers in
JetBrains Mono.

### Feedback block — build this, it is not optional
Directly under the score, a block "💬 Nhận định của bạn":
- one button "✓ Đồng ý với điểm AI" — the fast path, one click
- expandable: four sliders pre-set to the AI scores, a free-text reason field, and a field
  to pin your own translation as the reference
Save BOTH the AI score and the expert score. Never overwrite one with the other.
Copy under the block: "AI chấm trước, bạn là người phán quyết. Nhận định CÓ ghi lý do sẽ
thành luật chấm cho các buổi sau với hồ sơ này."

Advancing to the next turn is the ONE choreographed animation in the app: slide up 10px
plus fade, 220ms, the custom ease-out.

End of session: a report with the overall score, a bar chart per criterion, terms that were
wrong aggregated with counts, and a per-turn breakdown.
```

---

## Prompt 5 — Hiệu chỉnh, Lịch sử, Bảo mật, Dung lượng

```
Build the four remaining screens.

### Hiệu chỉnh
This is where the feedback loop becomes visible and checkable.
- A DIVERGING bar chart: expert score minus AI score, per criterion. Positive bars green,
  negative carmine, with a zero line. Caption: "Cột dương = AI chấm khắt khe hơn bạn. Cột
  âm = AI dễ dãi hơn bạn. Tiêu chí lệch nhiều nhất là chỗ bạn nên tự kiểm lại điểm AI thay
  vì tin ngay."
- A table: criterion, mean gap, mean absolute gap, times adjusted.
- Whether the gap is narrowing over time.
- The criterion with the largest TOTAL correction — times adjusted MULTIPLIED BY magnitude,
  not just the count — with a note that this is the one they actually care most about.
  (Ranking by count alone names the wrong criterion; that bug is why this is spelled out.)
- A panel showing the VERBATIM text of the calibration rules currently being injected into
  the scoring prompt. Transparency, not trust-me. Note under it: "Đây là hiệu chỉnh bằng
  ngữ cảnh, KHÔNG phải huấn luyện lại mô hình."
- A list of every verdict recorded, and a "Đặt lại hiệu chỉnh" button behind a two-step
  confirmation.

How calibration works: when scoring a turn, select the most relevant past verdicts (same
workspace -> same term category -> most recent, capped around 12) and inject them into the
scoring prompt as rules. ONLY verdicts with a written reason qualify — a bare slider
adjustment is stored but teaches nothing.
Separately, terms the user has edited are applied HARD: compare the translation against the
user's pinned rendering directly instead of letting the model decide again.

### Lịch sử
Sessions list with status badges, the ability to reopen an unfinished session, a progress
line chart (bold overall line plus four thin dotted criterion lines), and the Q&A history.

### Bảo mật
Log every outbound call to an external service. There are exactly THREE destinations:
LLM, web search, text-to-speech. Table columns: time, destination as a colour-coded chip,
module, character count, allowed/blocked, summary. Above the table, state plainly what
leaves the system and what does not.
Warn if any single call exceeded ~40,000 characters — that suggests whole documents are
being sent instead of retrieved passages.

Also a "hồ sơ mật" toggle per workspace. When it is on, EVERY outbound call must first show
a dialog containing the VERBATIM payload about to be sent, and wait for approval.
Implement this in ONE place in the API client: catch a 409 'consent_required' response,
show the dialog, grant consent, then AUTOMATICALLY RETRY the original request so the user
does not have to click their action again. Do not scatter this logic across screens — that
is how a path gets missed.

### Dung lượng
Storage used by generated audio, with a delete button behind a two-step confirmation.

Every destructive action in the app uses a two-step confirmation that says exactly what
will be lost AND what will be preserved.
```

---

## Prompt 6 — Rà soát cuối

```
Review the whole app and fix these. Do not summarise the issues — fix them.

Accessibility: every icon-only button has an aria-label; every input has a real label;
a visible :focus-visible ring everywhere; a skip link to main content; toasts are
aria-live="polite"; headings are hierarchical.

Motion: no `transition: all` anywhere; only transform and opacity animate; every UI
duration under 300ms; every hover gated behind @media (hover: hover) and (pointer: fine);
prefers-reduced-motion respected; scale(0.97) on :active for every button.

Typography: use … not three dots; curly quotes; tabular-nums on every number column;
text-wrap: balance on headings; loading states end with "…".

Layout: no horizontal page scroll at 900px wide; wide tables scroll inside their own
container; flex children holding text have min-w-0; modals use overscroll-behavior: contain.

Dark mode: <select> and <option> need explicit background-color and color, or Windows dark
mode renders black text on black. Set a theme-color meta for both schemes.

Copy: errors state what happened AND what to do next, never just the problem. Second
person, active voice, no apologies. Empty states are an invitation to act, not an error.

Finally, read every visible string and check it is natural Vietnamese written for a working
professional interpreter — not machine-translated English.
```

---

## Chỗ bản Lovable khác bản đang chạy — phải biết trước khi bắt đầu

| Bản đang chạy trên máy | Bản Lovable | Hệ quả |
|---|---|---|
| Dữ liệu ở lại máy chuyên gia | Supabase trên cloud | **§7 của spec không còn đúng.** Tài liệu khách hàng nằm trên máy chủ bên thứ ba |
| Đọc được `.doc` cũ qua Word COM | Không đọc được | Phải mở bằng Word lưu lại `.docx`. **2 trong 3 tài liệu LDSC là `.doc`** |
| Embedding chạy local (`sentence-transformers`) | Gemini embedding API | Nội dung tài liệu đi qua Google, không chỉ đoạn truy hồi |
| Không cần đăng nhập (một người, một máy) | **Bắt buộc auth + RLS** | Không có thì ai biết link đều đọc được toàn bộ |
| Key trong `.env` trên máy | Supabase edge secrets | Key không bao giờ được xuống trình duyệt |
| Ba đường egress đi qua đúng một cửa | Phải dựng lại trong edge function | Không tự có — nằm trong Prompt 5, đừng bỏ |

Nếu bảo mật là ràng buộc thật thì bản Lovable chỉ nên dùng cho **tài liệu không nhạy cảm**,
và giữ bản chạy local cho hồ sơ thật.

## Khi Lovable đi chệch

Dán lại đoạn này, nó bám sát hơn là mô tả chung chung:

```
Stop. Re-read the design direction. Three things are wrong right now:
1. This looks like a default shadcn dashboard. The spine component with the centre rule is
   the signature — every bilingual block must use it.
2. Numbers must be JetBrains Mono with tabular-nums. Body text must be Be Vietnam Pro.
3. All UI text is Vietnamese. Fix any English string you find.
```
