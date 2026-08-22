/**
 * Cổng duy nhất gọi backend.
 *
 * Vào:  đường dẫn + payload.
 * Ra:   dữ liệu đã parse, hoặc ném ApiError mang thông báo TIẾNG VIỆT hiển thị thẳng được.
 *
 * Điểm quan trọng nhất ở đây: HTTP 409 `consent_required` được bắt ở ĐÚNG MỘT CHỖ.
 * Bản Streamlit phải xử lý riêng ở từng màn hình nên rất dễ sót đường; gom về một chỗ
 * thì không đường nào lọt, và sau khi chuyên gia đồng ý thì tự chạy lại đúng yêu cầu
 * vừa bị chặn — người dùng không phải bấm lại.
 */

const BASE = "";

export class ApiError extends Error {
  constructor(message, status = null, body = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export class ConsentRequired extends ApiError {
  constructor(message, preview) {
    super(message, 409);
    this.name = "ConsentRequired";
    this.preview = preview;
  }
}

/** Hàm hỏi đồng ý do lớp giao diện cắm vào (xem ui.js). Trả về true nếu được đồng ý. */
let consentHandler = null;
export function setConsentHandler(fn) {
  consentHandler = fn;
}

function pickDetail(body, fallback) {
  const detail = body?.detail ?? body?.error;
  if (Array.isArray(detail)) {
    return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("; ");
  }
  return typeof detail === "string" ? detail : fallback;
}

async function parse(response) {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function raw(method, path, { json, form, query, timeoutMs = 900000 } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const init = { method, signal: controller.signal, headers: {} };
  if (json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(json);
  } else if (form !== undefined) {
    init.body = form; // trình duyệt tự đặt boundary cho multipart
  }

  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    clearTimeout(timer);
    if (error.name === "AbortError") {
      throw new ApiError(
        "Máy chủ xử lý quá lâu và chưa trả lời. Phần việc đã xong vẫn được giữ — thử lại."
      );
    }
    throw new ApiError(
      "Không kết nối được máy chủ. Kiểm tra xem cửa sổ backend còn chạy không, " +
        "hoặc chạy lại `.\\run.ps1`."
    );
  }
  clearTimeout(timer);

  if (response.ok) return parse(response);

  const body = await parse(response);

  if (response.status === 409 && body?.error === "consent_required") {
    throw new ConsentRequired(
      pickDetail(body, "Cần bạn đồng ý trước khi gửi dữ liệu ra ngoài."),
      body.preview ?? {}
    );
  }

  throw new ApiError(
    pickDetail(body, `Máy chủ trả lỗi ${response.status}.`),
    response.status,
    body
  );
}

/**
 * Gọi API, tự xử lý cổng đồng ý của hồ sơ mật.
 * Bị chặn → hỏi chuyên gia → cấp vé → CHẠY LẠI đúng yêu cầu vừa bị chặn.
 */
async function call(method, path, options = {}) {
  try {
    return await raw(method, path, options);
  } catch (error) {
    if (!(error instanceof ConsentRequired) || !consentHandler) throw error;

    const granted = await consentHandler(error.preview);
    if (!granted) {
      throw new ApiError(
        "Bạn đã từ chối gửi dữ liệu ra ngoài, nên thao tác này dừng lại. " +
          "Dữ liệu trên máy không thay đổi."
      );
    }
    return raw(method, path, options);
  }
}

export const get = (path, query) => call("GET", path, { query });
export const post = (path, json, query) => call("POST", path, { json, query });
export const patch = (path, json) => call("PATCH", path, { json });
export const del = (path, query) => call("DELETE", path, { query });

/* ======================= Hàm theo nghiệp vụ ======================= */

export const health = () => get("/health");
export const pingLlm = () => post("/system/ping-llm");

export const listWorkspaces = () => get("/workspaces");
export const getWorkspace = (id) => get(`/workspaces/${id}`);
export const createWorkspace = (body) => post("/workspaces", body);
export const updateWorkspace = (id, body) => patch(`/workspaces/${id}`, body);
export const deletePreview = (id) => get(`/workspaces/${id}/delete-preview`);
export const deleteWorkspace = (id) => del(`/workspaces/${id}`, { confirm: true });

export const dashboard = (workspaceId) => get("/dashboard", { workspace_id: workspaceId });

/* --- Tài liệu --- */
export const listDocuments = (workspaceId) => get("/documents", { workspace_id: workspaceId });
export const previewDocument = (id) => get(`/documents/${id}/preview`);
export const setDocumentLanguage = (id, language) =>
  patch(`/documents/${id}/language?language=${encodeURIComponent(language)}`);
export const reindexDocument = (id) => post(`/documents/${id}/reindex`);
export const deleteDocument = (id) => del(`/documents/${id}`);
export const askDocuments = (body) => post("/documents/ask", body);
export const qaHistory = (workspaceId) =>
  get("/documents/qa-history", { workspace_id: workspaceId });

export function uploadDocuments(workspaceId, files) {
  const form = new FormData();
  form.append("workspace_id", String(workspaceId));
  for (const file of files) form.append("files", file, file.name);
  return call("POST", "/documents/upload", { form });
}

/* --- Nghiên cứu & thuật ngữ --- */
export const runResearch = (body) => post("/research/run", body);
export const getProfiles = (workspaceId) => get("/research/profiles", { workspace_id: workspaceId });
export const editProfileField = (id, value) => patch(`/research/profile-fields/${id}`, { value });
export const researchRuns = (workspaceId) => get("/research/runs", { workspace_id: workspaceId });

export const listTerms = (workspaceId, query = {}) =>
  get("/glossary", { workspace_id: workspaceId, ...query });
export const glossaryStats = (workspaceId) => get("/glossary/stats", { workspace_id: workspaceId });
export const createTerm = (body) => post("/glossary", body);
export const updateTerm = (id, body) => patch(`/glossary/${id}`, body);
export const skipTerm = (id) => post(`/glossary/${id}/skip`);
export const resolveConflict = (id, accept) =>
  post(`/glossary/conflicts/${id}/resolve`, undefined, { accept });
export const glossaryExportUrl = (workspaceId) => `/glossary/export?workspace_id=${workspaceId}`;

/* --- Mock buổi dịch --- */
export const simulationContext = (workspaceId) =>
  get("/simulate/context", { workspace_id: workspaceId });
export const createScript = (body) => post("/simulate/script", body);
export const listSessions = (workspaceId) =>
  get("/simulate/sessions", { workspace_id: workspaceId });
export const getSession = (id) => get(`/simulate/sessions/${id}`);
export const submitAttempt = (body) => post("/simulate/attempts", body);
export const scoreAttempt = (id) => post(`/simulate/attempts/${id}/score`);
export const sessionReport = (id) => get(`/simulate/sessions/${id}/report`);
export const completeSession = (id) => post(`/simulate/sessions/${id}/complete`);

/* --- Âm thanh --- */
export const turnAudio = (turnId, speed = "normal") =>
  post(`/speech/turn-audio/${turnId}`, undefined, { speed });
export const audioUrl = (key) => `/speech/audio/${key}`;
export const deviceCheck = () => post("/speech/device-check");
export const storageStats = (workspaceId) =>
  get("/speech/storage", { workspace_id: workspaceId });
export const recordingsDeletePreview = (scope, targetId) =>
  get("/speech/recordings/delete-preview", { scope, target_id: targetId });
export const deleteRecordings = (scope, targetId) =>
  del("/speech/recordings", { scope, target_id: targetId, confirm: true });
export const clearTtsCache = () => del("/speech/tts-cache");

/* --- Vòng phản hồi --- */
export const submitVerdict = (body) => post("/feedback/verdict", body);
export const listVerdicts = (workspaceId) => get("/feedback/verdicts", { workspace_id: workspaceId });
export const divergence = (workspaceId) => get("/feedback/divergence", { workspace_id: workspaceId });
export const calibrationPreview = (workspaceId) =>
  get("/feedback/calibration-preview", { workspace_id: workspaceId });
export const resetCalibration = (workspaceId) =>
  post("/feedback/reset-calibration", undefined, { workspace_id: workspaceId, confirm: true });

/* --- Bảo mật --- */
export const egressLog = (workspaceId, limit = 300) =>
  get("/security/egress-log", { workspace_id: workspaceId, limit });
export const consentStatus = (workspaceId) => get(`/security/consent/${workspaceId}`);
export const grantConsent = (workspaceId, scope = "session") =>
  post("/security/consent", { workspace_id: workspaceId, scope });
export const revokeConsent = (workspaceId) => del(`/security/consent/${workspaceId}`);
