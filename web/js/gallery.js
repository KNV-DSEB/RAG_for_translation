/**
 * Trang mẫu thiết kế — dùng ĐÚNG các component thật trong ui.js, không phải bản dựng lại.
 *
 * Mục đích: cho chuyên gia soi hướng thiết kế trước khi dựng 9 màn hình. Sai hướng thì
 * sửa lúc còn rẻ. Nội dung lấy từ bộ tài liệu thật (LDSC × xã Thu Cúc) chứ không dùng
 * chữ giả — chữ giả làm thiết kế trông ổn hơn thực tế.
 */

import {
  el, frag, pageHead, stats, note, badge, card, spine, field, loading,
  toast, confirmDanger, consentDialog, empty,
} from "./ui.js";

const gal = document.getElementById("gal");

function section(title, why, ...body) {
  return el("section", null, el("h2", { text: title }), why && el("p.why", { text: why }), ...body);
}

/* ============================== Bảng màu ============================== */

const COLORS = [
  ["--ink", "Mực văn bản"],
  ["--paper", "Giấy — lạnh, cố ý không ngả kem"],
  ["--vi", "Phía tiếng Việt"],
  ["--en", "Phía tiếng Anh"],
  ["--flag", "Cần soát lại"],
  ["--ok", "Đạt"],
  ["--warn", "Lưu ý"],
  ["--line-2", "Đường kẻ đậm"],
];

const swatches = el(
  "div.swatches",
  null,
  COLORS.map(([token, label]) =>
    el(
      "div.sw",
      null,
      el("div.chip", { style: `background: var(${token})` }),
      el("div.meta", null, el("b", { text: label }), el("code", { text: token }))
    )
  )
);

/* ============================== Thang chữ ============================== */

const TYPE = [
  ["--t-display / 900", "Trợ lý phiên dịch", "font-size:var(--t-display);font-weight:900;letter-spacing:var(--tr-display)"],
  ["--t-h1 / 900", "Lễ tổng kết và bàn giao công trình", "font-size:var(--t-h1);font-weight:900;letter-spacing:var(--tr-head)"],
  ["--t-h2 / 700", "Hồ sơ khách hàng · xã Thu Cúc", "font-size:var(--t-h2);font-weight:700;letter-spacing:var(--tr-head)"],
  ["--t-body / 400", "Qua rà soát, xã còn 113 hộ đang ở nhà tạm, nhà dột nát, phần lớn là hộ nghèo và cận nghèo.", "font-size:var(--t-body)"],
  ["--t-sm / 500", "Phường Thuỵ Khuê — Đề nghị duyệt", "font-size:var(--t-sm);font-weight:500"],
  ["mono", "6.780.000.000 ₫ · 42s · 8/10 lượt · 7.8/10", "font-family:var(--font-mono);font-variant-numeric:tabular-nums"],
];

const typeScale = el(
  "div.card",
  null,
  TYPE.map(([tag, text, style]) =>
    el("div.type-row", null, el("span.tag", { text: tag }), el("div", { style, text }))
  )
);

/* ============================== Cái sống ============================== */

const spineTurn = spine({
  number: 3,
  left: {
    lang: "vi",
    who: "Ông Nguyễn Minh Hòa",
    role: "Phó Giám đốc Sở Ngoại vụ tỉnh Phú Thọ",
    text:
      "Báo cáo với ông Walker, dự án lần này có tổng giá trị tài trợ là 6.780.000.000 đồng, " +
      "một nguồn lực vô cùng quý báu đối với địa phương. Khoản viện trợ phi chính phủ nước " +
      "ngoài này đã giúp 113 hộ gia đình có nơi an cư lạc nghiệp.",
  },
  right: {
    lang: "en",
    who: "Mr. David Walker",
    role: "Humanitarian Specialist, Latter-Day Saint Charities",
    text:
      "Reporting to Mr. Walker, this project has a total funding value of 6,780,000,000 VND, " +
      "an extremely precious resource for the locality. This foreign non-governmental aid has " +
      "helped 113 households have a stable place to live.",
  },
});

const spineTerms = el(
  "div",
  null,
  [
    ["nhà tạm, nhà dột nát", "temporary and dilapidated houses", "người dịch", "ok"],
    ["Latter-Day Saint Charities", "Lát-tơ Đây Xây-nt Cha-ri-tis", "cách đọc", "warn"],
    ["nghiệm thu", "acceptance", "chuyên gia sửa", "ok"],
  ].map(([vi, en, tag, kind], i) =>
    el(
      "div",
      { style: i ? "margin-top:8px" : "" },
      spine({
        number: i + 1,
        compact: true,
        left: { lang: "vi", text: vi },
        right: { lang: "en", text: en, extra: el("div", { style: "margin-top:6px" }, badge(kind, tag)) },
      })
    )
  )
);

/* ============================== Nút ============================== */

const buttons = el(
  "div.card",
  null,
  el("div.btn-row", null,
    el("button.btn.btn-primary", { type: "button", text: "Sinh kịch bản" }),
    el("button.btn", { type: "button", text: "Nghe lại" }),
    el("button.btn.btn-ghost", { type: "button", text: "Bỏ qua lượt này" }),
    el("button.btn.btn-danger", { type: "button", text: "Xoá bản ghi âm" }),
    el("button.btn", { type: "button", text: "Đang tắt", disabled: true })
  ),
  el("p.why", { style: "margin:16px 0 0", text: "Bấm thử để cảm nhận scale(0.97) ở 140ms. Tab để thấy vòng focus." })
);

/* ============================== Điểm ============================== */

const scoreGrid = el(
  "div.score-grid",
  null,
  [
    ["Nghĩa", 8.0, "high"], ["Thuật ngữ", 5.0, "mid"],
    ["Đầy đủ", 3.0, "low"], ["Diễn đạt", 9.0, "high"],
  ].map(([k, v, level]) =>
    el("div.score-cell", { dataset: { level } }, el("div.v", { text: v.toFixed(1) }), el("div.k", { text: k }))
  ).concat([
    el("div.score-cell.is-total", null, el("div.v", { text: "6.3" }), el("div.k", { text: "Điểm lượt" })),
  ])
);

const verdicts = el(
  "div.card",
  null,
  el("div.card-title", { text: "Thuật ngữ trong lượt này" }),
  el("div.term-verdict.is-ok", null,
    el("span.mark", { text: "✓" }),
    el("span", null, el("b", { text: "viện trợ phi chính phủ nước ngoài" }), " → ",
      el("code", { text: "foreign non-governmental aid" }))),
  el("div.term-verdict.is-bad", null,
    el("span.mark", { text: "✕" }),
    el("span", null, el("b", { text: "nhà tạm, nhà dột nát" }), " → chuẩn ",
      el("code", { text: "temporary and dilapidated houses" }),
      el("span", { style: "color:var(--ink-3)", text: " · bạn bỏ sót" })))
);

/* ============================== Dựng trang ============================== */

gal.append(
  pageHead("MẪU THIẾT KẾ", "Hệ thiết kế", "Soi trước khi dựng 9 màn hình. Nội dung lấy từ bộ tài liệu thật, không dùng chữ giả."),

  section("⭐ Cái sống — signature",
    "Mọi khối song ngữ dựng thành cặp cột có một đường kẻ mảnh chạy dọc ở giữa, số lượt nằm trong máng giữa, nguồn trái → đích phải. Đường kẻ đó chính là việc phiên dịch: đi từ bên này sang bên kia. Nó mang thông tin thật chứ không trang trí.",
    spineTurn,
    el("h3", { style: "margin:24px 0 8px", text: "Bản gọn — dùng cho dòng thuật ngữ" }),
    spineTerms),

  section("Bảng màu",
    "Hai màu ngôn ngữ để mắt học được trục VI→EN, dùng kiềm chế: vạch 3px bên trái + nhãn, không tô nền. Giấy lạnh chứ không ngả kem — tránh đúng cái mặc định mà mọi giao diện AI sinh ra đều rơi vào.",
    swatches),

  section("Bộ chữ",
    "Be Vietnam Pro vẽ riêng cho dấu tiếng Việt — dùng nó là tuyên bố công cụ này lấy tiếng Việt làm gốc. JetBrains Mono cho số. Đúng hai họ chữ, không dùng serif làm tiêu đề.",
    typeScale),

  section("Nút", null, buttons),

  section("Chấm điểm", "Màu theo mức điểm, số dùng chữ mono căn cột dọc để so sánh bằng mắt được.",
    scoreGrid, verdicts),

  section("Số liệu & nhãn", null,
    stats([["Tài liệu", 3], ["Thuật ngữ", 22], ["Buổi mock", 1], ["Nhận định", 3]]),
    el("div.card", { style: "margin-top:12px" },
      el("div.btn-row", null,
        badge("vi", "TIẾNG VIỆT"), badge("en", "TIẾNG ANH"),
        badge("ok", "⭐⭐⭐ người thật dịch"), badge("warn", "⭐⭐ bạn đã chốt"),
        badge("mute", "⭐ AI sinh"), badge("flag", "🔒 MẬT"), badge("flag", "sai 3 lần")))),

  section("Thông báo", "Lỗi không xin lỗi, và không bao giờ mơ hồ về chuyện gì đã xảy ra.",
    note("ok", "Đã lưu nhận định. Từ buổi sau, hệ thống sẽ chấm theo cách bạn vừa chỉ ra."),
    note("warn", "Bản chữ có chứa số hoặc đơn vị tiền tệ. Mô hình nhận dạng hay viết sai số — soát lại trước khi chấm."),
    note("error", "Đã dùng hết lượt miễn phí của Gemini cho hôm nay. Phần việc đã hoàn thành vẫn được giữ nguyên."),
    note("secret", "Hồ sơ “Latter-Day Saint Charities” đang ở chế độ MẬT — mọi lần gửi dữ liệu ra ngoài đều phải được bạn đồng ý trước.")),

  section("Ô nhập", null,
    el("div.card", null,
      field("Tên khách hàng", el("input.input", { placeholder: "ví dụ: Latter-Day Saint Charities" }), null, true),
      field("Chủ đề buổi làm việc",
        el("textarea.textarea", { placeholder: "ví dụ: Lễ tổng kết và bàn giao công trình nhà ở cho 113 hộ" }),
        "Càng cụ thể thì kịch bản càng sát buổi thật.", true),
      el("label.check", null, el("input", { type: "checkbox" }),
        el("span", null, el("b", { text: "Hồ sơ mật" }),
          el("div", { style: "font-size:var(--t-xs);color:var(--ink-3)", text: "Hiện trước nội dung sẽ gửi và chờ bạn đồng ý." }))))),

  section("Đang chạy", null,
    el("div.card", null,
      loading("Đang sinh kịch bản… thường mất 30–60 giây."),
      el("div.progress", { style: "margin:12px 0" }, el("i", { style: "width:62%" })),
      el("div.mock-progress", null,
        [1,2,3,4,5,6,7,8].map((n) =>
          el("i", { dataset: { state: n < 4 ? "done" : n === 4 ? "now" : "" } }))),
      el("div.steps", { style: "margin-top:12px" },
        "⏳ Lập kế hoạch tìm kiếm … 6 truy vấn\n" +
        "✅ [1/6] \"Latter-Day Saint Charities Vietnam\" … 8 kết quả\n" +
        "✅ [2/6] \"LDSC Phú Thọ viện trợ\" … 5 kết quả\n" +
        "⏳ Tổng hợp hồ sơ …"))),

  section("Hộp thoại", "Bấm để xem thật — cả hai đều là component dùng trong app.",
    el("div.btn-row", null,
      el("button.btn.btn-danger", { type: "button", text: "Thử hộp thoại xoá",
        onclick: () => confirmDanger({
          title: "Xoá bản ghi âm của buổi này?",
          body: "Sẽ xoá vĩnh viễn 8 bản ghi âm (12,4 MB) của buổi mock #1.",
          detail: "Điểm đã chấm và bản chữ vẫn được giữ nguyên.",
          confirmLabel: "Xoá 8 bản ghi",
        }).then((v) => toast(v ? "ok" : "warn", v ? "Đã xoá 8 bản ghi âm." : "Đã huỷ, không xoá gì.")) }),
        // Thao tác MỘT lệnh gọi: biết trước nội dung nên hiện đủ, không cắt.
        el("button.btn", { type: "button", text: "Cổng đồng ý — biết trước nội dung",
          onclick: () => consentDialog({
            workspace_name: "Latter-Day Saint Charities",
            operation_kind: "simulate.score",
            declares: [{ provider_label: "Gemini (Google)", destination_label: "mô hình ngôn ngữ",
                         unit_calls: 1, max_calls: 15 }],
            scope_note:
              "Thao tác này sẽ gửi dữ liệu ra ngoài: tối đa 1 lần tới Gemini (Google) " +
              "(gửi lại cùng nội dung đó tối đa 14 lần nếu nhà cung cấp bận hoặc hết hạn mức, " +
              "nên trần kỹ thuật là 15 lượt).",
            payload_known: true, n_chars: 3462,
            payload_excerpt:
                "CHIỀU DỊCH: tiếng Việt → tiếng Anh\n\n=== LỜI NGƯỜI NÓI ===\n" +
                "Báo cáo với ông Walker, dự án lần này có tổng giá trị tài trợ là 6.780.000.000 đồng…\n\n" +
                "=== BẢN DỊCH CỦA CHUYÊN GIA ===\nReporting to Mr. Walker, this project has…",
          }).then((v) => toast(v ? "ok" : "warn",
            v ? `Đã cho phép (${v}).` : "Đã từ chối — không gửi gì.")) }),
        // Thao tác NHIỀU lệnh gọi: chưa biết nội dung, phải nói thẳng thay vì hiện khung rỗng.
        el("button.btn", { type: "button", text: "Cổng đồng ý — chưa biết trước nội dung",
          onclick: () => consentDialog({
            workspace_name: "Latter-Day Saint Charities",
            operation_kind: "research.run",
            declares: [
              { provider_label: "DuckDuckGo", destination_label: "tìm kiếm web",
                unit_calls: 8, max_calls: 24 },
              { provider_label: "Gemini (Google)", destination_label: "mô hình ngôn ngữ",
                unit_calls: 5, max_calls: 75 },
            ],
            scope_note:
              "Thao tác này sẽ gửi dữ liệu ra ngoài: tối đa 8 lần tới DuckDuckGo, tối đa 5 lần " +
              "tới Gemini (Google). Nội dung từng lần do các bước bên trong sinh ra nên chưa " +
              "hiện được ở đây — mọi lần gửi đều được ghi vào Nhật ký Bảo mật để bạn soi lại.",
            payload_known: false, n_chars: 0, payload_excerpt: "",
          }).then((v) => toast(v ? "ok" : "warn",
            v ? `Đã cho phép (${v}).` : "Đã từ chối — không gửi gì.")) }),
      el("button.btn", { type: "button", text: "Thử toast", onclick: () => toast("ok", "Đã lưu.") }))),

  section("Trạng thái rỗng", "Màn hình rỗng là lời mời hành động, không phải chỗ báo lỗi.",
    empty("Chưa có buổi mock nào",
      "Sinh kịch bản 8–10 lượt từ hồ sơ khách hàng và bảng thuật ngữ, rồi luyện dịch hai chiều.",
      el("button.btn.btn-primary", { style: "margin-top:16px", type: "button", text: "Sinh kịch bản đầu tiên" })))
);
