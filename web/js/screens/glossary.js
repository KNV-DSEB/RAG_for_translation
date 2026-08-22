/**
 * Màn hình: Thuật ngữ — bảng thuật ngữ song ngữ, sửa được, tái dùng qua các buổi.
 *
 * Vào:  hồ sơ khách hàng đang chọn.
 * Ra:   danh sách thuật ngữ dạng "cái sống" gọn, khối xung đột, thêm tay, xuất CSV.
 *
 * Ba thứ không được làm rơi:
 *   A2.11  thuật ngữ mới dùng được ngay, không có bước duyệt chặn đường
 *   A2.13  xung đột bản dịch hiện ra cho chuyên gia chọn, hệ thống KHÔNG tự chọn
 *   Q6     cột cách đọc phải hiện — chuyên gia phải đọc to được trong buổi dịch
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import {
  el, pageHead, stats, note, loading, empty, spine, toast, ok, fail, withBusy, field, fmtNum,
} from "../ui.js";

const CONFIDENCE = {
  human_translated: ["badge-ok", "⭐⭐⭐ người dịch"],
  machine_guess: ["badge-mute", "máy suy đoán"],
};

const STATUS = {
  auto: ["badge-mute", "tự nhận"],
  expert_edited: ["badge-ok", "bạn đã sửa"],
  skipped: ["badge-mute", "đã bỏ qua"],
};

function tag(map, key) {
  const [cls, text] = map[key] ?? ["badge-mute", String(key)];
  return el(`span.badge.${cls}`, { text });
}

/* ============================== Sửa một thuật ngữ ============================== */

function editRow(term, reload) {
  const vi = el("input.input", { value: term.term_vi });
  const en = el("input.input", { value: term.term_en });
  const pron = el("input.input", {
    value: term.pronunciation ?? "",
    placeholder: "ví dụ: Lát-tơ Đây Xây-nt Cha-ri-tis",
  });
  const def = el("textarea.textarea", { rows: 2, value: term.definition ?? "" });
  const save = el("button.btn.btn-primary.btn-sm", { type: "submit", text: "Lưu" });

  return el(
    "form",
    {
      style: "padding:16px 20px;background:var(--surface-2)",
      onsubmit: async (event) => {
        event.preventDefault();
        await withBusy(save, "Đang lưu…", async () => {
          await api.updateTerm(term.id, {
            term_vi: vi.value.trim(),
            term_en: en.value.trim(),
            pronunciation: pron.value.trim() || null,
            definition: def.value.trim() || null,
          });
          ok("Đã lưu. Dòng này giờ được ưu tiên tuyệt đối — lần nghiên cứu sau không ghi đè.");
          await store.touchWorkspace();
          reload();
        });
      },
    },
    el(
      "div",
      { style: "display:grid;grid-template-columns:1fr 1fr;gap:12px" },
      field("Thuật ngữ tiếng Việt", vi),
      field("Thuật ngữ tiếng Anh", en)
    ),
    field("Cách đọc", pron, "Chỉ điền với tên riêng, tên tổ chức, từ viết tắt. Dùng cho cả phần đọc lời thoại."),
    field("Định nghĩa", def),
    el("div.btn-row", null, save, el("button.btn.btn-sm", { type: "button", text: "Huỷ", onclick: reload }))
  );
}

/* ============================== Một dòng thuật ngữ ============================== */

function termRow(term, reload) {
  const box = el("div.term-item");

  async function resolve(conflictId, accept) {
    try {
      const result = await api.resolveConflict(conflictId, accept);
      ok(result.message);
      reload();
    } catch (error) {
      fail(error.message);
    }
  }

  // ⭐ Cái sống ở dạng gọn: cùng ngữ pháp thị giác với lượt mock
  box.append(
    spine({
      compact: true,
      left: { lang: "vi", text: term.term_vi },
      right: {
        lang: "en",
        text: term.term_en,
        extra: term.pronunciation ? el("div.pron", { text: `đọc: ${term.pronunciation}` }) : null,
      },
    })
  );

  const meta = el(
    "div.term-meta",
    null,
    tag(CONFIDENCE, term.confidence),
    tag(STATUS, term.status),
    term.category && el("span.badge.badge-mute", { text: term.category }),
    el("span", { text: `dùng ${term.frequency} lần` }),
    term.source_ref && el("span", { text: `· ${term.source_ref}` }),
    el(
      "div.btn-row",
      { style: "margin-left:auto" },
      el("button.btn.btn-sm.btn-ghost", {
        type: "button",
        text: "Sửa",
        onclick: () => {
          box.innerHTML = "";
          box.append(editRow(term, reload));
        },
      }),
      el("button.btn.btn-sm.btn-ghost", {
        type: "button",
        text: "Bỏ qua",
        title: "Không xoá hẳn — chỉ để lần sau không đề xuất lại",
        onclick: async () => {
          try {
            await api.skipTerm(term.id);
            ok("Đã bỏ qua thuật ngữ này.");
            await store.touchWorkspace();
            reload();
          } catch (error) {
            fail(error.message);
          }
        },
      })
    )
  );
  box.append(meta);

  if (term.definition) {
    box.append(
      el("div", {
        style: "padding:0 20px 12px;font-size:var(--t-sm);color:var(--ink-2)",
        text: term.definition,
      })
    );
  }

  // Xung đột: hiện CẢ HAI bản để chuyên gia chọn, hệ thống không tự chọn (A2.13)
  for (const conflict of term.conflicts ?? []) {
    box.append(
      el(
        "div",
        {
          style:
            "margin:0 20px 14px;padding:12px;border:1px solid var(--flag);" +
            "border-radius:var(--r-sm);background:var(--flag-soft)",
        },
        el("div", {
          style: "font-weight:600;font-size:var(--t-sm);margin-bottom:6px",
          text: "Xung đột bản dịch — bạn chọn bản nào?",
        }),
        el(
          "div",
          { style: "font-size:var(--t-sm);margin-bottom:10px" },
          el("div", null, "Đang dùng: ", el("code", { text: term.term_en })),
          el("div", null, "Bản mới: ", el("code", { text: conflict.proposed_term_en })),
          el("div", {
            style: "font-size:var(--t-xs);color:var(--ink-3);margin-top:4px",
            text: `nguồn bản mới: ${conflict.source_ref ?? "?"} (${conflict.confidence})`,
          })
        ),
        el(
          "div.btn-row",
          null,
          el("button.btn.btn-sm.btn-primary", {
            type: "button",
            text: "Dùng bản mới",
            onclick: () => resolve(conflict.id, true),
          }),
          el("button.btn.btn-sm", {
            type: "button",
            text: "Giữ bản đang dùng",
            onclick: () => resolve(conflict.id, false),
          })
        )
      )
    );
  }

  return box;
}

/* ============================== Thêm tay ============================== */

function addForm(workspaceId, reload) {
  const vi = el("input.input", { placeholder: "nghiệm thu" });
  const en = el("input.input", { placeholder: "acceptance" });
  const pron = el("input.input", { placeholder: "chỉ điền với tên riêng / viết tắt" });
  const def = el("input.input", { placeholder: "định nghĩa ngắn một câu" });
  const cat = el(
    "select.select",
    null,
    [
      "chuyên ngành", "pháp lý", "kỹ thuật", "thương mại",
      "tài chính", "chính sách", "tên riêng/tổ chức", "viết tắt", "thành ngữ",
    ].map((c) => el("option", { value: c, text: c }))
  );
  const submit = el("button.btn.btn-primary", { type: "submit", text: "Thêm thuật ngữ" });

  return el(
    "details.card",
    null,
    el("summary", { style: "cursor:pointer;font-weight:600", text: "Thêm thuật ngữ thủ công" }),
    el(
      "form",
      {
        style: "margin-top:16px",
        onsubmit: async (event) => {
          event.preventDefault();
          if (!vi.value.trim() || !en.value.trim()) {
            toast("warn", "Cần cả thuật ngữ tiếng Việt và tiếng Anh.");
            return;
          }
          await withBusy(submit, "Đang thêm…", async () => {
            await api.createTerm({
              workspace_id: workspaceId,
              term_vi: vi.value.trim(),
              term_en: en.value.trim(),
              pronunciation: pron.value.trim() || null,
              definition: def.value.trim() || null,
              category: cat.value,
            });
            ok("Đã thêm. Thuật ngữ bạn tự nhập luôn ở mức ưu tiên cao nhất.");
            await store.touchWorkspace();
            reload();
          });
        },
      },
      el(
        "div",
        { style: "display:grid;grid-template-columns:1fr 1fr;gap:12px" },
        field("Tiếng Việt", vi, null, true),
        field("Tiếng Anh", en, null, true)
      ),
      field("Cách đọc", pron),
      field("Định nghĩa", def),
      field("Phân loại", cat),
      submit
    )
  );
}

/* ============================== Render ============================== */

export async function render(root) {
  const current = store.currentWorkspace();
  if (!current) {
    root.append(
      pageHead("CHUẨN BỊ", "Thuật ngữ", "Bảng thuật ngữ song ngữ, tái dùng cho mọi buổi với khách này"),
      empty("Chưa chọn hồ sơ khách hàng", "Tạo hoặc chọn một hồ sơ ở Bảng điều khiển trước.")
    );
    return;
  }

  root.append(
    pageHead(
      "CHUẨN BỊ",
      "Thuật ngữ",
      "Trích từ tài liệu và web, dùng được ngay không cần duyệt. Sửa dòng nào thì dòng đó được ưu tiên tuyệt đối."
    )
  );

  const slot = el("div");
  root.append(slot);

  async function reload() {
    slot.innerHTML = "";
    slot.append(loading("Đang tải bảng thuật ngữ…"));

    let terms;
    let statsData;
    try {
      [terms, statsData] = await Promise.all([
        api.listTerms(current.id),
        api.glossaryStats(current.id),
      ]);
    } catch (error) {
      slot.innerHTML = "";
      slot.append(note("error", error.message));
      return;
    }

    slot.innerHTML = "";
    slot.append(
      stats([
        ["Tổng thuật ngữ", fmtNum(statsData.total)],
        ["⭐⭐⭐ người dịch", fmtNum(statsData.human_translated)],
        ["Bạn đã sửa", fmtNum(statsData.expert_edited)],
        ["Có cách đọc", fmtNum(statsData.with_pronunciation)],
      ])
    );

    if (statsData.conflicts) {
      slot.append(
        el(
          "div",
          { style: "margin-top:16px" },
          note(
            "warn",
            `${statsData.conflicts} thuật ngữ có bản dịch xung đột — cuộn xuống để chọn bản chuẩn. ` +
              "Hệ thống không tự chọn hộ."
          )
        )
      );
    }

    if (!terms.length) {
      slot.append(
        empty(
          "Bảng thuật ngữ đang rỗng",
          "Chạy Nghiên cứu để trích thuật ngữ từ tài liệu và web, hoặc tự thêm tay bên dưới.",
          el("button.btn.btn-primary", {
            style: "margin-top:16px",
            type: "button",
            text: "Mở tab Nghiên cứu",
            onclick: () => router.go("research"),
          })
        ),
        el("div", { style: "margin-top:16px" }, addForm(current.id, reload))
      );
      return;
    }

    const search = el("input.input", { placeholder: "Tìm thuật ngữ…", style: "max-width:260px" });
    const catFilter = el(
      "select.select",
      { style: "width:auto" },
      el("option", { value: "", text: "Tất cả phân loại" }),
      (statsData.by_category ?? []).map((c) =>
        el("option", { value: c.category, text: `${c.category} (${c.n})` })
      )
    );
    const count = el("span", { style: "font-size:var(--t-sm);color:var(--ink-3)" });
    const list = el("div.term-list");

    function draw() {
      const q = search.value.trim().toLowerCase();
      const cat = catFilter.value;
      const shown = terms.filter(
        (t) =>
          (!cat || t.category === cat) &&
          (!q ||
            t.term_vi.toLowerCase().includes(q) ||
            t.term_en.toLowerCase().includes(q) ||
            String(t.definition ?? "").toLowerCase().includes(q))
      );
      list.innerHTML = "";
      count.textContent = `${shown.length}/${terms.length} thuật ngữ`;
      if (!shown.length) {
        list.append(
          el("div", {
            style: "padding:24px;text-align:center;color:var(--ink-3)",
            text: "Không có thuật ngữ nào khớp.",
          })
        );
        return;
      }
      for (const term of shown) list.append(termRow(term, reload));
    }

    search.addEventListener("input", draw);
    catFilter.addEventListener("change", draw);

    slot.append(
      el(
        "div.row-between",
        { style: "margin-top:24px;margin-bottom:12px" },
        el("div.btn-row", null, search, catFilter, count),
        el("a.btn.btn-sm", {
          href: api.glossaryExportUrl(current.id),
          download: "",
          text: "Xuất CSV",
          title: "Mang đi buổi dịch thật. Mở bằng Excel giữ đúng chữ tiếng Việt có dấu.",
        })
      ),
      list,
      el("div", { style: "margin-top:20px" }, addForm(current.id, reload))
    );

    draw();
  }

  await reload();
}
