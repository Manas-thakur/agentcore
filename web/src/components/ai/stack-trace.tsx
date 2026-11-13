import { FileCodeIcon, LayersIcon, OctagonXIcon } from "lucide-react";

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";

interface Frame {
  file: string;
  line: string;
  fn: string;
  internal: boolean;
  raw: string;
}

const FRAME_RE = /^File "(.+?)", line (\d+)(?:, in (.+))?$/;

/** Split a Python-style error ("Type: message" plus optional traceback lines) into parts. */
export function parseError(text: string): { title: string; frames: Frame[]; rest: string[] } {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const frames: Frame[] = [];
  const rest: string[] = [];
  for (const l of lines) {
    const m = FRAME_RE.exec(l);
    if (m) {
      const file = m[1];
      frames.push({
        file,
        line: m[2],
        fn: m[3] || "<module>",
        internal: /site-packages|[\\/]lib[\\/]python|asyncio|<frozen/.test(file),
        raw: l,
      });
    } else if (!/^Traceback \(most recent call last\)/.test(l)) {
      rest.push(l);
    }
  }
  // The exception line is the last non-frame line in a traceback, the first otherwise.
  const title = frames.length ? rest[rest.length - 1] || "Error" : rest[0] || "Error";
  return { title, frames, rest: frames.length ? rest.slice(0, -1) : rest.slice(1) };
}

/** Stack Trace pattern: a failed step and its frames (when the error carries a traceback). */
export function StackTrace({ error, label = "Failed" }: { error: string; label?: string }) {
  const { title, frames, rest } = parseError(error);
  const app = frames.filter((f) => !f.internal);
  const internal = frames.filter((f) => f.internal);
  return (
    <TraceCollapsible defaultOpen>
      <TraceCollapsibleTrigger>
        <TraceLine status="error">
          <TraceIcon>
            <OctagonXIcon />
          </TraceIcon>
          <TraceTitle>
            {label}: {title}
          </TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="flex flex-col gap-2">
        <p className="font-mono text-xs break-words whitespace-pre-wrap text-destructive">
          {[title, ...rest].join("\n")}
        </p>
        {frames.length ? (
          <Trace>
            {app.map((f) => (
              <TraceLine key={f.raw}>
                <TraceIcon>
                  <FileCodeIcon />
                </TraceIcon>
                <TraceTitle className="font-mono text-xs">
                  {f.fn} in {f.file}:{f.line}
                </TraceTitle>
              </TraceLine>
            ))}
            {internal.length ? (
              <TraceCollapsible>
                <TraceCollapsibleTrigger>
                  <TraceLine>
                    <TraceIcon>
                      <LayersIcon />
                    </TraceIcon>
                    <TraceTitle>{internal.length} library frames</TraceTitle>
                  </TraceLine>
                </TraceCollapsibleTrigger>
                <TraceCollapsibleContent>
                  <Trace>
                    {internal.map((f) => (
                      <TraceLine key={f.raw}>
                        <TraceTitle className="font-mono text-xs">
                          {f.fn} in {f.file}:{f.line}
                        </TraceTitle>
                      </TraceLine>
                    ))}
                  </Trace>
                </TraceCollapsibleContent>
              </TraceCollapsible>
            ) : null}
          </Trace>
        ) : null}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}
