/**
 * Helper dựng DOM, toast, hộp thoại xác nhận, và cổng đồng ý hồ sơ mật.
 *
 * Vào:  lời gọi từ các màn hình.
 * Ra:   phần tử DOM, hoặc Promise cho hộp thoại.
 *
 * Dựng bằng `document.createElement` chứ không nối chuỗi HTML: nội dung ở đây là
 * tên khách hàng, lời thoại, thuật ngữ do người dùng nhập — nối chuỗi là mở đường
 * cho lỗi hiển thị và chèn thẻ ngoài ý muốn. `textContent` xử lý đúng mọi trường hợp.
 */

/** el("div.card", { onclick }, "chữ", elKhac) — bộ dựng DOM gọn. */
export function el(spec, props = null, ...children) {
  const [tagAndId, ...classes] = String(spec).split(".");
  const [tag, id] = tagAndId.split("#");
  const node = document.createElement(tag || "div");
  if (id) node.id = id;
  if (classes.length) node.className = classes.join(" ");

  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = [node.className, value].filter(Boolean).join(" ");
    else if (key === "html") node.innerHTML = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key in node && key !== "list") node[key] = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }

  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const frag = (...children) => {
  const f = document.createDocumentFragment();
  f.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return f;
};

/* ============================== Khối hay dùng ============================== */

export function pageHead(eyebrow, title, subtitle) {
  return el(
    "header.page-head",
    null,
    eyebrow && el("div.eyebrow", { text: eyebrow }),
    el("h1", { text: title }),
    subtitle && el("p", { text: subtitle })
  );
}

export function stats(items) {
  return el(
    "div.stats",
    null,
    items.map(([k, v]) => el("div.stat", null, el("div.v", { text: String(v) }), el("div.k", { text: k })))
  );
}

export function note(kind, text) {
  return el(`div.note.is-${kind}`, null, el("div", { text }));
}

export function badge(kind, text) {
  return el(`span.badge.badge-${kind}`, { text });
}

export function card(title, ...body) {
  return el("div.card", null, title && el("div.card-title", { text: title }), ...body);
}

export function loading(text = "Đang tải…") {
  return el("div.loading-row", null, el("span.spinner"), el("span", { text }));
}

export function empty(title, detail, action) {
  return el("div.empty", null, el("h2", { text: title }), el("p", { text: detail }), action);
}

export function field(labelText, control, hint, required = false) {
  return el(
    "label.field",
    null,
    el("span.label", null, labelText, required && el("span.req", { text: " *" })),
    control,
    hint && el("span.hint", { text: hint })
  );
}

/**
 * ⭐ CÁI SỐNG — khối song ngữ có đường kẻ dọc ở giữa.
 * Đây là signature của sản phẩm; mọi chỗ có hai ngôn ngữ đều dùng nó.
 */
export function spine({ number, left, right, compact = false }) {
  const side = (data, lang) =>
    el(
      `div.spine-side.is-${lang}`,
      null,
      el("div.spine-lang", { text: lang === "vi" ? "TIẾNG VIỆT" : "TIẾNG ANH" }),
      data.who && el("div.spine-who", { text: data.who }),
      data.role && el("div.spine-role", { text: data.role }),
      el(`div.spine-text${data.muted ? ".is-muted" : ""}`, { text: data.text ?? "" }),
      data.extra
    );

  return el(
    `div.spine${compact ? ".spine-row" : ""}`,
    null,
    side(left, left.lang ?? "vi"),
    el(
      "div.spine-gutter",
      null,
      number !== undefined && el("span.spine-no", { text: String(number).padStart(2, "0") }),
      el("span.spine-arrow", { text: "→", "aria-hidden": "true" })
    ),
    side(right, right.lang ?? "en")
  );
}

/* ============================== Toast ============================== */

let toastHost = null;

export function toast(kind, text, ms = 5000) {
  if (!toastHost) {
    toastHost = el("div.toasts", { "aria-live": "polite" });
    document.body.append(toastHost);
  }
  const node = el(
    `div.toast.is-${kind}`,
    { dataset: { enter: "0" } },
    el("div", { text }),
    el("button.close", { type: "button", "aria-label": "Đóng", text: "×", onclick: close })
  );
  toastHost.append(node);

  // Chạy sang frame sau để transition có trạng thái đầu mà chuyển
  requestAnimationFrame(() => {
    node.dataset.enter = "1";
  });

  const timer = setTimeout(close, ms);
  function close() {
    clearTimeout(timer);
    node.dataset.enter = "0";
    setTimeout(() => node.remove(), 200);
  }
  return close;
}

export const ok = (t) => toast("ok", t);
export const warn = (t) => toast("warn", t);
export const fail = (t) => toast("error", t, 9000);

/* ============================== Hộp thoại ============================== */

function openModal(build) {
  return new Promise((resolve) => {
    const backdrop = el("div.modal-backdrop", {
      onclick: (event) => {
        if (event.target === backdrop) done(false);
      },
    });
    const box = el("div.modal", { role: "dialog", "aria-modal": "true" });
    backdrop.append(box);

    function done(value) {
      document.removeEventListener("keydown", onKey);
      backdrop.remove();
      resolve(value);
    }
    function onKey(event) {
      if (event.key === "Escape") done(false);
    }

    build(box, done);
    document.addEventListener("keydown", onKey);
    document.body.append(backdrop);

    // Đưa focus vào hộp thoại để người dùng bàn phím không bị bỏ lại phía sau
    box.querySelector("button, input, textarea, select")?.focus();
  });
}

/** Xác nhận hai bước cho thao tác không hoàn tác được. */
export function confirmDanger({ title, body, confirmLabel = "Xác nhận", detail }) {
  return openModal((box, done) => {
    box.append(
      el("h2", { text: title }),
      el("div.modal-body", null, el("p", { text: body }), detail && note("warn", detail)),
      el(
        "div.modal-foot",
        null,
        el("button.btn", { type: "button", text: "Huỷ", onclick: () => done(false) }),
        el("button.btn.btn-danger", {
          type: "button",
          text: confirmLabel,
          onclick: () => done(true),
        })
      )
    );
  });
}

/**
 * Cổng đồng ý cho hồ sơ mật — hiện NGUYÊN VĂN nội dung sắp gửi ra ngoài.
 * Cắm vào api.js qua setConsentHandler.
 */
export function consentDialog(preview) {
  const destLabel =
    { llm: "gọi mô hình ngôn ngữ", search: "truy vấn tìm kiếm web", tts: "đọc lời thoại thành giọng nói" }[
      preview.destination
    ] ?? preview.destination;

  return openModal((box, done) => {
    box.append(
      el("h2", { text: "Cần bạn đồng ý trước khi gửi dữ liệu ra ngoài" }),
      note(
        "secret",
        `Hồ sơ “${preview.workspace_name}” đang ở chế độ mật. ` +
          `Thao tác này sẽ ${destLabel}.`
      ),
      el(
        "div.modal-body",
        null,
        el(
          "p",
          null,
          "Sẽ gửi ",
          el("b", { text: `${preview.n_chars} ký tự` }),
          " tới ",
          el("code", { text: preview.endpoint || preview.destination }),
          ` — từ mô-đun ${preview.module}.`
        ),
        el("p", { text: "Đây là chính xác nội dung sẽ rời khỏi máy này:" }),
        el("pre.payload", { text: preview.payload_excerpt ?? "" })
      ),
      el(
        "div.modal-foot",
        null,
        el("button.btn", { type: "button", text: "Không gửi", onclick: () => done(false) }),
        el("button.btn.btn-primary", {
          type: "button",
          text: "Đồng ý cho cả buổi làm việc",
          onclick: () => done(true),
        })
      )
    );
  });
}

/* ============================== Vặt ============================== */

export function fmtBytes(n) {
  const mb = Number(n) / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.round(Number(n) / 1024)} KB`;
}

export function fmtDate(value) {
  if (!value) return "";
  return String(value).slice(0, 16).replace("T", " ");
}

export function fmtNum(n) {
  return new Intl.NumberFormat("vi-VN").format(Number(n) || 0);
}

/** Bọc một thao tác async: khoá nút, hiện spinner, bắt lỗi thành toast. */
export async function withBusy(button, label, task) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "";
  button.append(el("span.spinner"), document.createTextNode(label));
  try {
    return await task();
  } catch (error) {
    fail(error?.message ?? String(error));
    return undefined;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}
