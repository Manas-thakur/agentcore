// Incremental parser for text/event-stream bodies (the subset AgentCore emits:
// `event:` + one or more `data:` lines, blank-line separated). Pure, so it is unit-tested.

export interface SSEEvent {
  event: string;
  data: unknown;
}

export class SSEParser {
  private buffer = "";

  /** Feed a decoded chunk; returns every event completed by it. */
  push(chunk: string): SSEEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const out: SSEEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) >= 0) {
      const block = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      const ev = parseBlock(block);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** Flush a trailing event that was not followed by a blank line. */
  end(): SSEEvent[] {
    const rest = this.buffer.trim();
    this.buffer = "";
    if (!rest) return [];
    const ev = parseBlock(rest);
    return ev ? [ev] : [];
  }
}

export function parseBlock(block: string): SSEEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value.trim() || "message";
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  const raw = data.join("\n");
  let parsed: unknown = raw;
  try {
    parsed = JSON.parse(raw);
  } catch {
    /* plain text payload */
  }
  return { event, data: parsed };
}

/** Parse a complete SSE body at once (tests, small responses). */
export function parseSSE(text: string): SSEEvent[] {
  const p = new SSEParser();
  return [...p.push(text), ...p.end()];
}

/** Read a streaming Response body and call `onEvent` for each event. */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (ev: SSEEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const ev of parser.push(decoder.decode(value, { stream: true }))) onEvent(ev);
  }
  for (const ev of parser.push(decoder.decode())) onEvent(ev);
  for (const ev of parser.end()) onEvent(ev);
}
