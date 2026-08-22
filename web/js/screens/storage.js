/**
 * Màn hình: Dung lượng — bản ghi âm và cache audio đang chiếm bao nhiêu chỗ.
 *
 * Vào:  hồ sơ khách hàng đang chọn (hoặc xem toàn bộ).
 * Ra:   thống kê dung lượng cache audio, và bản ghi âm cũ nếu còn.
 *
 * Từ khi bỏ ghi âm, sẽ không có bản ghi mới nào được tạo. Phần bản ghi chỉ hiện khi
 * cơ sở dữ liệu còn dữ liệu cũ, để xoá cho sạch — không để lại nút bấm cho tính năng
 * đã không còn.
 */

import * as api from "../api.js";
import * as store from "../store.js";
import {
  el, pageHead, stats, note, loading, ok, fail, withBusy, confirmDanger, fmtBytes, fmtNum,
} from "../ui.js";

export async function render(root) {
  const current = store.currentWorkspace();

  root.append(
    pageHead("HỆ THỐNG", "Dung lượng", "Bản ghi âm và cache audio đang chiếm bao nhiêu chỗ")
  );

  const slot = el("div");
  root.append(slot);

  async function confirmDelete(scope, targetId, label) {
    let preview;
    try {
      preview = await api.recordingsDeletePreview(scope, targetId);
    } catch (error) {
      fail(error.message);
      return;
    }
    if (!preview.n_files) {
      ok("Không có bản ghi âm nào để xoá.");
      return;
    }
    const yes = await confirmDanger({
      title: `Xoá bản ghi âm của ${label}?`,
      body: `${preview.warning} (${preview.n_files} tệp · ${preview.total_mb} MB)`,
      detail: "Điểm đã chấm, bản chữ và báo cáo buổi vẫn được giữ nguyên.",
      confirmLabel: `Xoá ${preview.n_files} bản ghi`,
    });
    if (!yes) return;
    try {
      const result = await api.deleteRecordings(scope, targetId);
      ok(result.message);
      reload();
    } catch (error) {
      fail(error.message);
    }
  }

  async function reload() {
    const scopeAll = slot.dataset.scopeAll === "1";
    slot.innerHTML = "";
    slot.append(loading("Đang tính dung lượng…"));

    let data;
    try {
      data = await api.storageStats(scopeAll || !current ? null : current.id);
    } catch (error) {
      slot.innerHTML = "";
      slot.append(note("error", error.message));
      return;
    }

    slot.innerHTML = "";
    const rec = data.recordings;
    const cache = data.tts_cache;

    slot.append(
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
      stats(
        rec.n_files
          ? [
              ["Bản ghi âm cũ", fmtNum(rec.n_files)],
              ["Dung lượng ghi âm", `${rec.total_mb} MB`],
              ["Tệp audio cache", fmtNum(cache.n_files)],
              ["Dung lượng cache", `${cache.total_mb} MB`],
            ]
          : [
              ["Tệp audio cache", fmtNum(cache.n_files)],
              ["Dung lượng cache", `${cache.total_mb} MB`],
            ]
      )
    );

    if (rec.missing_files) {
      slot.append(
        el(
          "div",
          { style: "margin-top:12px" },
          note(
            "warn",
            `${rec.missing_files} bản ghi có trong cơ sở dữ liệu nhưng tệp đã không còn trên đĩa. ` +
              "Điểm đã chấm vẫn nguyên."
          )
        )
      );
    }

    if (rec.n_files) {
      slot.append(
        el(
          "div.card",
          { style: "margin-top:16px" },
          el("div.card-title", { text: "Bản ghi âm cũ" }),
          el("div.card-sub", {
            text:
              "Tính năng ghi âm đã bỏ nên không có bản ghi mới nào được tạo nữa. " +
              "Đây là dữ liệu còn lại từ trước — xoá được cho sạch, và xoá KHÔNG làm mất " +
              "điểm đã chấm, bản chữ hay báo cáo buổi.",
          })
        )
      );
    }

    const byWorkspace = rec.by_workspace ?? [];
    if (byWorkspace.length) {
      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Theo hồ sơ khách hàng" }),
          el(
            "div.card",
            { style: "padding:0" },
            byWorkspace.map((item) =>
              el(
                "div",
                {
                  style:
                    "display:flex;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid var(--line)",
                },
                el(
                  "div",
                  { style: "flex:1" },
                  el("div", {
                    style: "font-weight:600;font-size:var(--t-sm)",
                    text: item.workspace_name,
                  }),
                  el("div", {
                    style: "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-3)",
                    text: `${item.n_files} tệp · ${fmtBytes(item.bytes)}`,
                  })
                ),
                el("button.btn.btn-sm.btn-danger", {
                  type: "button",
                  text: "Xoá bản ghi",
                  onclick: () =>
                    confirmDelete("workspace", item.workspace_id, `hồ sơ “${item.workspace_name}”`),
                })
              )
            )
          )
        )
      );
    }

    const bySession = rec.by_session ?? [];
    if (bySession.length) {
      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Theo buổi mock" }),
          el(
            "div.card",
            { style: "padding:0" },
            bySession.slice(0, 20).map((item) =>
              el(
                "div",
                {
                  style:
                    "display:flex;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid var(--line)",
                },
                el(
                  "div",
                  { style: "flex:1" },
                  el("div", {
                    style: "font-weight:600;font-size:var(--t-sm)",
                    text: `Buổi #${item.session_id}`,
                  }),
                  el("div", {
                    style: "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-3)",
                    text: `${item.n_files} tệp · ${fmtBytes(item.bytes)}`,
                  })
                ),
                el("button.btn.btn-sm.btn-danger", {
                  type: "button",
                  text: "Xoá bản ghi",
                  onclick: () =>
                    confirmDelete("session", item.session_id, `buổi mock #${item.session_id}`),
                })
              )
            )
          )
        )
      );
    }

    slot.append(
      el(
        "div.section",
        null,
        el("h2", { text: "Cache audio lời thoại" }),
        el(
          "div.card",
          null,
          el("div.card-sub", {
            style: "margin-bottom:12px",
            text:
              "Audio do TTS sinh được giữ lại để nghe lại không phải chờ, và để lần nghe lại KHÔNG " +
              "tính là dữ liệu gửi ra ngoài. Xoá đi thì lần nghe sau sinh lại, chậm hơn vài giây.",
          }),
          el("button.btn.btn-danger", {
            type: "button",
            text: `Xoá ${cache.n_files} tệp cache (${cache.total_mb} MB)`,
            onclick: async (event) => {
              const target = event.currentTarget;
              const yes = await confirmDanger({
                title: "Xoá cache audio?",
                body: `Sẽ xoá ${cache.n_files} tệp audio (${cache.total_mb} MB).`,
                detail: "Lần nghe sau sẽ sinh lại — chậm hơn vài giây nhưng không mất gì.",
                confirmLabel: "Xoá cache",
              });
              if (!yes) return;
              await withBusy(target, "…", async () => {
                const result = await api.clearTtsCache();
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
