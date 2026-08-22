/**
 * State dùng chung: hồ sơ khách hàng đang chọn + cache nhẹ.
 *
 * Vào:  lời gọi setWorkspace / refreshWorkspaces từ các màn hình.
 * Ra:   trạng thái hiện tại, và thông báo cho ai đã đăng ký khi có thay đổi.
 *
 * Cố ý giữ nhỏ. Chín màn hình không cần một thư viện state — một object cộng
 * danh sách hàm lắng nghe là đủ, và đọc hiểu ngay không phải tra tài liệu.
 */

import * as api from "./api.js";

const LS_KEY = "rag_dich_workspace_id";

const state = {
  workspaces: [],
  workspaceId: null,
  loading: false,
};

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  for (const fn of listeners) fn(state);
}

export function get() {
  return state;
}

export function currentWorkspace() {
  return state.workspaces.find((w) => w.id === state.workspaceId) ?? null;
}

export async function refreshWorkspaces() {
  state.loading = true;
  emit();
  try {
    state.workspaces = await api.listWorkspaces();

    // Khôi phục hồ sơ đã chọn lần trước; nếu nó không còn thì lấy hồ sơ đầu tiên.
    const saved = Number(localStorage.getItem(LS_KEY));
    const exists = state.workspaces.some((w) => w.id === state.workspaceId);
    if (!exists) {
      const savedExists = state.workspaces.some((w) => w.id === saved);
      state.workspaceId = savedExists ? saved : state.workspaces[0]?.id ?? null;
    }
  } finally {
    state.loading = false;
    emit();
  }
  return state.workspaces;
}

export function setWorkspace(id) {
  const next = Number(id) || null;
  if (state.workspaceId === next) return;
  state.workspaceId = next;
  if (next) localStorage.setItem(LS_KEY, String(next));
  else localStorage.removeItem(LS_KEY);
  emit();
}

/** Cập nhật số liệu của một hồ sơ tại chỗ, khỏi phải tải lại cả danh sách. */
export async function touchWorkspace(id = state.workspaceId) {
  if (!id) return;
  try {
    const fresh = await api.getWorkspace(id);
    const index = state.workspaces.findIndex((w) => w.id === id);
    if (index >= 0) state.workspaces[index] = fresh;
    emit();
  } catch {
    /* số liệu hiển thị lệch một nhịp không đáng để làm hỏng thao tác đang chạy */
  }
}
