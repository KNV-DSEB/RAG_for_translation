/**
 * Màn hình: Buổi mock — chạy TOÀN KHUNG, dạng buồng lái.
 *
 * Vào:  hồ sơ khách hàng; hoặc ?session=<id> để mở lại buổi đang dở.
 * Ra:   cấu hình → sinh kịch bản → luyện từng lượt (nghe, nói, chấm, phản biện) → báo cáo.
 *
 * Vì sao bỏ hết chrome: đây là lúc chuyên gia phải tập trung nghe và nói dưới áp lực thời
 * gian. Rail điều hướng, tiêu đề trang, mọi thứ khác đều là phân tán. Đây cũng là điểm tệ
 * số 4 mà chuyên gia nêu — "chưa ra dáng công cụ luyện tập".
 *
 * Không được làm rơi so với bản Streamlit:
 *   A3.12  mặc định ẩn kịch bản; bản gốc dạng chữ chỉ hiện SAU khi đã chấm
 *   A3.14  chấm theo bản transcript ĐÃ SỬA, không chấm bản thô của máy
 *   A4.4   transcript luôn sửa được trước khi chấm
 *   A4.9   audio im lặng thì báo rõ, KHÔNG chấm 0 điểm cho bản trống
 *   §6     sau mỗi lượt chấm là khối phản biện, không phải ngoại lệ
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import { barChart } from "../charts.js";
import {
  el, stats, note, loading, empty, spine, toast, ok, fail, withBusy, field, fmtNum,
} from "../ui.js";

const LANG = { vi: "tiếng Việt", en: "tiếng Anh" };

const TIER = {
  // Bằng chứng có được: câu này xuất hiện NGUYÊN VĂN trong tài liệu song ngữ.
  // Nó KHÔNG chứng minh đây là bản dịch của đúng lượt nguồn này — nên nhãn không được
  // nói "bản dịch của người thật". Xem `generator.py > _is_verbatim_in`.
  verbatim_parallel: ["badge-ok", "⭐⭐⭐ nguyên văn trong tài liệu song ngữ"],
  expert_pinned: ["badge-ok", "⭐⭐ bạn đã chốt"],
  ai: ["badge-mute", "⭐ AI sinh"],
};

const CRITERIA = [
  ["meaning", "Nghĩa"],
  ["terminology", "Thuật ngữ"],
  ["completeness", "Đầy đủ"],
  ["expression", "Diễn đạt"],
];

const level = (v) => (v < 5 ? "low" : v < 7.5 ? "mid" : "high");

/* ============================== Cấu hình + sinh kịch bản ============================== */

async function configView(root, workspace) {
  const context = await api.simulationContext(workspace.id);

  root.append(
    el(
      "div.mock-body",
      null,
      el("div.page-head", null,
        el("div.eyebrow", { text: "LUYỆN TẬP" }),
        el("h1", { text: "Buổi mock" }),
        el("p", { text: "Kịch bản 8–10 lượt sát bối cảnh thật, dịch cả hai chiều, chấm 4 tiêu chí thang 10." })
      ),

      el("div.card", null,
        el("div.card-title", { text: "Bối cảnh sẽ dùng để sinh kịch bản" }),
        el("div.card-sub", null,
          (context.entities ?? []).map((e) =>
            el("div", null,
              el("b", { text: e.entity_name }),
              ` — ${e.entity_role === "client" ? "khách hàng" : "đối tác"}`)
          )
        ),
        el("div", { style: "margin-top:14px" },
          stats([
            ["Hồ sơ đã dựng", fmtNum(context.n_profiles)],
            ["Thuật ngữ", fmtNum(context.n_terms)],
            ["⭐⭐⭐ ghép từ tài liệu song ngữ", fmtNum(context.n_human_terms)],
            ["Tài liệu song ngữ", fmtNum(context.n_parallel)],
          ])
        )
      ),
      ...(context.warnings ?? []).map((w) => el("div", { style: "margin-top:12px" }, note("warn", w))),
      configForm(workspace, context)
    )
  );
}

function configForm(workspace, context) {
  const topic = el("textarea.textarea", {
    rows: 2,
    placeholder: "ví dụ: Lễ tổng kết và bàn giao công trình nhà ở cho 113 hộ khó khăn tại xã Thu Cúc",
  });
  const partners = el("input.input", {
    value: (context.entities ?? [])
      .filter((e) => e.entity_role === "partner")
      .map((e) => e.entity_name)
      .join(", "),
  });
  const difficulty = el("select.select", null,
    [["basic", "Cơ bản"], ["medium", "Trung bình"], ["hard", "Khó"]].map(([v, t]) =>
      el("option", { value: v, text: t, selected: v === "medium" })
    )
  );
  const turns = el("select.select", null,
    [8, 9, 10].map((n) => el("option", { value: String(n), text: `${n} lượt`, selected: n === 8 }))
  );
  const hide = el("input", { type: "checkbox", checked: true });
  const submit = el("button.btn.btn-primary.btn-lg", { type: "submit", text: "Sinh kịch bản" });

  return el(
    "form.card",
    {
      style: "margin-top:16px",
      onsubmit: async (event) => {
        event.preventDefault();
        if (!topic.value.trim()) {
          toast("warn", "Cần nhập chủ đề buổi làm việc.");
          return;
        }
        await withBusy(submit, "Đang sinh…", async () => {
          const data = await api.createScript({
            workspace_id: workspace.id,
            topic: topic.value.trim(),
            client_name: workspace.name,
            partner_names: partners.value.split(",").map((s) => s.trim()).filter(Boolean),
            difficulty: difficulty.value,
            n_turns: Number(turns.value),
            hide_script: hide.checked,
          });
          ok("Đã sinh kịch bản.");
          await store.touchWorkspace(workspace.id);
          router.go("mock", { session: data.session.id });
        });
      },
    },
    el("div.card-title", { text: "Cấu hình buổi" }),
    field("Chủ đề buổi làm việc", topic, "Càng cụ thể thì kịch bản càng sát buổi thật.", true),
    field("Tên đối tác", partners, "Cách nhau bằng dấu phẩy."),
    el("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:12px" },
      field("Độ khó", difficulty), field("Số lượt", turns)),
    el("label.check", { style: "margin-bottom:16px" }, hide,
      el("span", null, el("b", { text: "Ẩn kịch bản" }),
        el("div", { style: "font-size:var(--t-xs);color:var(--ink-3)",
          text: "Giống buổi thật: bạn nghe rồi dịch, không đọc chữ trước. Bản gốc hiện sau khi chấm." }))),
    el("p.card-sub", { style: "margin-bottom:16px",
      text: "Mỗi lượt khoảng 5 câu, đọc lên 30–60 giây (chấp nhận 24–78 giây vì ước lượng " +
            "thời lượng tính từ số từ nên có sai số). Hai nhân vật nói xen kẽ Việt–Anh nên bạn dịch cả hai chiều." }),
    submit
  );
}

/* ============================== Thanh trên của buổi ============================== */

function topBar(session, turns, index, onExit) {
  const progress = el("div.mock-progress", { "aria-label": `Lượt ${index + 1}/${turns.length}` });
  turns.forEach((turn, i) => {
    const scored = turn.attempt?.score_overall != null;
    progress.append(
      el("i", { dataset: { state: scored ? "done" : i === index ? "now" : "" } })
    );
  });

  const turn = turns[index];
  return el(
    "div.mock-bar",
    null,
    el("button.btn.btn-sm.btn-ghost", { type: "button", text: "← Thoát", onclick: onExit }),
    el("div", null,
      el("div.who", { text: turn.speaker_name || `Lượt ${index + 1}` }),
      el("div.meta", { text: turn.speaker_role || "" })),
    el("div.spacer"),
    el("div.meta", {
      text: `${LANG[turn.source_lang]} → ${LANG[turn.target_lang]} · ~${Math.round(turn.est_duration_sec)}s`,
    }),
    progress,
    el("div.meta", { text: `${index + 1}/${turns.length}` })
  );
}

/* ============================== Khối nghe ============================== */

function listenBlock(turn, hideScript, revealBox) {
  const player = el("audio", { controls: true, style: "flex:1;min-width:220px;height:38px" });
  const speed = el("select.select", { style: "width:auto" },
    [["slow", "Chậm"], ["normal", "Bình thường"], ["fast", "Nhanh"]].map(([v, t]) =>
      el("option", { value: v, text: t, selected: v === "normal" })));
  const info = el("span.meta", { style: "font-size:var(--t-xs);color:var(--ink-3)" });
  let replays = 0;

  const play = el("button.btn.btn-primary", {
    type: "button",
    text: "🔊 Phát lời thoại",
    onclick: async () => {
      await withBusy(play, "Đang chuẩn bị…", async () => {
        try {
          const result = await api.turnAudio(turn.id, speed.value);
          player.src = api.audioUrl(result.key);
          player.play().catch(() => {});
          replays += 1;
          info.textContent =
            `${result.engine} · giọng ${result.voice} · đã nghe ${replays} lần` +
            (result.cached ? " · lấy từ cache" : "");
          if ((result.substitutions ?? []).length) {
            info.textContent +=
              " · đọc tên riêng theo bảng thuật ngữ: " +
              result.substitutions.map((s) => `${s.surface}→${s.spoken_as}`).join(", ");
          }
        } catch (error) {
          // Hỏng TTS thì buổi mock vẫn tiếp tục bằng lời thoại dạng chữ
          fail(`${error.message} Lời thoại hiện dạng chữ bên dưới.`);
          revealBox();
        }
      });
    },
  });

  return {
    node: el("div.mock-listen", null, play, speed, player, info),
    getReplays: () => replays,
  };
}

/* ============================== Khối gõ bản dịch ==============================
 *
 * Chỉ gõ, không ghi âm. Bỏ ghi âm vì: nhận dạng chạy trên máy chủ nên mỗi lượt phải chờ
 * 15–30 giây, qua đường tunnel còn lâu hơn; và mô hình hay viết sai số liệu, đúng thứ
 * phiên dịch không được sai. Phần NGHE lời thoại vẫn giữ — đó mới là cái tạo áp lực thật.
 */

function inputBlock(turn, workspaceId, onScored) {
  const target = LANG[turn.target_lang];
  const transcript = el("textarea.textarea", {
    rows: 6,
    placeholder: `Bản dịch sang ${target}. Giữ nguyên chính xác mọi con số, tên riêng và chức danh.`,
  });

  const counter = el("div", {
    style: "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-4);margin-top:6px",
    text: "0 từ",
  });
  transcript.addEventListener("input", () => {
    const words = transcript.value.trim().split(/\s+/).filter(Boolean).length;
    counter.textContent = `${words} từ`;
  });

  const scoreBtn = el("button.btn.btn-primary.btn-lg", { type: "button", text: "Chấm điểm" });
  scoreBtn.addEventListener("click", async () => {
    const text = transcript.value.trim();
    if (!text) {
      toast("warn", "Chưa có bản dịch để chấm.");
      return;
    }
    await withBusy(scoreBtn, "Đang chấm…", async () => {
      const submitted = await api.submitAttempt({
        turn_id: turn.id,
        transcript: text,
        transcript_raw: text,
        input_mode: "typed",
        replay_count: 0,
      });
      const score = await api.scoreAttempt(submitted.attempt_id);
      onScored(score, submitted.attempt_id, text);
    });
  });

  // Ctrl+Enter chấm luôn — đỡ phải rời bàn phím giữa chừng
  transcript.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      scoreBtn.click();
    }
  });

  return {
    node: el(
      "div.card",
      null,
      el("div.card-title", { text: `Dịch sang ${target}` }),
      el("p.card-sub", {
        style: "margin-bottom:10px",
        text: "Nghe lời thoại ở trên rồi gõ bản dịch. Cố gắng dịch một lượt, đừng nghe đi nghe lại — buổi thật không cho phép.",
      }),
      transcript,
      counter,
      el(
        "div.btn-row",
        { style: "margin-top:14px" },
        scoreBtn,
        el("span", {
          style: "font-size:var(--t-xs);color:var(--ink-4)",
          text: "hoặc Ctrl+Enter",
        })
      )
    ),
  };
}

/* ============================== Kết quả chấm ============================== */

function scoreView(score, turn, attemptId, userText, onNext) {
  const s = score.scores;
  const cells = CRITERIA.map(([key, label]) =>
    el("div.score-cell", { dataset: { level: level(s[key]) } },
      el("div.v", { text: s[key].toFixed(1) }), el("div.k", { text: label }))
  );
  cells.push(
    el("div.score-cell.is-total", null,
      el("div.v", { text: s.overall.toFixed(1) }), el("div.k", { text: "Điểm lượt" }))
  );

  const box = el("div", { style: "margin-top:16px" },
    el("div.score-grid", null, cells),
    el("div.card", null, el("div.card-title", { text: "Nhận xét" }),
      el("div", { style: "white-space:pre-wrap;font-size:var(--t-sm)", text: score.comment }))
  );

  for (const n of score.notes ?? []) box.append(el("div", { style: "margin-top:12px" }, note("warn", n)));

  const verdicts = score.term_verdicts ?? [];
  if (verdicts.length) {
    box.append(
      el("div.card", { style: "margin-top:12px" },
        el("div.card-title", { text: "Thuật ngữ trong lượt này" }),
        verdicts.map((v) =>
          el(`div.term-verdict.${v.correct ? "is-ok" : "is-bad"}`, null,
            el("span.mark", { text: v.correct ? "✓" : "✕" }),
            el("span", null,
              el("b", { text: v.term_vi }), " → ",
              el("code", { text: v.expected_en }),
              !v.correct && el("span", { style: "color:var(--ink-3)",
                text: v.used_by_expert ? ` · bạn dùng: ${v.used_by_expert}` : " · bạn bỏ sót" }))))
      )
    );
  }

  if ((score.missing_items ?? []).length) {
    box.append(
      el("div.card", { style: "margin-top:12px" },
        el("div.card-title", { text: "Thông tin bị bỏ sót" }),
        el("div", { style: "display:flex;gap:6px;flex-wrap:wrap" },
          score.missing_items.map((m) => el("span.badge.badge-flag", { text: m }))))
    );
  }

  // Bản gốc + bản tham chiếu hiện SAU khi chấm (A3.12), dựng bằng cái sống
  const [tierCls, tierText] = TIER[score.reference_tier] ?? TIER.ai;
  box.append(
    el("div", { style: "margin-top:16px" },
      el("div", { style: "display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap" },
        el("span", { style: "font-weight:700;font-size:var(--t-sm)", text: "Bản gốc và bản dịch tham chiếu" }),
        el(`span.badge.${tierCls}`, { text: tierText })),
      spine({
        number: turn.turn_index + 1,
        left: { lang: turn.source_lang, text: turn.source_text },
        right: { lang: turn.target_lang, text: score.reference_translation },
      })),
    el("div", { style: "margin-top:12px" },
      el("div", { style: "font-weight:700;font-size:var(--t-sm);margin-bottom:6px", text: "Bản dịch bạn đã nộp" }),
      el("div.card", null, el("div", { style: "white-space:pre-wrap;font-size:var(--t-sm)", text: userText }))),
    verdictBlock(attemptId, s, onNext)
  );

  return box;
}

/* ============================== §6 Phản biện điểm ============================== */

function verdictBlock(attemptId, aiScores, onNext) {
  const box = el("div.card", { style: "margin-top:16px" });
  const done = (result) => {
    box.innerHTML = "";
    for (const m of result.messages ?? []) box.append(note("ok", m));
    for (const c of result.contradictions ?? []) {
      box.append(note("warn",
        `Nhận định trước của bạn (${String(c.created_at).slice(0, 10)}) đi ngược hướng — ` +
        `lần đó bạn ${c.direction} ${Math.abs(c.gap)} điểm: “${String(c.note).slice(0, 150)}”. ` +
        "Hệ thống không tự chọn bên nào."));
    }
    box.append(el("div.btn-row", { style: "margin-top:12px" },
      el("button.btn.btn-primary", { type: "button", text: "Lượt tiếp theo →", onclick: onNext })));
  };

  const sliders = {};
  const grid = el("div", { style: "display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px" });
  for (const [key, label] of CRITERIA) {
    const input = el("input", {
      type: "range", min: "0", max: "10", step: "0.5",
      value: String(aiScores[key]), style: "width:100%",
    });
    const out = el("span.mono", { text: aiScores[key].toFixed(1) });
    input.addEventListener("input", () => (out.textContent = Number(input.value).toFixed(1)));
    sliders[key] = input;
    grid.append(el("label", null,
      el("div", { style: "font-size:var(--t-xs);color:var(--ink-3);display:flex;justify-content:space-between" },
        el("span", { text: label }), out),
      input));
  }

  const noteInput = el("textarea.textarea", { rows: 3,
    placeholder: "ví dụ: “nghiệm thu” ở đây phải dịch là acceptance, không phải inspection — AI chấm sai tiêu chí Thuật ngữ." });
  const pinInput = el("textarea.textarea", { rows: 2,
    placeholder: "Bản dịch bạn cho là chuẩn — sẽ thành bản tham chiếu ⭐⭐ thay bản AI sinh." });

  const agree = el("button.btn.btn-primary", { type: "button", text: "✓ Đồng ý với điểm AI" });
  agree.addEventListener("click", async () => {
    await withBusy(agree, "…", async () => done(await api.submitVerdict({ attempt_id: attemptId, action: "agree" })));
  });

  const save = el("button.btn.btn-primary", { type: "button", text: "Lưu nhận định" });
  save.addEventListener("click", async () => {
    const changed = CRITERIA.some(([k]) => Math.abs(Number(sliders[k].value) - aiScores[k]) > 0.01);
    const hasNote = noteInput.value.trim().length > 0;
    const hasPin = pinInput.value.trim().length > 0;
    if (!changed && !hasNote && !hasPin) {
      toast("warn", "Chưa sửa gì và chưa ghi lý do — bấm “Đồng ý với điểm AI” là đủ.");
      return;
    }
    await withBusy(save, "Đang lưu…", async () => {
      const body = {
        attempt_id: attemptId,
        action: hasPin ? "pin_translation" : changed ? "adjust" : "note",
        note: noteInput.value.trim(),
        pinned_translation: pinInput.value.trim(),
      };
      if (changed) for (const [k] of CRITERIA) body[`score_${k}`] = Number(sliders[k].value);
      done(await api.submitVerdict(body));
    });
  });

  box.append(
    el("div.card-title", { text: "💬 Nhận định của bạn" }),
    el("p.card-sub", { style: "margin-bottom:14px",
      text: "AI chấm trước, bạn là người phán quyết. Nhận định CÓ ghi lý do sẽ thành luật chấm cho các buổi sau với hồ sơ này." }),
    el("div.btn-row", { style: "margin-bottom:16px" }, agree),
    el("details", null,
      el("summary", { style: "cursor:pointer;font-weight:600;font-size:var(--t-sm)",
        text: "Sửa điểm / ghi nhận định / chốt cách dịch" }),
      el("div", { style: "margin-top:14px" },
        grid,
        el("div", { style: "margin-top:14px" }, field("Lý do — vì sao AI chấm chưa đúng?", noteInput)),
        field("Chốt cách dịch cho lượt này", pinInput),
        el("div.btn-row", null, save)))
  );
  return box;
}

/* ============================== Báo cáo cuối buổi ============================== */

async function reportView(root, sessionId, workspace) {
  const report = await api.sessionReport(sessionId);
  const body = el("div.mock-body");
  root.append(
    el("div.mock-bar", null,
      el("button.btn.btn-sm.btn-ghost", { type: "button", text: "← Thoát",
        onclick: () => router.go("dashboard") }),
      el("div.who", { text: "Báo cáo buổi mock" }),
      el("div.spacer"),
      el("button.btn.btn-sm", { type: "button", text: "Buổi mới", onclick: () => router.go("mock") })),
    body
  );

  if (report.overall_score == null) {
    body.append(empty("Chưa có lượt nào được chấm trong buổi này",
      "Quay lại luyện tập và chấm ít nhất một lượt."));
    return;
  }

  const averages = report.averages ?? {};
  body.append(
    el("div.page-head", null,
      el("div.eyebrow", { text: "KẾT QUẢ" }),
      el("h1", { text: `Điểm tổng ${report.overall_score.toFixed(1)}/10` }),
      el("p", { text: `Đã chấm ${report.n_scored}/${report.n_turns} lượt.` })),
    el("div.card", null,
      barChart({
        items: CRITERIA.filter(([k]) => averages[k] != null)
          .map(([k, label]) => ({ label, value: averages[k] })),
      })),
  );

  const review = report.terms_to_review ?? [];
  if (review.length) {
    body.append(
      el("div.section", null,
        el("h2", { text: "Thuật ngữ cần ôn" }),
        el("div.card", { style: "padding:8px 4px" },
          review.map((t) =>
            el("div.review-term", null,
              el("div.pair", null, el("div.vi", { text: t.term_vi }), el("div.en", { text: t.expected ?? "" })),
              el("span.badge.badge-flag", { text: `sai ${t.count} lần` })))))
    );
  }

  body.append(
    el("div.section", null,
      el("h2", { text: "Chi tiết theo lượt" }),
      (report.turns ?? []).filter((t) => t.score_overall != null).map((t) =>
        el("details.card", { style: "margin-bottom:8px" },
          el("summary", { style: "cursor:pointer;font-weight:600;font-size:var(--t-sm)",
            text: `Lượt ${t.turn_index + 1} · ${t.source_lang}→${t.target_lang} · ${t.score_overall.toFixed(1)}/10` }),
          el("div", { style: "margin-top:12px" },
            spine({
              number: t.turn_index + 1,
              left: { lang: t.source_lang, text: t.source_text },
              right: { lang: t.target_lang, text: t.reference_translation ?? "" },
            }),
            el("div", { style: "margin-top:12px" },
              el("div", { style: "font-weight:700;font-size:var(--t-sm)", text: "Bạn dịch" }),
              el("div.card-sub", { style: "white-space:pre-wrap",
                text: t.transcript_edited || t.transcript_raw || "" })),
            el("div", { style: "margin-top:12px" }, note("ok", t.comment ?? ""))))))
  );
}

/* ============================== Luyện tập ============================== */

async function practiceView(root, sessionId, workspace) {
  let data = await api.getSession(sessionId);
  const turns = data.turns;
  const session = data.session;

  if (!turns.length) {
    root.append(el("div.mock-body", null, empty("Buổi này không có lượt nào", "Sinh kịch bản mới.")));
    return;
  }

  // Mở đúng lượt chưa chấm đầu tiên — mở lại buổi dở thì vào ngay chỗ đang dừng
  let index = turns.findIndex((t) => t.attempt?.score_overall == null);
  if (index < 0) index = turns.length - 1;

  const bar = el("div");
  const body = el("div.mock-body");
  root.append(bar, body);

  function drawTurn() {
    const turn = turns[index];
    bar.innerHTML = "";
    bar.append(topBar(session, turns, index, () => router.go("dashboard")));

    body.innerHTML = "";
    const stage = el("div.turn-enter");
    body.append(stage);

    for (const w of session.gen_warnings ?? []) stage.append(note("warn", w));

    const sourceBox = el("div");
    const revealSource = () => {
      sourceBox.innerHTML = "";
      sourceBox.append(
        el("div.card", null,
          el("div.card-title", { text: `Lời người nói (${LANG[turn.source_lang]})` }),
          el("div", { style: "white-space:pre-wrap", text: turn.source_text }))
      );
    };

    const listen = listenBlock(turn, session.hide_script, revealSource);
    stage.append(listen.node);

    // Ẩn kịch bản: chỉ hiện chữ khi chuyên gia chủ động bấm (A3.12)
    if (session.hide_script) {
      sourceBox.append(
        el("div.card", null,
          el("div.card-sub", { text: "Kịch bản đang ẩn để giống buổi thật — bạn nghe rồi dịch. Bản gốc dạng chữ sẽ hiện sau khi chấm." }),
          el("button.btn.btn-sm", { type: "button", style: "margin-top:10px",
            text: "👁️ Hiện lời thoại dạng chữ", onclick: revealSource }))
      );
    } else {
      revealSource();
    }
    stage.append(sourceBox);

    const result = el("div");
    const already = turn.attempt?.score_overall != null;

    if (already) {
      revealSource();
      result.append(note("ok", `Lượt này đã chấm: ${turn.attempt.score_overall.toFixed(1)}/10. Xem chi tiết ở báo cáo cuối buổi.`));
    } else {
      const input = inputBlock(turn, workspace.id, (score, attemptId, userText) => {
        revealSource();
        input.node.replaceWith(scoreView(score, turn, attemptId, userText, next));
        turn.attempt = { score_overall: score.scores.overall };
        bar.innerHTML = "";
        bar.append(topBar(session, turns, index, () => router.go("dashboard")));
      });
      stage.append(input.node);
    }
    stage.append(result);

    stage.append(
      el("div.btn-row", { style: "margin-top:24px" },
        index > 0 && el("button.btn", { type: "button", text: "← Lượt trước",
          onclick: () => { index -= 1; drawTurn(); } }),
        index < turns.length - 1 && el("button.btn", { type: "button", text: "Lượt tiếp theo →", onclick: next }),
        el("button.btn", { type: "button", text: "Kết thúc buổi", onclick: finish }))
    );
  }

  function next() {
    if (index < turns.length - 1) {
      index += 1;
      drawTurn();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      finish();
    }
  }

  async function finish() {
    try {
      await api.completeSession(sessionId);
    } catch {
      /* hoàn tất hỏng không đáng chặn xem báo cáo */
    }
    router.go("mock", { session: sessionId, view: "report" });
  }

  drawTurn();
}

/* ============================== Render ============================== */

export async function render(root, params) {
  const current = store.currentWorkspace();
  if (!current) {
    root.append(el("div.mock-body", null,
      empty("Chưa chọn hồ sơ khách hàng", "Tạo hoặc chọn một hồ sơ ở Bảng điều khiển trước.")));
    return;
  }

  const stage = el("div.mock-stage");
  root.append(stage);

  const sessionId = params.session ? Number(params.session) : null;

  if (sessionId && params.view === "report") {
    await reportView(stage, sessionId, current);
    return;
  }
  if (sessionId) {
    await practiceView(stage, sessionId, current);
    return;
  }

  await configView(stage, current);

  // Danh sách buổi trước, để mở lại buổi đang dở
  try {
    const sessions = await api.listSessions(current.id);
    if (sessions.length) {
      stage.querySelector(".mock-body")?.append(
        el("div.section", null,
          el("h2", { text: "Các buổi trước" }),
          el("div.card", { style: "padding:0" },
            sessions.slice(0, 10).map((s) =>
              el("div", { style: "display:flex;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid var(--line)" },
                el("div", { style: "flex:1" },
                  el("div", { style: "font-weight:600;font-size:var(--t-sm)",
                    text: `Buổi #${s.id} · ${s.n_turns} lượt · ${s.difficulty}` }),
                  el("div", { style: "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-3)",
                    text: `${String(s.created_at).slice(0, 16)} · ${s.status}` })),
                s.overall_score != null && el("span.badge.badge-ok", { text: `${s.overall_score.toFixed(1)}/10` }),
                el("button.btn.btn-sm", { type: "button", text: "Mở lại",
                  onclick: () => router.go("mock", { session: s.id }) })))))
      );
    }
  } catch {
    /* danh sách buổi hỏng không đáng chặn màn cấu hình */
  }
}
