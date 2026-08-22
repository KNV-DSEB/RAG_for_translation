/**
 * Màn hình: Tài liệu — nạp tệp và hỏi đáp có trích dẫn nguồn.
 *
 * Vào:  hồ sơ khách hàng đang chọn.
 * Ra:   danh sách tài liệu, khối hỏi đáp, lịch sử hỏi đáp.
 *
 * Ba thứ không được làm rơi so với bản Streamlit:
 *   A1.3  mỗi câu trả lời phải có trích dẫn trỏ đúng tệp và đúng đoạn, bấm mở được
 *   A1.6  câu hỏi suy luận tách rõ phần có trong tài liệu và phần suy đoán
 *   A1.7  nhãn `song ngữ song song` phải hiện, và đổi tay được nếu máy nhận sai
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import {
  el, pageHead, note, loading, empty, toast, ok, fail, withBusy, confirmDanger,
  fmtBytes, fmtDate,
} from "../ui.js";

const LANG_LABEL = {
  vi: ["badge-vi", "tiếng Việt"],
  en: ["badge-en", "tiếng Anh"],
  parallel: ["badge-ok", "song ngữ song song"],
  mixed: ["badge-mute", "trộn hai thứ tiếng"],
  unknown: ["badge-mute", "chưa rõ ngôn ngữ"],
};

const STATUS_LABEL = {
  ready: ["badge-ok", "sẵn sàng"],
  pending: ["badge-mute", "chờ xử lý"],
  extracting: ["badge-warn", "đang đọc"],
  chunking: ["badge-warn", "đang phân đoạn"],
  indexing: ["badge-warn", "đang lập chỉ mục"],
  error: ["badge-flag", "lỗi"],
};

function labelBadge(map, key) {
  const [cls, text] = map[key] ?? ["badge-mute", String(key)];
  return el(`span.badge.${cls}`, { text });
}

/* ============================== Nạp tệp ============================== */

function uploadBox(workspaceId, reload) {
  const input = el("input", {
    type: "file",
    multiple: true,
    accept: ".pdf,.docx,.doc,.txt,.md",
    style: "display:none",
    onchange: () => send(input.files),
  });

  const drop = el(
    "div.drop",
    {
      ondragover: (event) => {
        event.preventDefault();
        drop.dataset.over = "1";
      },
      ondragleave: () => {
        drop.dataset.over = "0";
      },
      ondrop: (event) => {
        event.preventDefault();
        drop.dataset.over = "0";
        send(event.dataTransfer.files);
      },
    },
    el("div.big", { text: "Kéo tệp vào đây, hoặc chọn từ máy" }),
    el("div.small", { text: "Nhận PDF · DOCX · DOC (Word cũ) · TXT · MD" }),
    el("button.btn.btn-primary", {
      type: "button",
      style: "margin-top:16px",
      text: "Chọn tệp",
      onclick: () => input.click(),
    }),
    input
  );

  async function send(fileList) {
    const files = Array.from(fileList ?? []);
    if (!files.length) return;

    const busy = el(
      "div.loading-row",
      null,
      el("span.spinner"),
      el("span", {
        text: `Đang nạp ${files.length} tệp — đọc, phân đoạn rồi lập chỉ mục. Tệp .doc cũ mất thêm chút thời gian vì phải mở qua Word.`,
      })
    );
    drop.replaceWith(busy);

    try {
      const result = await api.uploadDocuments(workspaceId, files);
      if (result.n_ready) ok(`Đã nạp xong ${result.n_ready}/${result.n_total} tệp.`);
      // Một tệp lỗi KHÔNG làm hỏng cả lô (A1.9) — báo riêng từng tệp, nêu lý do cụ thể
      for (const item of result.results ?? []) {
        if (item.status !== "ready") {
          fail(`${item.filename}: ${item.error_message ?? "không nạp được"}`);
        }
      }
      await store.touchWorkspace(workspaceId);
      reload();
    } catch (error) {
      busy.replaceWith(drop);
      fail(error.message);
    }
  }

  return drop;
}

/* ============================== Danh sách tài liệu ============================== */

function showModal(...content) {
  const backdrop = el("div.modal-backdrop", {
    onclick: (event) => {
      if (event.target === backdrop) backdrop.remove();
    },
  });
  const close = () => backdrop.remove();
  backdrop.append(
    el(
      "div.modal",
      { role: "dialog", "aria-modal": "true" },
      ...content,
      el("div.modal-foot", null, el("button.btn", { type: "button", text: "Đóng", onclick: close }))
    )
  );
  document.body.append(backdrop);
  backdrop.querySelector("button")?.focus();
  const onKey = (event) => {
    if (event.key === "Escape") {
      close();
      document.removeEventListener("keydown", onKey);
    }
  };
  document.addEventListener("keydown", onKey);
}

function documentRow(doc, reload) {
  const actions = el(
    "div.btn-row",
    null,
    el("button.btn.btn-sm", {
      type: "button",
      text: "Xem trước",
      onclick: async (event) => {
        await withBusy(event.currentTarget, "…", async () => {
          const preview = await api.previewDocument(doc.id);
          showModal(
            el("h2", { text: doc.filename }),
            el("p.card-sub", {
              text:
                `${preview.showing}/${preview.total_chunks} đoạn · ` +
                `${doc.n_chars} ký tự · đọc bằng ${doc.extractor ?? "?"}`,
            }),
            doc.extraction_quality === "low" &&
              note(
                "warn",
                "Trích xuất chất lượng thấp — tệp .doc cũ đọc bằng lớp dự phòng. " +
                  "Soát kỹ nội dung dưới đây trước khi tin vào câu trả lời."
              ),
            el(
              "div.modal-body",
              null,
              (preview.chunks ?? []).map((chunk) =>
                el(
                  "div",
                  { style: "margin-bottom:14px" },
                  el("div", {
                    style: "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-4)",
                    text: `${chunk.locator ?? `đoạn ${chunk.chunk_index}`} · ${chunk.lang ?? "?"}`,
                  }),
                  el("div", { text: chunk.text })
                )
              )
            )
          );
        });
      },
    }),
    // Máy nhận sai ngôn ngữ thì phải sửa tay được; đổi nhãn thì trích thuật ngữ lại
    el(
      "select.select",
      {
        style: "width:auto;padding:.25rem .5rem;font-size:var(--t-xs)",
        "aria-label": `Ngôn ngữ của ${doc.filename}`,
        onchange: async (event) => {
          try {
            await api.setDocumentLanguage(doc.id, event.target.value);
            ok("Đã đổi nhãn ngôn ngữ. Lần trích thuật ngữ sau sẽ dùng nhãn mới.");
            reload();
          } catch (error) {
            fail(error.message);
          }
        },
      },
      ["vi", "en", "parallel", "mixed", "unknown"].map((value) =>
        el("option", { value, text: LANG_LABEL[value][1], selected: value === doc.language })
      )
    ),
    el("button.btn.btn-sm.btn-danger", {
      type: "button",
      text: "Xoá",
      onclick: async () => {
        const yes = await confirmDanger({
          title: `Xoá “${doc.filename}”?`,
          body:
            "Tệp và toàn bộ chỉ mục của nó sẽ bị xoá vĩnh viễn. Nội dung này sẽ không còn " +
            "xuất hiện trong bất kỳ câu trả lời nào sau đó.",
          confirmLabel: "Xoá tài liệu",
        });
        if (!yes) return;
        try {
          await api.deleteDocument(doc.id);
          ok("Đã xoá tài liệu.");
          await store.touchWorkspace();
          reload();
        } catch (error) {
          fail(error.message);
        }
      },
    })
  );

  return el(
    "div.doc-row",
    null,
    el(
      "div.grow",
      null,
      el("div.name", { text: doc.filename }),
      el(
        "div",
        { style: "display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:5px" },
        labelBadge(STATUS_LABEL, doc.status),
        labelBadge(LANG_LABEL, doc.language),
        doc.language_source === "manual" && el("span.badge.badge-mute", { text: "bạn đã đổi nhãn" }),
        doc.extraction_quality === "low" &&
          el("span.badge.badge-warn", { text: "trích xuất chất lượng thấp" }),
        el("span.meta", {
          text: `${String(doc.ext).toUpperCase()} · ${fmtBytes(doc.size_bytes)} · ${doc.n_chunks} đoạn`,
        })
      ),
      doc.error_message && el("div", { style: "margin-top:8px" }, note("error", doc.error_message))
    ),
    actions
  );
}

/* ============================== Hỏi đáp ============================== */

function citationChip(citation) {
  return el("button.citation", {
    type: "button",
    text: `${citation.filename} · ${citation.locator ?? ""}`.trim(),
    title: "Bấm để xem nguyên văn đoạn được trích",
    onclick: () =>
      showModal(
        el("h2", { text: citation.filename }),
        el("p.card-sub", { text: citation.locator ?? "" }),
        el("div.modal-body", null, el("div", { style: "white-space:pre-wrap", text: citation.snippet ?? "" }))
      ),
  });
}

const CONFIDENCE_NOTE = {
  low: "Câu trả lời dựa trên ngữ cảnh hạn chế — nên kiểm tra lại nguồn trước khi dùng.",
  medium: null,
  high: null,
};

function answerBlock(result) {
  const box = el("div.card", { style: "margin-top:8px" });

  // Không tìm thấy thì nói không tìm thấy, và mở đường sang tìm web (A1.4)
  if (result.found === false) {
    box.append(
      note("warn", result.answer),
      el("button.btn", {
        type: "button",
        style: "margin-top:8px",
        text: "Tìm trên web thay vì trong tài liệu",
        onclick: () => router.go("research"),
      })
    );
    return box;
  }

  const confNote = CONFIDENCE_NOTE[result.confidence];
  if (confNote) box.append(note("warn", confNote));
  for (const w of result.warnings ?? []) box.append(note("warn", w));

  box.append(el("div", { style: "white-space:pre-wrap", text: result.answer }));

  // Số liệu là thứ phiên dịch sai là hỏng — tách riêng cho dễ soát
  if ((result.key_figures ?? []).length) {
    box.append(
      el(
        "div",
        { style: "margin-top:12px;display:flex;gap:6px;flex-wrap:wrap;align-items:center" },
        el("span", { style: "font-size:var(--t-xs);color:var(--ink-3)", text: "Số liệu:" }),
        result.key_figures.map((figure) => el("span.badge.badge-vi", { text: figure }))
      )
    );
  }

  // Phần suy luận tách hẳn khỏi phần đọc được từ tài liệu (A1.6)
  if (result.inference) {
    box.append(
      el(
        "div",
        {
          style:
            "margin-top:14px;padding-top:12px;border-top:1px dashed var(--line-2)",
        },
        el(
          "div",
          { style: "margin-bottom:6px" },
          el("span.badge.badge-warn", { text: "suy luận — không đọc được trực tiếp từ tài liệu" })
        ),
        el("div.card-sub", { style: "white-space:pre-wrap", text: result.inference })
      )
    );
  }

  const citations = result.citations ?? [];
  if (citations.length) {
    box.append(
      el(
        "div",
        { style: "margin-top:14px;padding-top:12px;border-top:1px solid var(--line)" },
        el("div", {
          style: "font-size:var(--t-xs);color:var(--ink-3);margin-bottom:6px",
          text: `${citations.length} trích dẫn — bấm để xem nguyên văn`,
        }),
        el("div", null, citations.map(citationChip))
      )
    );
  } else {
    box.append(
      el(
        "div",
        { style: "margin-top:12px" },
        note("warn", "Câu trả lời này không có trích dẫn — hãy tự kiểm lại trong tài liệu.")
      )
    );
  }
  return box;
}

const SAMPLE_QUESTIONS = [
  "Tóm tắt thông tin về khách hàng",
  "Cho tôi thông tin về dự án",
  "Dự đoán nội dung sẽ trao đổi trong buổi nghiệm thu",
];

function askBlock(workspaceId, documents) {
  const input = el("textarea.textarea", {
    rows: 2,
    placeholder: "Hỏi bằng tiếng Việt hoặc tiếng Anh…",
  });
  const scope = el(
    "select.select",
    { style: "width:auto", "aria-label": "Phạm vi hỏi" },
    el("option", { value: "", text: "Toàn bộ hồ sơ" }),
    documents.filter((d) => d.status === "ready").map((d) =>
      el("option", { value: String(d.id), text: d.filename })
    )
  );
  const submit = el("button.btn.btn-primary", { type: "submit", text: "Hỏi" });
  const answers = el("div");

  async function ask(question) {
    input.value = question;
    await withBusy(submit, "Đang tra…", async () => {
      const result = await api.askDocuments({
        workspace_id: workspaceId,
        question,
        document_ids: scope.value ? [Number(scope.value)] : null,
      });
      answers.prepend(
        el(
          "div",
          { style: "margin-top:16px" },
          el("div", { style: "font-weight:600", text: question }),
          answerBlock(result)
        )
      );
      input.value = "";
    });
  }

  const form = el(
    "form.card",
    {
      onsubmit: (event) => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question) {
          toast("warn", "Chưa nhập câu hỏi.");
          return;
        }
        ask(question);
      },
    },
    el("div.card-title", { text: "Hỏi trên tài liệu" }),
    el("p.card-sub", {
      style: "margin-bottom:12px",
      text:
        "Câu trả lời luôn kèm trích dẫn trỏ về đúng tệp và đúng đoạn. " +
        "Không tìm thấy thì nói không tìm thấy, không suy diễn thành câu khẳng định.",
    }),
    input,
    el("div.btn-row", { style: "margin-top:12px" }, scope, submit),
    el(
      "div.btn-row",
      { style: "margin-top:12px" },
      el("span", { style: "font-size:var(--t-xs);color:var(--ink-3)", text: "Hỏi nhanh:" }),
      SAMPLE_QUESTIONS.map((q) =>
        el("button.btn.btn-sm.btn-ghost", { type: "button", text: q, onclick: () => ask(q) })
      )
    )
  );

  return el("div", null, form, answers);
}

/* ============================== Render ============================== */

export async function render(root) {
  const current = store.currentWorkspace();
  if (!current) {
    root.append(
      pageHead("CHUẨN BỊ", "Tài liệu", "Nạp tài liệu và hỏi đáp có trích dẫn nguồn"),
      empty("Chưa chọn hồ sơ khách hàng", "Tạo hoặc chọn một hồ sơ ở Bảng điều khiển trước.")
    );
    return;
  }

  root.append(
    pageHead(
      "CHUẨN BỊ",
      "Tài liệu",
      "Nạp tài liệu của buổi làm việc, rồi hỏi bằng tiếng Việt — câu trả lời luôn chỉ ra nguồn"
    )
  );

  const slot = el("div");
  root.append(slot);

  async function reload() {
    slot.innerHTML = "";
    slot.append(loading("Đang tải danh sách tài liệu…"));

    let documents;
    try {
      documents = await api.listDocuments(current.id);
    } catch (error) {
      slot.innerHTML = "";
      slot.append(note("error", error.message));
      return;
    }

    slot.innerHTML = "";
    slot.append(uploadBox(current.id, reload));

    if (documents.length) {
      slot.append(
        el("div.card", { style: "margin-top:16px;padding:0" }, documents.map((doc) => documentRow(doc, reload)))
      );

      const parallel = documents.filter((d) => d.language === "parallel");
      if (parallel.length) {
        slot.append(
          el(
            "div",
            { style: "margin-top:12px" },
            note(
              "ok",
              `${parallel.length} tài liệu song ngữ song song — nguồn thuật ngữ đáng tin nhất, vì cặp dịch ` +
                "do người thật làm. Cũng dùng làm bản dịch chuẩn ⭐⭐⭐ khi chấm điểm."
            )
          )
        );
      }
    } else {
      slot.append(
        el(
          "div",
          { style: "margin-top:16px" },
          note("warn", "Chưa có tài liệu nào. Nạp hợp đồng, biên bản hoặc bài phát biểu của buổi làm việc.")
        )
      );
    }

    if (documents.some((d) => d.status === "ready")) {
      slot.append(el("div.section", null, askBlock(current.id, documents)));

      try {
        const items = await api.qaHistory(current.id);
        if (items.length) {
          slot.append(
            el(
              "div.section",
              null,
              el("h2", { text: "Đã hỏi trước đó" }),
              el(
                "div.card",
                { style: "padding:0" },
                items.slice(0, 12).map((item) =>
                  el(
                    "div",
                    { style: "padding:12px 20px;border-bottom:1px solid var(--line)" },
                    el("div", { style: "font-weight:600;font-size:var(--t-sm)", text: item.question }),
                    el("div.card-sub", {
                      style: "margin-top:4px",
                      text:
                        String(item.answer ?? "").slice(0, 220) +
                        (String(item.answer ?? "").length > 220 ? "…" : ""),
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
        /* lịch sử hỏng không đáng chặn màn hình chính */
      }
    }
  }

  await reload();
}
