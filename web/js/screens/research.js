/**
 * Màn hình: Nghiên cứu — dựng hồ sơ khách hàng/đối tác có nguồn trích dẫn.
 *
 * Vào:  tên khách hàng, tên đối tác, chủ đề buổi làm việc.
 * Ra:   hồ sơ từng bên, mỗi TRƯỜNG kèm URL nguồn riêng; kèm thống kê thuật ngữ trích được.
 *
 * Ba thứ không được làm rơi:
 *   A2.4   mỗi thông tin có ít nhất một URL nguồn, bấm mở được
 *   A2.5   thông tin không xác minh được đánh dấu rõ, TÁCH khỏi thông tin có nguồn
 *   A2.12  sửa tay một trường thì lần nghiên cứu sau không ghi đè
 */

import * as api from "../api.js";
import * as store from "../store.js";
import * as router from "../router.js";
import {
  el, pageHead, stats, note, loading, empty, toast, ok, withBusy, field, fmtNum, fmtDate,
} from "../ui.js";

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return String(url).slice(0, 40);
  }
}

/* ============================== Một trường hồ sơ ============================== */

function profileField(item, reload) {
  const box = el("div", { style: "padding:14px 0;border-bottom:1px solid var(--line)" });

  const value = el("div", {
    style: "white-space:pre-wrap;font-size:var(--t-sm)",
    text: item.value ?? "",
  });

  const edit = el("button.btn.btn-sm.btn-ghost", {
    type: "button",
    text: "Sửa",
    onclick: () => {
      const input = el("textarea.textarea", { rows: 3, value: item.value ?? "" });
      const save = el("button.btn.btn-sm.btn-primary", { type: "submit", text: "Lưu" });
      const form = el(
        "form",
        {
          style: "margin-top:8px",
          onsubmit: async (event) => {
            event.preventDefault();
            await withBusy(save, "…", async () => {
              await api.editProfileField(item.id, input.value.trim());
              ok("Đã lưu. Lần nghiên cứu sau sẽ không ghi đè trường này.");
              reload();
            });
          },
        },
        input,
        el(
          "div.btn-row",
          { style: "margin-top:8px" },
          save,
          el("button.btn.btn-sm", { type: "button", text: "Huỷ", onclick: () => reload() })
        )
      );
      value.replaceWith(form);
      edit.remove();
    },
  });

  box.append(
    el(
      "div",
      { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px" },
      el("span", {
        style: "font-size:var(--t-xs);font-weight:700;color:var(--ink-3)",
        text: item.label,
      }),
      // Không có nguồn thì phải nói rõ, không trộn lẫn với thông tin đã xác minh (A2.5)
      item.has_source
        ? el("span.badge.badge-ok", { text: "có nguồn" })
        : el("span.badge.badge-warn", { text: "chưa xác minh" }),
      item.is_expert_edited && el("span.badge.badge-ok", { text: "bạn đã sửa" }),
      el("div", { style: "margin-left:auto" }, edit)
    ),
    value
  );

  const sources = item.sources ?? [];
  if (sources.length) {
    box.append(
      el(
        "div",
        { style: "margin-top:8px;display:flex;gap:6px;flex-wrap:wrap" },
        // KHÔNG còn nhãn "liên kết hỏng" / "chặn truy cập".
        //
        // Chúng đến từ `check_urls_reachable()` — một đường mạng đi vòng qua cửa egress,
        // đã bị xoá. Giữ phần hiển thị lại thì hai điều cùng sai: dữ liệu cũ đóng băng
        // vĩnh viễn (không gì cập nhật nó nữa), và bản thân phép đo vốn đã hay sai —
        // Wikipedia, thuvienphapluat.vn trả 403 cho máy nhưng mở bằng trình duyệt vẫn
        // bình thường. Gắn nhãn "chết" cho nguồn tốt làm chuyên gia mất tin vào nguồn đúng.
        sources.map((source) =>
          el("a.citation", {
            href: source.url,
            target: "_blank",
            rel: "noopener noreferrer",
            title: source.title || source.url,
            text:
              hostOf(source.url) +
              (source.published_at ? ` · ${String(source.published_at).slice(0, 10)}` : ""),
          })
        )
      )
    );
  } else if (!item.has_source) {
    box.append(
      el("div", {
        style: "margin-top:6px;font-size:var(--t-xs);color:var(--warn)",
        text: "Không có nguồn — đây là suy luận của máy, tự kiểm lại trước khi dùng.",
      })
    );
  }

  return box;
}

function profileCard(profile, reload) {
  return el(
    "div.card",
    { style: "margin-bottom:16px" },
    el(
      "div",
      { style: "display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px" },
      el("h3", { text: profile.entity_name }),
      el(`span.badge.${profile.entity_role === "client" ? "badge-vi" : "badge-en"}`, {
        text: profile.entity_role === "client" ? "khách hàng" : "đối tác",
      }),
      el("span", {
        style:
          "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-4);margin-left:auto",
        text: fmtDate(profile.created_at),
      })
    ),
    (profile.fields ?? []).map((item) => profileField(item, reload))
  );
}

/* ============================== Chạy nghiên cứu ============================== */

function runForm(workspace, reload) {
  const clientName = el("input.input", { value: workspace.name });
  const partners = el("input.input", { placeholder: "UBND xã Thu Cúc, Sở Ngoại vụ tỉnh Phú Thọ" });
  const topic = el("textarea.textarea", {
    rows: 2,
    placeholder: "ví dụ: Lễ tổng kết và bàn giao công trình nhà ở cho 113 hộ khó khăn tại xã Thu Cúc",
  });
  const industry = el("input.input", { value: workspace.industry ?? "" });
  const extra = el("input.input", { placeholder: "website, quốc gia, thông tin bạn đã biết" });
  const submit = el("button.btn.btn-primary", { type: "submit", text: "Bắt đầu nghiên cứu" });
  const progress = el("div");

  return el(
    "form.card",
    {
      onsubmit: async (event) => {
        event.preventDefault();
        if (!topic.value.trim()) {
          toast("warn", "Cần nhập chủ đề buổi làm việc.");
          return;
        }
        progress.innerHTML = "";
        progress.append(
          el(
            "div.loading-row",
            { style: "margin-top:16px" },
            el("span.spinner"),
            el("span", {
              text: "Đang lập kế hoạch truy vấn, tìm kiếm, rồi tổng hợp… thường mất 1–3 phút.",
            })
          )
        );

        await withBusy(submit, "Đang nghiên cứu…", async () => {
          const result = await api.runResearch({
            workspace_id: workspace.id,
            client_name: clientName.value.trim(),
            topic: topic.value.trim(),
            partner_names: partners.value.split(",").map((s) => s.trim()).filter(Boolean),
            industry: industry.value.trim() || null,
            extra_notes: extra.value.trim() || null,
          });

          progress.innerHTML = "";
          progress.append(
            el(
              "div",
              { style: "margin-top:16px" },
              stats([
                ["Truy vấn đã dùng", `${result.n_queries}/8`],
                ["Nguồn thu được", fmtNum(result.n_sources)],
                ["Thuật ngữ", fmtNum(result.n_terms_total)],
                ["⭐⭐⭐ người dịch", fmtNum(result.n_terms_human)],
              ]),
              result.ambiguity_warning &&
                el("div", { style: "margin-top:12px" },
                  note("warn", `Tên tổ chức nhập nhằng — bạn chọn: ${result.ambiguity_warning}`)),
              ...(result.not_found_notes ?? []).map((t) =>
                el("div", { style: "margin-top:8px" }, note("warn", t))),
              ...(result.warnings ?? []).map((t) =>
                el("div", { style: "margin-top:8px" }, note("warn", t))),
              el(
                "details",
                { style: "margin-top:12px" },
                el("summary", {
                  style: "cursor:pointer;font-size:var(--t-sm)",
                  text: `Xem ${(result.steps ?? []).length} bước đã chạy và ${result.n_queries} truy vấn đã gửi ra ngoài`,
                }),
                el("div.steps", { style: "margin-top:8px", text: (result.steps ?? []).join("\n") }),
                el(
                  "div",
                  { style: "margin-top:8px;font-size:var(--t-xs);color:var(--ink-3)" },
                  el("b", { text: "Truy vấn đã gửi: " }),
                  (result.queries_used ?? []).join("  ·  ")
                )
              )
            )
          );

          ok(`Xong: ${result.n_sources} nguồn, ${result.n_terms_total} thuật ngữ.`);
          await store.touchWorkspace(workspace.id);
        });
      },
    },
    el("div.card-title", { text: "Chạy nghiên cứu" }),
    el("p.card-sub", {
      style: "margin-bottom:16px",
      text:
        "Agent lập kế hoạch, chạy tối đa 8 truy vấn tìm kiếm, rồi tổng hợp hồ sơ và trích thuật ngữ " +
        "từ cả tài liệu lẫn web. Mọi truy vấn gửi đi đều hiện ra để bạn kiểm.",
    }),
    field("Tên khách hàng", clientName, null, true),
    field("Tên đối tác", partners, "Cách nhau bằng dấu phẩy. Bên còn lại trong buổi dịch."),
    field("Chủ đề buổi làm việc", topic, "Càng cụ thể thì hồ sơ và thuật ngữ càng sát.", true),
    field("Ngành nghề / lĩnh vực", industry, "Không bắt buộc. Giúp thu hẹp tìm kiếm."),
    field("Ghi chú thêm", extra),
    submit,
    progress
  );
}

/* ============================== Render ============================== */

export async function render(root) {
  const current = store.currentWorkspace();
  if (!current) {
    root.append(
      pageHead("CHUẨN BỊ", "Nghiên cứu", "Dựng hồ sơ khách hàng và bảng thuật ngữ song ngữ"),
      empty("Chưa chọn hồ sơ khách hàng", "Tạo hoặc chọn một hồ sơ ở Bảng điều khiển trước.")
    );
    return;
  }

  root.append(
    pageHead(
      "CHUẨN BỊ",
      "Nghiên cứu",
      "Từ vài cái tên, dựng hồ sơ các bên có nguồn trích dẫn và bảng thuật ngữ tái dùng được"
    )
  );

  const slot = el("div");
  root.append(slot);

  async function reload() {
    slot.innerHTML = "";
    slot.append(loading("Đang tải hồ sơ đã dựng…"));

    let profiles;
    let runs;
    try {
      [profiles, runs] = await Promise.all([
        api.getProfiles(current.id),
        api.researchRuns(current.id).catch(() => []),
      ]);
    } catch (error) {
      slot.innerHTML = "";
      slot.append(note("error", error.message));
      return;
    }

    slot.innerHTML = "";

    if (profiles.length) {
      const nVerified = profiles.reduce(
        (sum, p) => sum + p.fields.filter((f) => f.has_source).length,
        0
      );
      const nTotal = profiles.reduce((sum, p) => sum + p.fields.length, 0);

      slot.append(
        stats([
          ["Hồ sơ đã dựng", profiles.length],
          ["Trường có nguồn", `${nVerified}/${nTotal}`],
          ["Lần nghiên cứu", runs.length],
        ]),
        el(
          "div.section",
          null,
          el("h2", { text: "Hồ sơ các bên" }),
          profiles.map((p) => profileCard(p, reload))
        ),
        el(
          "div.btn-row",
          null,
          el("button.btn", {
            type: "button",
            text: "Xem bảng thuật ngữ",
            onclick: () => router.go("glossary"),
          }),
          el("button.btn.btn-primary", {
            type: "button",
            text: "Tạo buổi mock từ hồ sơ này",
            onclick: () => router.go("mock"),
          })
        )
      );
    } else {
      slot.append(
        empty(
          "Chưa có hồ sơ nào",
          "Nhập tên khách hàng, đối tác và chủ đề buổi làm việc bên dưới. Agent sẽ tìm và tổng hợp, mỗi thông tin đều kèm nguồn để bạn kiểm lại."
        )
      );
    }

    slot.append(el("div.section", null, runForm(current, reload)));

    if (runs.length) {
      slot.append(
        el(
          "div.section",
          null,
          el("h2", { text: "Các lần nghiên cứu trước" }),
          el(
            "div.card",
            { style: "padding:0" },
            runs.slice(0, 8).map((run) =>
              el(
                "div",
                { style: "padding:12px 20px;border-bottom:1px solid var(--line)" },
                el("div", { style: "font-weight:600;font-size:var(--t-sm)", text: run.topic }),
                el("div", {
                  style:
                    "font-family:var(--font-mono);font-size:var(--t-micro);color:var(--ink-3);margin-top:4px",
                  text:
                    `${fmtDate(run.created_at)} · ${run.n_queries} truy vấn · ` +
                    `${run.n_sources} nguồn · ${run.n_terms} thuật ngữ · ${run.status}`,
                })
              )
            )
          )
        )
      );
    }
  }

  await reload();
}
