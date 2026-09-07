/**
 * Màn hình: Bảo mật (§7) — dữ liệu đang nằm ở đâu, và đã đi những đâu.
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

/**
 * Nhãn trạng thái của một lần gửi.
 *
 * Ba mức, không phải hai, vì chỉ có ba điều ta thật sự biết:
 *   bị chặn            — chưa hề chạm mạng
 *   đã gửi, có phản hồi — nhà cung cấp trả lời bình thường
 *   đã gửi, lỗi         — ĐÃ cố gửi rồi hỏng; KHÔNG kết luận được dữ liệu đã đi hay chưa,
 *                         nên tuyệt đối không được hiện như "chưa gửi"
 */
const DEST_LABEL = { llm: "LLM", search: "Tìm kiếm", tts: "Lời thoại" };

function statusBadge(row) {
  const status = String(row.status ?? "");
  if (status === "blocked") {
    return el("span.badge.badge-mute", { text: "bị chặn", title: "Chưa có gì được gửi đi." });
  }
  if (status === "attempt_failed") {
    return el("span.badge.badge-flag", {
      text: "đã gửi, lỗi",
      title:
        `Đã cố gửi rồi hỏng (${row.error_class ?? "không rõ"}). Không kết luận được dữ ` +
        "liệu đã ra ngoài hay chưa, nên vẫn tính là đã gửi.",
    });
  }
  return el("span.badge.badge-ok", {
    text: "đã gửi, có phản hồi",
    title: "Nhà cung cấp trả lời bình thường.",
  });
}

export async function render(root) {
  const current = store.currentWorkspace();

  root.append(
    pageHead("HỆ THỐNG", "Bảo mật", "Dữ liệu của bạn đang nằm ở đâu, và đã đi những đâu")
  );

  // Bản đồ dữ liệu do MÁY CHỦ sinh ra từ cấu hình đang chạy.
  //
  // Chỗ này trước đây là một đoạn viết cứng nói rằng cơ sở dữ liệu, vector và "nhận dạng
  // giọng nói" đều chạy trên máy này. Câu đó sai ba lần: nhận dạng giọng nói đã bị gỡ
  // khỏi dự án từ lâu, còn trên cloud thì cả cơ sở dữ liệu lẫn vector đều ở Supabase.
  // Một câu viết tay không tự đúng lên được khi kiến trúc đổi — nên nó phải đến từ nơi
  // quyết định dữ liệu nằm ở đâu.
  const BOUNDARY = {
    device: ["badge-ok", "trên máy"],
    app_cloud: ["badge-warn", "kho của ứng dụng"],
    third_party: ["badge-flag", "bên thứ ba"],
  };

  try {
    const map = await api.dataMap();
    root.append(
      el(
        "div.card",
        null,
        el("div.card-title", { text: "Dữ liệu nằm ở đâu" }),
        el("div.card-sub", { style: "margin-bottom:12px", text: map.headline }),
        el(
          "div",
          { style: "display:flex;flex-direction:column;gap:8px" },
          (map.rows ?? []).map((r) => {
            const [cls, label] = BOUNDARY[r.boundary] ?? BOUNDARY.third_party;
            return el(
              "div",
              { style: "display:flex;gap:10px;align-items:baseline;flex-wrap:wrap" },
              el(`span.badge.${cls}`, { text: label }),
              el("b", { style: "min-width:150px", text: r.what }),
              el("span", { style: "font-size:var(--t-sm)", text: r.where }),
              el("span", {
                style: "font-size:var(--t-xs);color:var(--ink-3);flex:1",
                text: r.detail,
              })
            );
          })
        )
      )
    );
  } catch {
    // Không lấy được bản đồ thì KHÔNG hiện gì cả. Hiện một câu mặc định viết cứng ở đây
    // là quay lại đúng cái lỗi vừa sửa.
    root.append(
      note("warn", "Chưa đọc được bản đồ dữ liệu từ máy chủ — thử tải lại trang.")
    );
  }

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
            // Đọc thẳng danh sách quyền máy chủ trả về. Hai cờ `has_llm_consent` /
            // `has_search_consent` cũ đã bị bỏ — và chúng vốn đã thiếu TTS, tức là
            // đường dữ liệu thứ ba không hề hiện ra ở đây.
            ...(consent.grants ?? []).length
              ? (consent.grants ?? []).map((g) =>
                  el("span.badge.badge-ok", {
                    text:
                      `${DEST_LABEL[g.destination] ?? g.destination} · ` +
                      `${g.provider} · ` +
                      // Nhãn phạm vi lấy từ máy chủ: ngữ nghĩa "phiên" khác nhau
                      // giữa bản chạy trên máy và bản chạy trên cloud.
                      (g.scope === "session"
                        ? (consent.session_scope_label ?? "tới khi đóng ứng dụng")
                        : "một thao tác"),
                  })
                )
              : [el("span.badge.badge-warn", { text: "chưa cho phép dịch vụ nào" })],
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
    // Đếm theo `status`, không theo cờ nhị phân cũ. Trường `consented` đã bị bỏ khỏi API;
    // đọc nó ra `undefined` khiến MỌI dòng hiện "BỊ CHẶN" — nói sai theo chiều nguy hiểm
    // nhất, vì nó bảo dữ liệu chưa đi trong khi nó đã đi rồi.
    const attempted = rows.filter((r) => String(r.status ?? "").startsWith("attempt"));
    const blocked = rows.filter((r) => r.status === "blocked").length;
    const failed = rows.filter((r) => r.status === "attempt_failed").length;
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
        // "Đã cố gửi" chứ không phải "đã gửi thành công": một lần hỏng vì timeout có thể
        // đã gửi xong thân request rồi mới hỏng lúc đọc. Ta không chứng minh được việc
        // giao nhận, nên không được dùng chữ đó ở bất kỳ đâu.
        stats([
          ["Đã cố gửi ra ngoài", fmtNum(attempted.length)],
          ["Trong đó có phản hồi", fmtNum(attempted.length - failed)],
          ["Bị chặn", fmtNum(blocked)],
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
        el("div", { style: "margin-top:16px" }, note("ok", "Chưa có lần nào dữ liệu được gửi sang dịch vụ bên thứ ba."))
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
                el("td", null, statusBadge(r)),
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
