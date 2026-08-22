/**
 * Router theo hash, không cần thư viện.
 *
 * Vào:  bảng đăng ký màn hình { key: { title, icon, render } }.
 * Ra:   gọi render(container, params) khi hash đổi.
 *
 * Dùng hash chứ không dùng History API để mở thẳng `web/index.html` cũng chạy,
 * và backend không phải thêm route bắt-tất cho từng đường dẫn.
 * Dạng hash: #/mock?session=12
 */

const routes = new Map();
let container = null;
let currentKey = null;
let onChange = null;

export function register(key, screen) {
  routes.set(key, screen);
}

export function setContainer(element) {
  container = element;
}

export function onRouteChange(fn) {
  onChange = fn;
}

export function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, queryString] = raw.split("?");
  const params = Object.fromEntries(new URLSearchParams(queryString ?? ""));
  return { key: path || "dashboard", params };
}

export function go(key, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  ).toString();
  const next = `#/${key}${query ? `?${query}` : ""}`;
  if (window.location.hash === next) {
    render(); // cùng hash nhưng muốn vẽ lại
  } else {
    window.location.hash = next;
  }
}

export function current() {
  return currentKey;
}

export async function render() {
  if (!container) return;
  const { key, params } = parseHash();
  const screen = routes.get(key);

  if (!screen) {
    container.innerHTML = "";
    const box = document.createElement("div");
    box.className = "empty";
    box.innerHTML =
      "<h2>Không có màn hình này</h2>" +
      "<p>Đường dẫn không đúng. Quay lại Bảng điều khiển để tiếp tục.</p>";
    const back = document.createElement("button");
    back.className = "btn btn-primary";
    back.textContent = "Về Bảng điều khiển";
    back.addEventListener("click", () => go("dashboard"));
    box.append(back);
    container.append(box);
    return;
  }

  currentKey = key;
  if (onChange) onChange(key, screen, params);

  container.innerHTML = "";
  container.scrollTop = 0;
  window.scrollTo({ top: 0 });

  try {
    await screen.render(container, params);
  } catch (error) {
    container.innerHTML = "";
    const box = document.createElement("div");
    box.className = "empty";
    const title = document.createElement("h2");
    title.textContent = "Màn hình này gặp lỗi";
    const detail = document.createElement("p");
    // Lỗi từ api.js đã là tiếng Việt sẵn sàng hiển thị
    detail.textContent = error?.message ?? String(error);
    box.append(title, detail);
    container.append(box);
    console.error(error);
  }
}

export function start() {
  window.addEventListener("hashchange", render);
  if (!window.location.hash) window.location.hash = "#/dashboard";
  else render();
}
