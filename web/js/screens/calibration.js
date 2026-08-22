/**
 * Màn hình: Hiệu chỉnh (§6.4) — AI chấm lệch bao nhiêu so với chuyên gia.
 *
 * Vào:  hồ sơ khách hàng đang chọn.
 * Ra:   biểu đồ độ lệch theo tiêu chí, khối luật chấm đang dùng, danh sách nhận định.
 *
 * Mục đích: cho chuyên gia biết KHI NÀO KHÔNG NÊN TIN điểm AI, và thấy chính xác hệ thống
 * đang "nhớ" gì về cách chấm của mình — thay vì phải tin lời.
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import { divergingBarChart } from "../charts.js";
import {
  el, pageHead, stats, note, loading, empty, ok, withBusy, confirmDanger, fmtDate,
} from "../ui.js";

const CRITERIA = ["meaning", "terminology", "completeness", "expression"];

export async function render(root) {
  const current = store.currentWorkspace();
  if (!current) {
    root.append(
      pageHead("LUYỆN TẬP", "Hiệu chỉnh", "AI chấm lệch bao nhiêu so với bạn"),
      empty("Chưa chọn hồ sơ khách hàng", "Tạo hoặc chọn một hồ sơ ở Bảng điều khiển trước.")
    );
    return;
  }

  root.append(
    pageHead(
      "LUYỆN TẬP",
      "Hiệu chỉnh chấm điểm",
      "AI chấm trước, bạn là người phán quyết. Đây là chỗ xem AI đang lệch ý bạn ở đâu."
    )
  );

  const slot = el("div");
  root.append(slot);

  async function reload() {
    slot.innerHTML = "";
    slot.append(loading("Đang tính độ lệch…"));

    let report;
    let preview;
    try {
      [report, preview] = await Promise.all([
        api.divergence(current.id),
        api.calibrationPreview(current.id),
      ]);
    } catch (error) {
      slot.innerHTML = "";
      slot.append(note("error", error.message));
      return;
    }

    slot.innerHTML = "";

    if (!report.n_verdicts) {
      slot.append(
        empty(
          "Chưa có nhận định nào",
          "Sau mỗi lượt chấm ở màn Buổi mock, bấm “Đồng ý” hoặc mở khối sửa điểm. " +
            "Nhận định có ghi lý do sẽ thành luật chấm cho những buổi sau.",
          el("button.btn.btn-primary", {
            style: "margin-top:16px",
            type: "button",
            text: "Mở màn Buổi mock",
            onclick: () => router.go("mock"),
          })
        )
      );
      return;
    }

    slot.append(
      stats([
        ["Nhận định đã ghi", report.n_verdicts],
        ["Lần bạn đồng ý", report.n_agree],
        ["Lần so sánh được", report.n_compared],
        ["Hiệu chỉnh", report.calibration_active ? "đang bật" : "chưa bật"],
      ])
    );

    if (report.trend) {
      slot.append(
        el(
          "div.card",
          { style: "margin-top:16px" },
          el("div.card-title", { text: `Khoảng cách giữa bạn và AI: ${report.trend}` }),
          el("div.card-sub", {
            text:
              "Thu hẹp dần nghĩa là hiệu chỉnh có tác dụng. Nếu đi ngang hoặc giãn ra thì nhận " +
              "định của bạn có thể chưa đủ cụ thể — ghi rõ sai ở đâu và nên chấm thế nào, thay vì " +
              "chỉ kéo thanh điểm.",
          })
        )
      );
    }

    if (report.implied_weight_note) {
      slot.append(el("div", { style: "margin-top:12px" }, note("ok", report.implied_weight_note)));
    }

    const items = CRITERIA.map((key) => report.summary[key])
      .filter((s) => s && s.mean_gap !== null)
      .map((s) => ({ label: s.label, value: s.mean_gap }));

    if (items.length) {
      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Điểm của bạn trừ điểm AI" }),
          el(
            "div.card",
            null,
            divergingBarChart({ items }),
            el("p.card-sub", {
              style: "margin-top:12px",
              text:
                "Cột dương = AI chấm khắt khe hơn bạn. Cột âm = AI dễ dãi hơn bạn. " +
                "Tiêu chí lệch nhiều nhất là chỗ bạn nên tự kiểm lại điểm AI thay vì tin ngay.",
            }),
            el(
              "div.table-wrap",
              { style: "margin-top:14px;border:0" },
              el(
                "table.data",
                null,
                el(
                  "thead",
                  null,
                  el(
                    "tr",
                    null,
                    el("th", { text: "Tiêu chí" }),
                    el("th", { text: "Lệch TB" }),
                    el("th", { text: "Độ lớn TB" }),
                    el("th", { text: "Số lần bạn sửa" })
                  )
                ),
                el(
                  "tbody",
                  null,
                  CRITERIA.map((key) => {
                    const s = report.summary[key];
                    if (!s || s.mean_gap === null) return null;
                    return el(
                      "tr",
                      null,
                      el("td", { text: s.label }),
                      el("td.num", {
                        text: `${s.mean_gap > 0 ? "+" : ""}${s.mean_gap.toFixed(1)}`,
                      }),
                      el("td.num", { text: s.mean_abs_gap.toFixed(1) }),
                      el("td.num", { text: String(s.times_adjusted) })
                    );
                  })
                )
              )
            )
          )
        )
      );
    }

    // Luật chấm đang thực sự được chèn vào prompt — minh bạch, không phải tin lời
    slot.append(
      el(
        "div.section",
        null,
        el("h2", { text: "Luật chấm đang được dùng" }),
        el(
          "div.card",
          null,
          el("p.card-sub", { style: "margin-bottom:12px", text: preview.note }),
          preview.active
            ? el(
                "div",
                null,
                el("pre.payload", { text: preview.text }),
                el("p.card-sub", {
                  style: "margin-top:8px",
                  text: `${preview.n_rules} luật đang được chèn vào mỗi lần chấm điểm.`,
                })
              )
            : note(
                "warn",
                "Chưa có luật chấm nào. Nhận định CÓ ghi lý do mới trở thành luật — " +
                  "sửa điểm suông thì chỉ lưu lại, không dạy được hệ thống."
              )
        )
      )
    );

    try {
      const verdicts = await api.listVerdicts(current.id);
      if (verdicts.length) {
        slot.append(
          el(
            "div.section",
            null,
            el("h2", { text: "Bạn đã dạy hệ thống những gì" }),
            el(
              "div.card",
              { style: "padding:0" },
              verdicts.map((item) => {
                const gap =
                  item.score_overall != null && item.ai_overall != null
                    ? item.score_overall - item.ai_overall
                    : null;
                return el(
                  "div",
                  { style: "padding:12px 20px;border-bottom:1px solid var(--line)" },
                  el(
                    "div",
                    {
                      style:
                        "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px",
                    },
                    el("span.badge.badge-mute", { text: item.action }),
                    item.related_category &&
                      el("span.badge.badge-mute", { text: item.related_category }),
                    gap !== null &&
                      el(`span.badge.${gap >= 0 ? "badge-ok" : "badge-flag"}`, {
                        text: `bạn ${gap > 0 ? "+" : ""}${gap.toFixed(1)} so với AI`,
                      }),
                    el("span", {
                      style:
                        "margin-left:auto;font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-4)",
                      text: fmtDate(item.created_at),
                    })
                  ),
                  el("div", {
                    style: "font-size:var(--t-sm)",
                    text: item.note || "(không ghi lý do — chỉ lưu, không dùng làm luật chấm)",
                  }),
                  item.pinned_translation &&
                    el("div", {
                      style: "margin-top:6px;font-size:var(--t-xs);color:var(--ink-3)",
                      text: `đã chốt bản dịch: ${item.pinned_translation}`,
                    })
                );
              })
            )
          )
        );
      }
    } catch {
      /* danh sách nhận định hỏng không đáng chặn phần còn lại */
    }

    slot.append(
      el(
        "div.section",
        null,
        el("h2", { text: "Đặt lại hiệu chỉnh" }),
        el(
          "div.card",
          null,
          el("p.card-sub", {
            style: "margin-bottom:12px",
            text:
              "Dùng khi thấy hiệu chỉnh làm điểm lệch quá xa. Thao tác này CHỈ bỏ phần luật chấm; " +
              "điểm bạn đã sửa vẫn giữ nguyên trong lịch sử.",
          }),
          el("button.btn.btn-danger", {
            type: "button",
            text: "Đặt lại hiệu chỉnh về mặc định",
            onclick: async (event) => {
              const target = event.currentTarget;
              const yes = await confirmDanger({
                title: "Đặt lại hiệu chỉnh?",
                body: `Sẽ bỏ ${preview.n_rules} luật chấm khỏi prompt. Không hoàn tác được.`,
                detail: "Điểm bạn đã sửa và toàn bộ lịch sử nhận định vẫn được giữ.",
                confirmLabel: "Đặt lại",
              });
              if (!yes) return;
              await withBusy(target, "…", async () => {
                const result = await api.resetCalibration(current.id);
                ok(result.message);
                reload();
              });
            },
          })
        )
      )
    );
  }

  await reload();
}
