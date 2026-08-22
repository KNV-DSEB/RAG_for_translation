/**
 * Màn hình: Bảng điều khiển.
 *
 * Vào:  hồ sơ khách hàng đang chọn.
 * Ra:   việc đang dở · buổi sắp tới · tiến bộ theo thời gian · thuật ngữ cần ôn (A6.5),
 *       cộng gợi ý bước tiếp theo cho người chưa quen (A6.9).
 *
 * Gọi ĐÚNG MỘT lần `/dashboard` — backend đã gom sẵn, khỏi phải sáu vòng chờ.
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import { lineChart, legend } from "../charts.js";
import {
  el, pageHead, stats, note, loading, empty, field, toast, ok, withBusy, fmtNum,
} from "../ui.js";

const CRITERIA = [
  ["meaning", "Nghĩa"],
  ["terminology", "Thuật ngữ"],
  ["completeness", "Đầy đủ"],
  ["expression", "Diễn đạt"],
];

/* ============================== Tạo hồ sơ đầu tiên ============================== */

function createWorkspaceForm(onDone) {
  const name = el("input.input", { placeholder: "ví dụ: Latter-Day Saint Charities" });
  const industry = el("input.input", { placeholder: "ví dụ: viện trợ nhân đạo" });
  const secret = el("input", { type: "checkbox" });
  const notes = el("textarea.textarea", { placeholder: "Website, quốc gia, thông tin bạn đã biết…" });
  const submit = el("button.btn.btn-primary", { type: "submit", text: "Tạo hồ sơ" });

  return el(
    "form.card",
    {
      onsubmit: async (event) => {
        event.preventDefault();
        if (!name.value.trim()) {
          toast("warn", "Cần nhập tên khách hàng.");
          return;
        }
        await withBusy(submit, "Đang tạo…", async () => {
          const created = await api.createWorkspace({
            name: name.value.trim(),
            industry: industry.value.trim() || null,
            is_confidential: secret.checked,
            notes: notes.value.trim() || null,
          });
          await store.refreshWorkspaces();
          store.setWorkspace(created.id);
          ok(`Đã tạo hồ sơ “${created.name}”.`);
          onDone();
        });
      },
    },
    el("div.card-title", { text: "Tạo hồ sơ khách hàng" }),
    el("p.card-sub", {
      text: "Mọi tài liệu, thuật ngữ và buổi mock đều thuộc về một hồ sơ khách hàng.",
      style: "margin-bottom:16px",
    }),
    field("Tên khách hàng", name, null, true),
    field("Ngành nghề / lĩnh vực", industry, "Không bắt buộc. Giúp thu hẹp kết quả tìm kiếm."),
    el(
      "label.check",
      { style: "margin-bottom:16px" },
      secret,
      el(
        "span",
        null,
        el("b", { text: "Hồ sơ mật" }),
        el("div", {
          style: "font-size:var(--t-xs);color:var(--ink-3)",
          text: "Trước mỗi lần gửi dữ liệu ra ngoài, hệ thống hiện nội dung sẽ gửi và chờ bạn đồng ý.",
        })
      )
    ),
    field("Ghi chú", notes),
    submit
  );
}

/* ============================== Các khối ============================== */

function nextStep(step) {
  if (!step) return null;
  return el(
    "div.card.card-accent",
    null,
    el("div.card-title", { text: `→ ${step.title}` }),
    el("p.card-sub", { text: step.detail }),
    el("button.btn.btn-primary", {
      type: "button",
      text: step.label,
      style: "margin-top:12px",
      onclick: () => router.go(step.page),
    })
  );
}

function quickActions() {
  const ACTIONS = [
    ["Nạp tài liệu", "documents", "Hợp đồng, biên bản, bài phát biểu"],
    ["Nghiên cứu khách hàng", "research", "Hồ sơ có nguồn + bảng thuật ngữ"],
    ["Luyện buổi mock", "mock", "Kịch bản 8–10 lượt, dịch hai chiều"],
    ["Xem hiệu chỉnh", "calibration", "AI chấm lệch bao nhiêu so với bạn"],
  ];
  return el(
    "div.dash-grid",
    null,
    ACTIONS.map(([label, page, hint]) =>
      el(
        "button.card",
        {
          type: "button",
          style: "text-align:left;cursor:pointer;font:inherit;color:inherit",
          onclick: () => router.go(page),
        },
        el("div.card-title", { text: label }),
        el("div.card-sub", { text: hint })
      )
    )
  );
}

function pendingWork(items) {
  if (!items.length) {
    return el(
      "div.card",
      null,
      el("div.card-sub", {
        text: "Không có việc nào đang dở. Mọi tài liệu đã nạp xong, không có buổi mock bỏ giữa chừng.",
      })
    );
  }
  return el(
    "div",
    null,
    items.map((item) =>
      el(
        "div.work-item",
        null,
        el("span.ico", { text: item.icon, "aria-hidden": "true" }),
        el("div.body", null, el("div.t", { text: item.title }), el("div.d", { text: item.detail })),
        el("button.btn.btn-sm", {
          type: "button",
          text: item.action,
          onclick: () => router.go(item.page, item.session_id ? { session: item.session_id } : {}),
        })
      )
    )
  );
}

function upcoming(items) {
  if (!items.length) return null;
  return el(
    "div.section",
    null,
    el("h2", { text: "Buổi làm việc sắp tới" }),
    items.map((item) =>
      el(
        "div.card",
        null,
        el("div.card-title", { text: `${item.event_date} — ${item.topic}` }),
        el("div.card-sub", {
          text: item.partners.length ? item.partners.join(" · ") : "chưa nêu đối tác",
        })
      )
    )
  );
}

function progressBlock(progress) {
  const sessions = progress?.sessions ?? [];
  const box = el("div.section", null, el("h2", { text: "Tiến bộ qua các buổi" }));

  if (sessions.length < 2) {
    box.append(
      el(
        "div.card",
        null,
        el("div.card-sub", {
          text: `Mới có ${sessions.length} buổi đã chấm. Cần ít nhất 2 buổi mới vẽ được đường tiến bộ.`,
        })
      )
    );
    return box;
  }

  const styles = getComputedStyle(document.documentElement);
  box.append(
    el(
      "div.card",
      null,
      lineChart({
        main: sessions.map((s) => s.overall),
        thin: CRITERIA.map(([key, label]) => ({ label, values: sessions.map((s) => s[key]) })),
        xLabels: sessions.map((_, i) => String(i + 1)),
        yMax: 10,
      }),
      legend([
        ["Điểm tổng", styles.getPropertyValue("--vi").trim(), false],
        ["Nghĩa", styles.getPropertyValue("--vi").trim(), true],
        ["Thuật ngữ", styles.getPropertyValue("--en").trim(), true],
        ["Đầy đủ", styles.getPropertyValue("--warn").trim(), true],
        ["Diễn đạt", styles.getPropertyValue("--ink-3").trim(), true],
      ]),
      progress.trend &&
        el("p.card-sub", { style: "margin-top:12px", text: `Xu hướng: ${progress.trend}.` })
    )
  );
  return box;
}

function termsToReview(items) {
  const box = el("div.section", null, el("h2", { text: "Thuật ngữ cần ôn" }));
  if (!items.length) {
    box.append(
      el(
        "div.card",
        null,
        el("div.card-sub", {
          text: "Chưa có thuật ngữ nào bị dịch sai. Danh sách này tự gom lại sau khi bạn luyện vài buổi.",
        })
      )
    );
    return box;
  }
  box.append(
    el("p.card-sub", {
      style: "margin-bottom:12px",
      text: `${items.length} thuật ngữ đã dịch sai trong các buổi mock, xếp theo số lần sai.`,
    }),
    el(
      "div.card",
      { style: "padding:8px 4px" },
      items.map((item) =>
        el(
          "div.review-term",
          null,
          el("div.pair", null, el("div.vi", { text: item.term_vi }), el("div.en", { text: item.expected ?? "" })),
          el("span.badge.badge-flag", { text: `sai ${item.wrong_times} lần` })
        )
      )
    ),
    el("button.btn", {
      type: "button",
      style: "margin-top:12px",
      text: "Luyện lại buổi mock",
      onclick: () => router.go("mock"),
    })
  );
  return box;
}

async function systemHealth() {
  const box = el("div.section", null, el("h2", { text: "Sức khoẻ hệ thống" }));
  try {
    const h = await api.health();
    box.append(
      stats([
        ["Python", h.python_version],
        ["Bảng dữ liệu", `${h.n_tables}/18`],
        ["RAM backend", `${Math.round(h.rss_mb)} MB`],
        ["Trạng thái", h.status === "ok" ? "ổn" : "cần xem"],
      ])
    );
    for (const w of h.warnings ?? []) {
      box.append(el("div", { style: "margin-top:12px" }, note("warn", w)));
    }
  } catch (error) {
    box.append(note("error", error.message));
  }
  return box;
}

/* ============================== Render ============================== */

export async function render(root) {
  const current = store.currentWorkspace();

  if (!current) {
    root.append(
      pageHead("CHUẨN BỊ", "Bảng điều khiển", "Bắt đầu bằng cách tạo hồ sơ khách hàng đầu tiên"),
      empty(
        "Chưa có hồ sơ khách hàng nào",
        "Mọi tài liệu, kết quả nghiên cứu, bảng thuật ngữ và buổi mock đều thuộc về một hồ sơ khách hàng."
      ),
      createWorkspaceForm(() => router.render())
    );
    return;
  }

  root.append(pageHead("CHUẨN BỊ", current.name, "Đang dở việc gì, sắp tới có gì, và tiến bộ tới đâu"));

  const slot = el("div");
  root.append(slot);
  slot.append(loading("Đang tổng hợp…"));

  const data = await api.dashboard(current.id);
  slot.innerHTML = "";

  slot.append(
    stats([
      ["Tài liệu", fmtNum(data.n_documents)],
      ["Thuật ngữ", fmtNum(data.n_terms)],
      ["Buổi mock", fmtNum(data.n_sessions)],
      ["Nhận định đã ghi", fmtNum(data.n_verdicts)],
    ])
  );

  const step = nextStep(data.next_step);
  if (step) slot.append(el("div", { style: "margin-top:16px" }, step));

  slot.append(
    el("div.section", null, el("h2", { text: "Làm gì tiếp" }), quickActions()),
    el("div.section", null, el("h2", { text: "Việc đang dở" }), pendingWork(data.pending_work ?? [])),
    upcoming(data.upcoming ?? []),
    progressBlock(data.progress ?? {}),
    termsToReview(data.terms_to_review ?? []),
    await systemHealth()
  );
}
