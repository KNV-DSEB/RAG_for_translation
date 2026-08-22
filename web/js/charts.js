/**
 * Ba biểu đồ SVG tự vẽ, không phụ thuộc thư viện.
 *
 * Vào:  dữ liệu số + nhãn.
 * Ra:   phần tử <svg> dùng chung bảng màu và bộ chữ với phần còn lại của app.
 *
 * Vì sao không dùng Plotly: biểu đồ Plotly trông ra biểu đồ Plotly — đúng cái
 * "nhìn như template" cần tránh. Ba biểu đồ ở đây đều đơn giản (một đường, hai cột),
 * và tự vẽ thì màu/chữ/khoảng cách khớp hẳn với hệ thiết kế.
 *
 * Dùng viewBox + preserveAspectRatio để co giãn theo khung chứa mà không cần JS đo đạc.
 */

const NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  }
  return node;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Đường gấp khúc qua các điểm. Không làm mượt spline — số liệu ít điểm thì
 *  đường thẳng trung thực hơn, cong lên là bịa ra giá trị không có thật. */
function polyline(points) {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

/* ============================================================================
 * 1. Biểu đồ đường — tiến bộ qua các buổi mock
 * ========================================================================= */

/**
 * @param {object}   opts
 * @param {number[]} opts.main      điểm tổng, đường đậm
 * @param {object[]} opts.thin      [{label, values}] bốn tiêu chí, đường mảnh làm nền
 * @param {string[]} opts.xLabels   nhãn trục X
 */
export function lineChart({ main, thin = [], xLabels = [], yMax = 10, height = 220 }) {
  const W = 640;
  const H = height;
  const pad = { top: 12, right: 14, bottom: 26, left: 30 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const svg = svgEl("svg", {
    class: "chart",
    viewBox: `0 0 ${W} ${H}`,
    preserveAspectRatio: "xMidYMid meet",
    role: "img",
  });

  const n = main.length;
  const x = (i) => pad.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v) => pad.top + plotH - (Math.max(0, Math.min(yMax, v)) / yMax) * plotH;

  // Lưới ngang + nhãn trục Y
  for (const tick of [0, yMax / 2, yMax]) {
    const yy = y(tick);
    svg.append(
      svgEl("line", { class: "grid-line", x1: pad.left, x2: W - pad.right, y1: yy, y2: yy })
    );
    const label = svgEl("text", { x: pad.left - 6, y: yy + 3, "text-anchor": "end" });
    label.textContent = String(tick);
    svg.append(label);
  }

  // Bốn tiêu chí: mảnh, mờ, làm nền cho đường điểm tổng
  const thinColors = [cssVar("--vi"), cssVar("--en"), cssVar("--warn"), cssVar("--ink-3")];
  thin.forEach((series, index) => {
    const pts = series.values
      .map((v, i) => (v === null || v === undefined ? null : [x(i), y(v)]))
      .filter(Boolean);
    if (pts.length < 2) return;
    svg.append(
      svgEl("polyline", {
        points: polyline(pts),
        fill: "none",
        stroke: thinColors[index % thinColors.length],
        "stroke-width": 1.2,
        "stroke-dasharray": "3 3",
        opacity: 0.5,
      })
    );
  });

  // Đường điểm tổng
  const mainPts = main.map((v, i) => [x(i), y(v)]);
  if (mainPts.length >= 2) {
    svg.append(
      svgEl("polyline", {
        points: polyline(mainPts),
        fill: "none",
        stroke: cssVar("--vi"),
        "stroke-width": 2.5,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
      })
    );
  }
  mainPts.forEach(([px, py], i) => {
    const dot = svgEl("circle", {
      cx: px, cy: py, r: 4,
      fill: cssVar("--surface"),
      stroke: cssVar("--vi"),
      "stroke-width": 2.5,
    });
    const title = svgEl("title");
    title.textContent = `${xLabels[i] ?? `Buổi ${i + 1}`}: ${main[i].toFixed(1)}/10`;
    dot.append(title);
    svg.append(dot);
  });

  // Nhãn trục X — thưa bớt khi nhiều điểm để chữ không chồng nhau
  const step = Math.ceil(n / 8);
  xLabels.forEach((text, i) => {
    if (i % step !== 0 && i !== n - 1) return;
    const label = svgEl("text", { x: x(i), y: H - 8, "text-anchor": "middle" });
    label.textContent = text;
    svg.append(label);
  });

  return svg;
}

/* ============================================================================
 * 2. Biểu đồ cột — điểm theo tiêu chí (thang 10 cố định)
 * ========================================================================= */

export function barChart({ items, max = 10, height = 200 }) {
  const W = 640;
  const H = height;
  const pad = { top: 18, right: 12, bottom: 34, left: 30 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const svg = svgEl("svg", {
    class: "chart",
    viewBox: `0 0 ${W} ${H}`,
    preserveAspectRatio: "xMidYMid meet",
    role: "img",
  });

  for (const tick of [0, max / 2, max]) {
    const yy = pad.top + plotH - (tick / max) * plotH;
    svg.append(svgEl("line", { class: "grid-line", x1: pad.left, x2: W - pad.right, y1: yy, y2: yy }));
    const label = svgEl("text", { x: pad.left - 6, y: yy + 3, "text-anchor": "end" });
    label.textContent = String(tick);
    svg.append(label);
  }

  const slot = plotW / items.length;
  const barW = Math.min(58, slot * 0.52);

  items.forEach((item, i) => {
    const value = Number(item.value) || 0;
    const h = (value / max) * plotH;
    const cx = pad.left + slot * (i + 0.5);
    // Màu theo mức điểm: dưới 5 là cần soát, 5–7.5 lưu ý, trên 7.5 đạt
    const color = value < 5 ? cssVar("--flag") : value < 7.5 ? cssVar("--warn") : cssVar("--ok");

    svg.append(
      svgEl("rect", {
        x: cx - barW / 2, y: pad.top + plotH - h,
        width: barW, height: Math.max(2, h),
        rx: 4, fill: color, opacity: 0.9,
      })
    );

    const value_label = svgEl("text", {
      x: cx, y: pad.top + plotH - h - 6, "text-anchor": "middle",
      fill: cssVar("--ink-2"), "font-weight": "500",
    });
    value_label.textContent = value.toFixed(1);
    svg.append(value_label);

    const name = svgEl("text", { x: cx, y: H - 10, "text-anchor": "middle" });
    name.textContent = item.label;
    svg.append(name);
  });

  return svg;
}

/* ============================================================================
 * 3. Biểu đồ cột hai chiều — độ lệch điểm AI vs chuyên gia
 * ========================================================================= */

export function divergingBarChart({ items, height = 220 }) {
  const W = 640;
  const H = height;
  const pad = { top: 16, right: 12, bottom: 34, left: 34 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const svg = svgEl("svg", {
    class: "chart",
    viewBox: `0 0 ${W} ${H}`,
    preserveAspectRatio: "xMidYMid meet",
    role: "img",
  });

  const bound = Math.max(1, ...items.map((it) => Math.abs(Number(it.value) || 0))) * 1.15;
  const zeroY = pad.top + plotH / 2;
  const scale = (v) => (v / bound) * (plotH / 2);

  for (const tick of [bound, 0, -bound]) {
    const yy = zeroY - scale(tick);
    const isZero = tick === 0;
    svg.append(
      svgEl("line", {
        class: isZero ? "axis-line" : "grid-line",
        x1: pad.left, x2: W - pad.right, y1: yy, y2: yy,
        "stroke-width": isZero ? 1.4 : 1,
      })
    );
    const label = svgEl("text", { x: pad.left - 6, y: yy + 3, "text-anchor": "end" });
    label.textContent = tick === 0 ? "0" : `${tick > 0 ? "+" : ""}${tick.toFixed(1)}`;
    svg.append(label);
  }

  const slot = plotW / items.length;
  const barW = Math.min(58, slot * 0.5);

  items.forEach((item, i) => {
    const value = Number(item.value) || 0;
    const h = Math.abs(scale(value));
    const cx = pad.left + slot * (i + 0.5);
    // Dương = bạn chấm cao hơn AI (AI khắt khe). Âm = AI dễ dãi hơn bạn.
    const color = value >= 0 ? cssVar("--ok") : cssVar("--flag");

    svg.append(
      svgEl("rect", {
        x: cx - barW / 2,
        y: value >= 0 ? zeroY - h : zeroY,
        width: barW, height: Math.max(2, h),
        rx: 3, fill: color, opacity: 0.88,
      })
    );

    const value_label = svgEl("text", {
      x: cx,
      y: value >= 0 ? zeroY - h - 6 : zeroY + h + 12,
      "text-anchor": "middle", fill: cssVar("--ink-2"), "font-weight": "500",
    });
    value_label.textContent = `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
    svg.append(value_label);

    const name = svgEl("text", { x: cx, y: H - 10, "text-anchor": "middle" });
    name.textContent = item.label;
    svg.append(name);
  });

  return svg;
}

/** Chú giải dùng chung cho biểu đồ đường. */
export function legend(entries) {
  const box = document.createElement("div");
  box.className = "chart-legend";
  for (const [label, color, dashed] of entries) {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.background = color;
    if (dashed) swatch.style.opacity = "0.5";
    item.append(swatch, document.createTextNode(label));
    box.append(item);
  }
  return box;
}
