/**
 * Màn hình: Bảo mật (§7) — kiểm chứng dữ liệu nào đã rời khỏi máy này.
 *
 * Vào:  hồ sơ khách hàng đang chọn (hoặc xem toàn bộ).
 * Ra:   nhật ký egress, trạng thái vé đồng ý, bật/tắt cờ hồ sơ mật.
 *
 * Đây là công cụ để chuyên gia TỰ KIỂM CHỨNG chứ không phải tin lời: cột số ký tự phải ở
 * cỡ đoạn ngữ cảnh (vài nghìn), không phải cỡ cả tài liệu (vài chục nghìn).
 */

import * as api from "../api.js";
import * as store from "../store.js";
import { el, pageHead, stats, note, loading, ok, fail, withBusy, fmtDate, fmtNum } from "../ui.js";

const DEST = {
  llm: "E1 · LLM",
  search: "E2 · tìm kiếm",
  tts: "E3 · đọc lời thoại",
};

export async function render(root) {
  const current = store.currentWorkspace();

  root.append(
    pageHead("HỆ THỐNG", "Bảo mật", "Kiểm chứng chính xác dữ liệu nào đã rời khỏi máy này"),
    el(
      "div.card",
      null,
      el("div.card-title", { text: "Toàn hệ thống có đúng ba đường dữ liệu ra ngoài" }),
      el(
        "div.card-sub",
        null,
        el("div", null, el("b", { text: "E1 — Gọi LLM: " }),
          "chỉ gửi các đoạn ngữ cảnh đã truy hồi, không bao giờ gửi cả tài liệu."),
        el("div", null, el("b", { text: "E2 — Truy vấn tìm kiếm: " }),
          "chuỗi truy vấn, có chứa tên khách hàng và chủ đề."),
        el("div", null, el("b", { text: "E3 — Đọc lời thoại: " }),
          "văn bản lời thoại gửi tới edge-tts. Lần nghe lại lấy từ cache thì không gọi mạng."),
        el("div", { style: "margin-top:8px" },
          "Nhúng embedding, vector DB, nhận dạng giọng nói và cơ sở dữ liệu đều chạy trên máy này.")
      )
    )
  );

  const slot = el("div");
  root.append(slot);

  async function reload() {
    const scopeAll = slot.dataset.scopeAll === "1";
    slot.innerHTML = "";
    slot.append(loading("Đang tải nhật ký…"));

    let rows;
    let consent = null;
    try {
      rows = await api.egressLog(scopeAll || !current ? null : current.id, 500);
      if (current) consent = await api.consentStatus(current.id).catch(() => null);
    } catch (error) {
      slot.innerHTML = "";
      slot.append(note("error", error.message));
      return;
    }

    slot.innerHTML = "";

    if (current) {
      const consentRow = el("div");
      if (consent?.is_confidential) {
        consentRow.append(
          el(
            "div",
            { style: "margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center" },
            el("span", { style: "font-size:var(--t-sm)", text: "Vé đồng ý hiện tại:" }),
            el(`span.badge.${consent.has_llm_consent ? "badge-ok" : "badge-warn"}`, {
              text: consent.has_llm_consent ? "LLM: đã đồng ý" : "LLM: chưa đồng ý",
            }),
            el(`span.badge.${consent.has_search_consent ? "badge-ok" : "badge-warn"}`, {
              text: consent.has_search_consent ? "Tìm kiếm: đã đồng ý" : "Tìm kiếm: chưa đồng ý",
            }),
            el("button.btn.btn-sm.btn-danger", {
              type: "button",
              text: "Thu hồi đồng ý",
              onclick: async (event) => {
                await withBusy(event.currentTarget, "…", async () => {
                  const result = await api.revokeConsent(current.id);
                  ok(result.message);
                  reload();
                });
              },
            })
          )
        );
      }

      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Chế độ hồ sơ mật" }),
          el(
            "div.card",
            null,
            el(
              "label.check",
              null,
              el("input", {
                type: "checkbox",
                checked: Boolean(current.is_confidential),
                onchange: async (event) => {
                  try {
                    await api.updateWorkspace(current.id, {
                      is_confidential: event.target.checked,
                    });
                    await store.refreshWorkspaces();
                    ok(
                      event.target.checked
                        ? "Đã bật chế độ mật. Từ giờ mọi lần gửi dữ liệu ra ngoài sẽ hiện trước cho bạn duyệt."
                        : "Đã tắt chế độ mật. Dữ liệu vẫn được ghi nhật ký đầy đủ."
                    );
                    reload();
                  } catch (error) {
                    fail(error.message);
                  }
                },
              }),
              el(
                "span",
                null,
                el("b", { text: `Hồ sơ “${current.name}” ở chế độ mật` }),
                el("div", {
                  style: "font-size:var(--t-xs);color:var(--ink-3)",
                  text:
                    "Bật thì trước MỖI lần gửi dữ liệu ra ngoài, hệ thống hiện nguyên văn nội dung " +
                    "sẽ gửi và chờ bạn đồng ý.",
                })
              )
            ),
            consentRow
          )
        )
      );
    }

    const byDest = {};
    for (const r of rows) byDest[r.destination] = (byDest[r.destination] ?? 0) + 1;
    const blocked = rows.filter((r) => !r.consented).length;
    const maxChars = rows.length ? Math.max(...rows.map((r) => r.n_chars)) : 0;

    slot.append(
      el(
        "div.section",
        null,
        el("h2", { text: "Nhật ký dữ liệu gửi ra ngoài" }),
        el(
          "label.check",
          { style: "margin-bottom:12px" },
          el("input", {
            type: "checkbox",
            checked: scopeAll,
            onchange: (event) => {
              slot.dataset.scopeAll = event.target.checked ? "1" : "0";
              reload();
            },
          }),
          el("span", { text: "Xem toàn bộ hồ sơ, không chỉ hồ sơ đang chọn" })
        ),
        stats([
          ["Tổng số lần gửi", fmtNum(rows.length)],
          ["Lần bị chặn", fmtNum(blocked)],
          ["E1 · LLM", fmtNum(byDest.llm ?? 0)],
          ["E2 · Tìm kiếm", fmtNum(byDest.search ?? 0)],
          ["E3 · Lời thoại", fmtNum(byDest.tts ?? 0)],
          ["Lần lớn nhất", `${fmtNum(maxChars)} ký tự`],
        ])
      )
    );

    if (maxChars > 40000) {
      slot.append(
        el(
          "div",
          { style: "margin-top:12px" },
          note(
            "warn",
            `Có lệnh gọi gửi tới ${fmtNum(maxChars)} ký tự — kiểm xem có phải đang gửi cả tài liệu ` +
              "thay vì chỉ đoạn ngữ cảnh không."
          )
        )
      );
    }

    if (!rows.length) {
      slot.append(
        el("div", { style: "margin-top:16px" }, note("ok", "Chưa có lần nào dữ liệu rời khỏi máy này."))
      );
      return;
    }

    slot.append(
      el(
        "div.table-wrap",
        { style: "margin-top:16px" },
        el(
          "table.data",
          null,
          el(
            "thead",
            null,
            el(
              "tr",
              null,
              el("th", { text: "Thời điểm" }),
              el("th", { text: "Đích" }),
              el("th", { text: "Mô-đun" }),
              el("th", { text: "Ký tự" }),
              el("th", { text: "Trạng thái" }),
              el("th", { text: "Tóm lược" })
            )
          ),
          el(
            "tbody",
            null,
            rows.slice(0, 300).map((r) =>
              el(
                "tr",
                null,
                el("td", {
                  style: "font-family:var(--font-mono);font-size:var(--t-micro);white-space:nowrap",
                  text: fmtDate(r.created_at),
                }),
                el("td", null,
                  el("span.egress-dest", {
                    dataset: { d: r.destination },
                    text: DEST[r.destination] ?? r.destination,
                  })),
                el("td", {
                  style: "font-family:var(--font-mono);font-size:var(--t-micro)",
                  text: r.module,
                }),
                el("td.num", { text: fmtNum(r.n_chars) }),
                el("td", null,
                  r.consented
                    ? el("span.badge.badge-ok", { text: "cho phép" })
                    : el("span.badge.badge-flag", { text: "BỊ CHẶN" })),
                el("td", {
                  style: "font-size:var(--t-xs);color:var(--ink-3)",
                  text: String(r.summary ?? "").slice(0, 110),
                })
              )
            )
          )
        )
      )
    );
  }

  await reload();
}
