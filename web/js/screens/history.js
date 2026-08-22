/**
 * Màn hình: Lịch sử — các buổi mock đã luyện và lịch sử hỏi đáp.
 *
 * Vào:  hồ sơ khách hàng đang chọn.
 * Ra:   danh sách buổi mock (mở lại được), biểu đồ tiến bộ, lịch sử hỏi đáp trên tài liệu.
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import { lineChart, legend } from "../charts.js";
import { el, pageHead, stats, note, loading, empty, fmtDate } from "../ui.js";

const CRITERIA = [
  ["meaning", "Nghĩa"],
  ["terminology", "Thuật ngữ"],
  ["completeness", "Đầy đủ"],
  ["expression", "Diễn đạt"],
];

const STATUS = {
  generated: ["badge-mute", "chưa luyện"],
  in_progress: ["badge-warn", "đang dở"],
  completed: ["badge-ok", "đã xong"],
  abandoned: ["badge-mute", "bỏ giữa chừng"],
};

export async function render(root) {
  const current = store.currentWorkspace();
  if (!current) {
    root.append(
      pageHead("LUYỆN TẬP", "Lịch sử", "Các buổi đã luyện và tiến bộ theo thời gian"),
      empty("Chưa chọn hồ sơ khách hàng", "Tạo hoặc chọn một hồ sơ ở Bảng điều khiển trước.")
    );
    return;
  }

  root.append(
    pageHead(
      "LUYỆN TẬP",
      "Lịch sử",
      "Xem lại các buổi đã luyện, mở lại buổi đang dở, và tiến bộ qua thời gian"
    )
  );

  const slot = el("div");
  root.append(slot);
  slot.append(loading("Đang tải lịch sử…"));

  let sessions;
  let dash;
  try {
    [sessions, dash] = await Promise.all([
      api.listSessions(current.id),
      api.dashboard(current.id).catch(() => null),
    ]);
  } catch (error) {
    slot.innerHTML = "";
    slot.append(note("error", error.message));
    return;
  }

  slot.innerHTML = "";

  if (!sessions.length) {
    slot.append(
      empty(
        "Chưa có buổi mock nào",
        "Sinh kịch bản 8–10 lượt từ hồ sơ khách hàng và bảng thuật ngữ, rồi luyện dịch hai chiều.",
        el("button.btn.btn-primary", {
          style: "margin-top:16px",
          type: "button",
          text: "Sinh kịch bản đầu tiên",
          onclick: () => router.go("mock"),
        })
      )
    );
  } else {
    const scored = sessions.filter((s) => s.overall_score != null);
    const best = scored.length ? Math.max(...scored.map((s) => s.overall_score)) : null;

    slot.append(
      stats([
        ["Tổng số buổi", sessions.length],
        ["Đã chấm", scored.length],
        ["Điểm cao nhất", best != null ? `${best.toFixed(1)}/10` : "—"],
        ["Buổi đang dở", sessions.filter((s) => s.status === "in_progress").length],
      ])
    );

    // Biểu đồ tiến bộ lấy từ /dashboard vì backend đã gộp sẵn trung bình từng tiêu chí
    const prog = dash?.progress?.sessions ?? [];
    if (prog.length >= 2) {
      const styles = getComputedStyle(document.documentElement);
      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Tiến bộ qua các buổi" }),
          el(
            "div.card",
            null,
            lineChart({
              main: prog.map((s) => s.overall),
              thin: CRITERIA.map(([key, label]) => ({ label, values: prog.map((s) => s[key]) })),
              xLabels: prog.map((_, i) => String(i + 1)),
              yMax: 10,
            }),
            legend([
              ["Điểm tổng", styles.getPropertyValue("--vi").trim(), false],
              ["Nghĩa", styles.getPropertyValue("--vi").trim(), true],
              ["Thuật ngữ", styles.getPropertyValue("--en").trim(), true],
              ["Đầy đủ", styles.getPropertyValue("--warn").trim(), true],
              ["Diễn đạt", styles.getPropertyValue("--ink-3").trim(), true],
            ]),
            dash?.progress?.trend &&
              el("p.card-sub", {
                style: "margin-top:12px",
                text: `Xu hướng: ${dash.progress.trend}.`,
              })
          )
        )
      );
    }

    slot.append(
      el(
        "div.section",
        null,
        el("h2", { text: "Các buổi mock" }),
        el(
          "div.card",
          { style: "padding:0" },
          sessions.map((s) => {
            const [cls, label] = STATUS[s.status] ?? ["badge-mute", s.status];
            return el(
              "div",
              {
                style:
                  "display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line)",
              },
              el(
                "div",
                { style: "flex:1;min-width:0" },
                el("div", {
                  style: "font-weight:600;font-size:var(--t-sm)",
                  text: `Buổi #${s.id} · ${s.n_turns} lượt · ${s.difficulty}`,
                }),
                el("div", {
                  style:
                    "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-3);margin-top:3px",
                  text: `${fmtDate(s.created_at)}${s.completed_at ? ` → ${fmtDate(s.completed_at)}` : ""}`,
                })
              ),
              el(`span.badge.${cls}`, { text: label }),
              s.overall_score != null &&
                el("span.badge.badge-ok", { text: `${s.overall_score.toFixed(1)}/10` }),
              el("button.btn.btn-sm", {
                type: "button",
                text: s.overall_score != null ? "Xem báo cáo" : "Mở lại",
                onclick: () =>
                  router.go(
                    "mock",
                    s.overall_score != null
                      ? { session: s.id, view: "report" }
                      : { session: s.id }
                  ),
              })
            );
          })
        )
      )
    );
  }

  try {
    const qa = await api.qaHistory(current.id);
    if (qa.length) {
      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Đã hỏi trên tài liệu" }),
          el(
            "div.card",
            { style: "padding:0" },
            qa.slice(0, 20).map((item) =>
              el(
                "details",
                { style: "padding:12px 20px;border-bottom:1px solid var(--line)" },
                el("summary", {
                  style: "cursor:pointer;font-weight:600;font-size:var(--t-sm)",
                  text: item.question,
                }),
                el("div.card-sub", {
                  style: "margin-top:8px;white-space:pre-wrap",
                  text: item.answer ?? "",
                }),
                el("div", {
                  style:
                    "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-4);margin-top:6px",
                  text: fmtDate(item.created_at),
                })
              )
            )
          )
        )
      );
    }
  } catch {
    /* lịch sử hỏi đáp hỏng không đáng chặn phần còn lại */
  }
}
