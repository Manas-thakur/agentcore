// Fetch wrapper: JSON helpers, the optional API key (prompted once on 401), SSE-over-POST.

import { readEventStream, type SSEEvent } from "@/lib/sse";
import { storage } from "@/lib/storage";

const KEY_STORAGE = "apiKey";

export function getApiKey(): string {
  const v = storage.get<unknown>(KEY_STORAGE, "");
  return v === null || v === undefined || v === "" ? "" : String(v);
}

export function setApiKey(key: string | null) {
  if (key) storage.set(KEY_STORAGE, key);
  else storage.remove(KEY_STORAGE);
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Registered by the API-key dialog; resolves true when a key was saved. */
type KeyPrompter = (message: string) => Promise<boolean>;
let prompter: KeyPrompter | null = null;
let pending: Promise<boolean> | null = null;

export function registerKeyPrompter(fn: KeyPrompter | null) {
  prompter = fn;
}

export function promptForKey(message = ""): Promise<boolean> {
  if (!prompter) return Promise.resolve(false);
  if (!pending) {
    pending = prompter(message).finally(() => {
      pending = null;
    });
  }
  return pending;
}

function headers(json: boolean): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  const key = getApiKey();
  if (key) h.Authorization = `Bearer ${key}`;
  return h;
}

async function errorFrom(resp: Response): Promise<ApiError> {
  let body: unknown = null;
  let message = `${resp.status} ${resp.statusText}`.trim();
  try {
    body = await resp.json();
    const b = body as { detail?: unknown; error?: { message?: string } };
    if (typeof b.detail === "string") message = b.detail;
    else if (Array.isArray(b.detail))
      message = b.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
        .join("; ");
    else if (b.error?.message) message = b.error.message;
  } catch {
    /* not JSON */
  }
  return new ApiError(resp.status, message, body);
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export async function request(path: string, opts: RequestOptions = {}, retried = false): Promise<Response> {
  const { method = "GET", body, signal } = opts;
  const init: RequestInit = { method, signal, headers: headers(body !== undefined) };
  if (body !== undefined) init.body = JSON.stringify(body);
  let resp: Response;
  try {
    resp = await fetch(path, init);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach the AgentCore server. Is `agentcore serve` running?");
  }
  if (resp.status === 401 && !retried) {
    const ok = await promptForKey(getApiKey() ? "The saved key was rejected." : "");
    if (ok) return request(path, opts, true);
  }
  if (!resp.ok) throw await errorFrom(resp);
  return resp;
}

export async function getJSON<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const resp = await request(path, opts);
  if (resp.status === 204) return null as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => getJSON<T>(path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    getJSON<T>(path, { ...opts, method: "POST", body: body ?? {} }),
  del: <T>(path: string, opts?: RequestOptions) => getJSON<T>(path, { ...opts, method: "DELETE" }),
  /** GET returning the parsed body plus a response header (e.g. X-Total-Count). */
  async getWithHeader<T>(path: string, header: string, opts?: RequestOptions): Promise<[T, string | null]> {
    const resp = await request(path, opts);
    return [(await resp.json()) as T, resp.headers.get(header)];
  },
};

/** POST a JSON body and stream the text/event-stream response. */
export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await request(path, { method: "POST", body, signal });
  if (!resp.body) throw new ApiError(0, "The server returned an empty stream.");
  await readEventStream(resp.body, onEvent);
}

/** Download a file from an (optionally authenticated) endpoint. */
export async function download(path: string, filename: string) {
  const resp = await request(path);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
