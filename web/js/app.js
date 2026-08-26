/**
 * Điểm vào của giao diện: dựng rail trái, đăng ký màn hình, khởi động router.
 *
 * Vào:  không.
 * Ra:   gắn giao diện vào #rail và #screen.
 */

import * as api from "./api.js";
import * as store from "./store.js";
import * as router from "./router.js";
import { el, consentDialog, fail, note } from "./ui.js";

/* Đăng ký màn hình. Thêm màn mới chỉ sửa đúng chỗ này. */
import * as dashboard from "./screens/dashboard.js";
import * as documents from "./screens/documents.js";
import * as research from "./screens/research.js";
import * as glossary from "./screens/glossary.js";
import * as mock from "./screens/mock.js";
import * as calibration from "./screens/calibration.js";
import * as history from "./screens/history.js";
import * as security from "./screens/security.js";
import * as storage from "./screens/storage.js";

const NAV = [
  { group: "Chuẩn bị" },
  { key: "dashboard", icon: "◈", label: "Bảng điều khiển", screen: dashboard },
  { key: "documents", icon: "▤", label: "Tài liệu", screen: documents, count: "n_documents" },
  { key: "research", icon: "◎", label: "Nghiên cứu", screen: research },
  { key: "glossary", icon: "⇄", label: "Thuật ngữ", screen: glossary, count: "n_terms" },

  { group: "Luyện tập" },
  { key: "mock", icon: "◑", label: "Buổi mock", screen: mock, count: "n_sessions" },
  { key: "calibration", icon: "◐", label: "Hiệu chỉnh", screen: calibration },
  { key: "history", icon: "◔", label: "Lịch sử", screen: history },

  { group: "Hệ thống" },
  { key: "security", icon: "⛨", label: "Bảo mật", screen: security },
  { key: "storage", icon: "▣", label: "Dung lượng", screen: storage },
];

for (const item of NAV) {
  if (item.key) router.register(item.key, item.screen);
}

/* ============================== Rail trái ============================== */

function buildRail() {
  const rail = document.getElementById("rail");
  const state = store.get();
  const current = store.currentWorkspace();
  rail.innerHTML = "";

  rail.append(
    el(
      "div.rail-brand",
      null,
      el("span.mark", { text: "Phiên dịch" }),
      el("span.axis", { text: "VI→EN" })
    )
  );

  // Bộ chọn hồ sơ ghim trên cùng: mọi màn hình đều thuộc về một hồ sơ khách hàng
  if (state.workspaces.length) {
    const select = el("select.select.ws-select", {
      "aria-label": "Hồ sơ khách hàng",
      onchange: (event) => {
        store.setWorkspace(event.target.value);
        router.render();
      },
    });
    for (const ws of state.workspaces) {
      select.append(
        el("option", {
          value: String(ws.id),
          text: ws.is_confidential ? `🔒 ${ws.name}` : ws.name,
          selected: ws.id === state.workspaceId,
        })
      );
    }
    rail.append(select);
  }

  for (const item of NAV) {
    if (item.group) {
      rail.append(el("div.rail-section", { text: item.group }));
      continue;
    }
    const active = router.current() === item.key;
    const countValue = item.count && current ? current[item.count] : null;
    rail.append(
      el(
        "button.rail-link",
        {
          type: "button",
          "aria-current": active ? "page" : null,
          onclick: () => router.go(item.key),
        },
        el("span.ico", { text: item.icon, "aria-hidden": "true" }),
        el("span", { text: item.label }),
        countValue ? el("span.count", { text: String(countValue) }) : null
      )
    );
  }

  rail.append(
    el(
      "div.rail-foot",
      null,
      el("div", { text: "Chạy trên máy này." }),
      el("div", { text: "Ba đường dữ liệu ra ngoài, đều ghi nhật ký." })
    )
  );
}

/* ============================== Khởi động ============================== */

function applyChrome(key, params) {
  // Màn Mock chạy toàn khung để không còn gì phân tán khi đang luyện.
  //
  // Nhưng CHỈ khi đang thật sự trong một buổi (`?session=…`). Ở màn cấu hình thì chuyên
  // gia mới đang điền biểu mẫu, chưa chịu áp lực gì — mà rail bị ẩn ở đó lại tạo ngõ cụt:
  // nút “← Thoát” chỉ có trong buổi đang chạy và trong báo cáo, nên vào Mock từ rail là
  // không còn đường ra nào ngoài nút back của trình duyệt.
  const inSession = key === "mock" && Boolean(params?.session);
  const app = document.getElementById("app");
  app.dataset.chrome = inSession ? "off" : "on";
}

function secretBanner() {
  const current = store.currentWorkspace();
  const main = document.getElementById("main");
  main.querySelector(".secret-banner")?.remove();
  if (!current?.is_confidential) return;
  const banner = note(
    "secret",
    `Hồ sơ “${current.name}” đang ở chế độ MẬT — dữ liệu chỉ được gửi ra ngoài trong ` +
        `phạm vi thao tác hoặc phiên mà bạn đã cho phép. Mọi lần gửi đều vào Nhật ký Bảo mật.`
  );
  banner.classList.add("secret-banner");
  main.querySelector(".content-inner")?.prepend(banner);
}

async function main() {
  // Cắm cổng đồng ý vào api.js — bắt 409 ở một chỗ duy nhất cho toàn ứng dụng
  api.setConsentHandler(async (preview) => {
    const agreed = await consentDialog(preview);
    if (!agreed) return false;
    await api.grantConsent(preview.workspace_id, "session");
    return true;
  });

  router.setContainer(document.getElementById("screen"));
  router.onRouteChange((key, _screen, params) => {
    applyChrome(key, params);
    buildRail();
    // Dải nhắc hồ sơ mật chạy sau khi màn hình vẽ xong
    setTimeout(secretBanner, 0);
  });

  store.subscribe(buildRail);

  try {
    await store.refreshWorkspaces();
  } catch (error) {
    document.getElementById("screen").innerHTML = "";
    document.getElementById("screen").append(
      el(
        "div.empty",
        null,
        el("h2", { text: "Không kết nối được máy chủ" }),
        el("p", { text: error?.message ?? String(error) })
      )
    );
    fail(error?.message ?? String(error));
    buildRail();
    return;
  }

  buildRail();
  router.start();
}

main();
