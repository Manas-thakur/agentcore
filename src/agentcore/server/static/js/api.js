// Fetch wrapper: JSON helpers, optional API key (prompted once on 401), SSE-over-POST reader.

const KEY_STORAGE = "agentcore.apiKey";
let pendingKeyPrompt = null;

export function getApiKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setApiKey(key) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function headers(extra = {}) {
  const hdrs = { ...extra };
  const key = getApiKey();
  if (key) hdrs.Authorization = `Bearer ${key}`;
  return hdrs;
}

// Ask for the key with the <dialog> in index.html. Resolves true if a key was saved.
export function promptForKey(message) {
  if (pendingKeyPrompt) return pendingKeyPrompt;
  const dialog = document.getElementById("auth-dialog");
  const form = document.getElementById("auth-form");
  const input = document.getElementById("auth-key");
  const error = document.getElementById("auth-error");
  const cancel = document.getElementById("auth-cancel");
  pendingKeyPrompt = new Promise((resolve) => {
    error.hidden = !message;
    error.textContent = message || "";
    input.value = "";
    const done = (ok) => {
      form.removeEventListener("submit", onSubmit);
      cancel.removeEventListener("click", onCancel);
      dialog.removeEventListener("cancel", onCancel);
      if (dialog.open) dialog.close();
      pendingKeyPrompt = null;
      resolve(ok);
    };
    const onSubmit = (ev) => {
      ev.preventDefault();
      const value = input.value.trim();
      if (!value) {
        input.setAttribute("aria-invalid", "true");
        return;
      }
      input.removeAttribute("aria-invalid");
      setApiKey(value);
      done(true);
    };
    const onCancel = (ev) => {
      ev.preventDefault();
      done(false);
    };
    form.addEventListener("submit", onSubmit);
    cancel.addEventListener("click", onCancel);
    dialog.addEventListener("cancel", onCancel);
    dialog.showModal();
    input.focus();
  });
  return pendingKeyPrompt;
}

async function errorFrom(resp) {
  let body = null;
  let message = `${resp.status} ${resp.statusText}`;
  try {
    body = await resp.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail)) message = body.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    else if (body.error && body.error.message) message = body.error.message;
  } catch {
    /* not JSON */
  }
  return new ApiError(resp.status, message, body);
}

export async function request(path, { method = "GET", body, signal, raw = false, retried = false } = {}) {
  const init = { method, signal, headers: headers(body !== undefined ? { "Content-Type": "application/json" } : {}) };
  if (body !== undefined) init.body = JSON.stringify(body);
  let resp;
  try {
    resp = await fetch(path, init);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach the AgentCore server. Is `agentcore serve` running?");
  }
  if (resp.status === 401 && !retried) {
    const hadKey = !!getApiKey();
    const ok = await promptForKey(hadKey ? "The saved key was rejected." : "");
    if (ok) return request(path, { method, body, signal, raw, retried: true });
  }
  if (!resp.ok) throw await errorFrom(resp);
  if (raw) return resp;
  if (resp.status === 204) return null;
  return resp.json();
}

export const api = {
  get: (p, opts) => request(p, opts),
  post: (p, body, opts) => request(p, { ...opts, method: "POST", body: body ?? {} }),
  del: (p, opts) => request(p, { ...opts, method: "DELETE" }),
};

// POST a JSON body and parse the text/event-stream response. `onEvent(name, data)` per event.
export async function streamSSE(path, body, { onEvent, signal }) {
  const resp = await request(path, { method: "POST", body, signal, raw: true });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      const data = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (!data.length) continue;
      let parsed;
      try {
        parsed = JSON.parse(data.join("\n"));
      } catch {
        parsed = data.join("\n");
      }
      onEvent(event, parsed);
    }
  }
}

// Download a file from an authenticated endpoint.
export async function download(path, filename) {
  const resp = await request(path, { raw: true });
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
