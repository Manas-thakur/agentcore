import * as React from "react";
import {
  ClockIcon,
  KeyboardIcon,
  MessageSquareIcon,
  MoonIcon,
  OctagonXIcon,
  PlayIcon,
  PlusIcon,
  SunIcon,
  WaypointsIcon,
} from "lucide-react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { NAV } from "@/app/nav";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { api, qs } from "@/lib/api";
import { fmtAgo, fmtMs, plural } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import type { EvalRunInfo, EvalSuite, ExploreResponse, SessionSummary, TraceSummary } from "@/lib/types";

export function CommandPalette({
  open,
  onOpenChange,
  openShortcuts,
  newChat,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  openShortcuts: () => void;
  newChat: () => void;
}) {
  const navigate = useNavigate();
  const theme = useTheme();
  const [search, setSearch] = React.useState("");
  const q = useDebounced(search.trim(), 160);
  const [traces, setTraces] = React.useState<TraceSummary[]>([]);
  const [suites, setSuites] = React.useState<EvalSuite[]>([]);
  const [chats, setChats] = React.useState<SessionSummary[]>([]);

  React.useEffect(() => {
    if (!open) return;
    setSearch("");
    api.get<EvalSuite[]>("/api/evals/suites").then(setSuites, () => {});
    api.get<SessionSummary[]>("/api/sessions").then((s) => setChats(s.slice(0, 8)), () => {});
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    const query = q ? `"${q.replace(/"/g, "")}"` : null;
    api
      .get<ExploreResponse>(`/api/traces/explore${qs({ limit: q ? 8 : 5, query, buckets: 4 })}`, { signal: ctrl.signal })
      .then((r) => setTraces(r.items), () => {});
    return () => ctrl.abort();
  }, [open, q]);

  const run = (fn: () => void) => {
    onOpenChange(false);
    fn();
  };

  const runSuite = async (s: EvalSuite) => {
    try {
      const job = await api.post<EvalRunInfo>("/api/evals/runs", { suite: s.path });
      toast.success(`Started ${s.name}`);
      navigate(`/evals${qs({ suite: s.path, run: job.id })}`);
    } catch (err) {
      toast.error(`Could not start the run: ${(err as Error).message}`);
    }
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Command palette"
      description="Go to a view, run an action, open a trace, chat or eval suite"
      className="sm:max-w-xl"
    >
      <Command loop>
        <CommandInput
          placeholder="Type a command, view, trace text or eval suite…"
          value={search}
          onValueChange={setSearch}
        />
        <CommandList className="max-h-[60vh]">
          <CommandEmpty>No matches. Try a view name, an action, a trace id or text from a trace input.</CommandEmpty>
          <CommandGroup heading="Actions">
            <CommandItem onSelect={() => run(newChat)} keywords={["create", "conversation", "playground"]}>
              <PlusIcon /> New chat
              <CommandShortcut>N</CommandShortcut>
            </CommandItem>
            <CommandItem onSelect={() => run(theme.toggle)} keywords={["dark", "light", "appearance", "colour", "color"]}>
              {theme.resolved === "dark" ? <SunIcon /> : <MoonIcon />} Toggle theme
              <CommandShortcut>⇧T</CommandShortcut>
            </CommandItem>
            <CommandItem
              onSelect={() => run(() => navigate(`/traces${qs({ query: "status:error" })}`))}
              keywords={["failed", "status:error", "traces", "filter"]}
            >
              <OctagonXIcon /> Show failed traces
            </CommandItem>
            <CommandItem
              onSelect={() => run(() => navigate(`/traces${qs({ chip: "slow" })}`))}
              keywords={["latency", "slow", "p95", "traces", "filter"]}
            >
              <ClockIcon /> Show slow traces (above p95)
            </CommandItem>
            <CommandItem onSelect={() => run(openShortcuts)} keywords={["help", "keys", "keyboard"]}>
              <KeyboardIcon /> Keyboard shortcuts
              <CommandShortcut>?</CommandShortcut>
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading="Go to">
            {NAV.map((n) => (
              <CommandItem key={n.id} onSelect={() => run(() => navigate(n.path))} keywords={["view", "page", n.id]}>
                <n.icon /> {n.label}
                <span className="hidden truncate text-xs text-muted-foreground sm:inline">{n.description}</span>
                <CommandShortcut>G {n.key.toUpperCase()}</CommandShortcut>
              </CommandItem>
            ))}
          </CommandGroup>
          {traces.length ? (
            <>
              <CommandSeparator />
              <CommandGroup heading={q ? "Matching traces" : "Recent traces"}>
                {traces.map((t) => (
                  <CommandItem
                    key={t.trace_id}
                    value={`trace ${t.trace_id} ${t.name} ${t.input}`}
                    keywords={q ? [q] : []}
                    onSelect={() => run(() => navigate(`/traces/${t.trace_id}`))}
                  >
                    {t.status === "ok" ? <WaypointsIcon /> : <OctagonXIcon className="text-destructive" />}
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate">{t.input ? t.input.slice(0, 90) : t.name}</span>
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {t.name} · {t.trace_id.slice(0, 8)} · {fmtMs(t.duration_ms)} · {fmtAgo(t.start_time)}
                      </span>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          ) : null}
          {chats.length ? (
            <>
              <CommandSeparator />
              <CommandGroup heading="Chats">
                {chats.map((c) => (
                  <CommandItem
                    key={c.id}
                    value={`chat ${c.id} ${c.title}`}
                    keywords={["chat", "session", "conversation"]}
                    onSelect={() => run(() => navigate(`/playground/${encodeURIComponent(c.id)}`))}
                  >
                    <MessageSquareIcon />
                    <span className="truncate">{c.title || "New chat"}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                      {plural(c.turns, "message")} · {fmtAgo(c.updated)}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          ) : null}
          {suites.filter((s) => !s.error).length ? (
            <>
              <CommandSeparator />
              <CommandGroup heading="Eval suites">
                {suites
                  .filter((s) => !s.error)
                  .map((s) => (
                    <CommandItem
                      key={s.path}
                      value={`run eval suite ${s.name} ${s.path}`}
                      keywords={["eval", "run", "suite", "test"]}
                      onSelect={() => run(() => void runSuite(s))}
                    >
                      <PlayIcon />
                      <span className="truncate">Run eval suite: {s.name}</span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">{plural(s.cases, "case")}</span>
                    </CommandItem>
                  ))}
              </CommandGroup>
            </>
          ) : null}
        </CommandList>
        <div className="flex items-center gap-4 border-t px-3 py-2 text-xs text-muted-foreground">
          <span>↑↓ move</span>
          <span>Enter run</span>
          <span>Esc close</span>
        </div>
      </Command>
    </CommandDialog>
  );
}
