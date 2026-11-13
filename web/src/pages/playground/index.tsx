import * as React from "react";
import {
  ArrowUpIcon,
  CopyIcon,
  ExternalLinkIcon,
  MessageCircleDashedIcon,
  MessagesSquareIcon,
  PanelRightIcon,
  PlusIcon,
  SquareIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { NEW_CHAT_EVENT } from "@/app/nav";
import { ContextUsage } from "@/components/ai/context-usage";
import { Markdown } from "@/components/ai/markdown";
import { ModelSelector } from "@/components/ai/model-selector";
import { RunSummary } from "@/components/ai/run-summary";
import { ErrorState, SkeletonRows } from "@/components/app/common";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupText,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import { Kbd } from "@/components/ui/kbd";
import { Message, MessageContent, MessageFooter } from "@/components/ui/message";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, ApiError, streamSSE } from "@/lib/api";
import { answerText, applyChatEvent, newAssistantTurn } from "@/lib/chat";
import { fmtAgo, fmtCost, plural } from "@/lib/format";
import { copyText, useFetch, useKeydown, useMediaQuery, useStored } from "@/lib/hooks";
import type { AssistantTurn, ModelInfo, ServerConfig, Session, SessionSummary, ToolInfo, Turn } from "@/lib/types";

import { DEFAULT_SETTINGS, enabledTools, RunSettings, type RunSettingsValue } from "./run-settings";

const EXAMPLES = [
  "What is 17 * 23 + 4?",
  "Compute (12 + 8) * 3 - 5.",
  "What is 2 ** 16 / 4?",
  "What time is it?",
];

interface Live {
  user: string;
  turn: AssistantTurn;
  startedAt: number;
}

function UserMessage({ text }: { text: string }) {
  return (
    <Message align="end">
      <MessageContent>
        <Bubble align="end" variant="muted">
          <BubbleContent className="whitespace-pre-wrap">{text}</BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  );
}

function AssistantMessage({ turn, startedAt }: { turn: AssistantTurn; startedAt?: number }) {
  const running = turn.status === "running";
  const answer = answerText(turn);
  const notes = turn.parts.filter((p) => p.type === "note");
  return (
    <Message>
      <MessageContent className="gap-3">
        <RunSummary turn={turn} startedAt={startedAt} />
        {answer ? (
          <Markdown streaming={running}>{answer}</Markdown>
        ) : running ? null : !turn.error && turn.status === "ok" ? (
          <p className="text-sm text-muted-foreground italic">(empty answer)</p>
        ) : null}
        {notes.map((n, i) => (
          <p key={i} className="rounded-md border-l-2 border-warning bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            {n.content}
          </p>
        ))}
        {turn.error ? (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>The run failed</AlertTitle>
            <AlertDescription className="break-words">{turn.error}</AlertDescription>
          </Alert>
        ) : null}
      </MessageContent>
      {!running ? (
        <MessageFooter className="absolute -bottom-6 left-0 gap-3 px-0 font-normal opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover/message:opacity-100 sm:group-focus-within/message:opacity-100">
          {turn.model ? <span className="font-mono">{turn.model}</span> : null}
          {turn.cost_usd ? <span>{fmtCost(turn.cost_usd)}</span> : null}
          {turn.status !== "ok" ? (
            <Badge variant={turn.status === "stopped" ? "secondary" : "destructive"}>{turn.status}</Badge>
          ) : null}
          {turn.trace_id ? (
            <Link to={`/traces/${turn.trace_id}`} className="inline-flex items-center gap-1 hover:text-foreground">
              View trace <ExternalLinkIcon className="size-3" />
            </Link>
          ) : null}
          {turn.content || answer ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-foreground"
              onClick={() => copyText(turn.content || answer).then((ok) => ok && toast.success("Answer copied"))}
              aria-label="Copy answer"
            >
              <CopyIcon className="size-3" /> Copy
            </button>
          ) : null}
        </MessageFooter>
      ) : null}
    </Message>
  );
}

function SessionList({
  sessions,
  loading,
  error,
  currentId,
  onOpen,
  onDelete,
  onNew,
  disabled,
}: {
  sessions: SessionSummary[];
  loading: boolean;
  error: Error | null;
  currentId: string | null;
  onOpen: (id: string) => void;
  onDelete: (s: SessionSummary) => void;
  onNew: () => void;
  disabled: boolean;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <h2 className="flex-1 text-sm font-semibold">Chats</h2>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" onClick={onNew} disabled={disabled} aria-label="New chat (N)">
              <PlusIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>New chat (N)</TooltipContent>
        </Tooltip>
      </div>
      <nav aria-label="Chat history" className="min-h-0 flex-1 overflow-y-auto p-2">
        {error ? (
          <p className="p-2 text-xs text-destructive">{error.message}</p>
        ) : loading && !sessions.length ? (
          <SkeletonRows rows={5} />
        ) : !sessions.length ? (
          <p className="p-2 text-xs text-muted-foreground">No chats yet. Conversations are saved on the server.</p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => (
              <li key={s.id} className="group/session relative">
                <button
                  type="button"
                  onClick={() => onOpen(s.id)}
                  aria-current={s.id === currentId ? "true" : undefined}
                  className="flex w-full flex-col items-start rounded-md px-2 py-1.5 pr-8 text-left text-sm transition-colors hover:bg-muted aria-[current=true]:bg-muted aria-[current=true]:font-medium"
                >
                  <span className="w-full truncate">{s.title || "New chat"}</span>
                  <span className="text-xs font-normal text-muted-foreground">
                    {plural(s.turns, "message")} · {fmtAgo(s.updated)}
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="absolute top-1.5 right-1.5 opacity-0 group-hover/session:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
                  aria-label={`Delete chat "${s.title}"`}
                  onClick={() => onDelete(s)}
                >
                  <Trash2Icon />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </nav>
    </div>
  );
}

export default function PlaygroundPage() {
  const params = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const sessionId = params.sessionId || null;
  const [settings, setSettings] = useStored<RunSettingsValue>("pg.settings", DEFAULT_SETTINGS);
  const [settingsOpenWide, setSettingsOpenWide] = useStored("pg.settingsOpen", true);
  const [settingsSheet, setSettingsSheet] = React.useState(false);
  const [sessionsSheet, setSessionsSheet] = React.useState(false);
  const wide = useMediaQuery("(min-width: 1280px)");
  const medium = useMediaQuery("(min-width: 1024px)");
  const [mockDismissed, setMockDismissed] = useStored("pg.mockNoticeDismissed", false);

  const sessionsQ = useFetch<SessionSummary[]>("/api/sessions");
  const toolsQ = useFetch<ToolInfo[]>("/api/tools");
  const modelsQ = useFetch<{ data: ModelInfo[] }>("/v1/models");
  const configQ = useFetch<ServerConfig>("/api/config");
  const models = modelsQ.data?.data || [];
  const defaultModel = models.find((m) => m.default)?.id || configQ.data?.default_model;

  const [session, setSession] = React.useState<Session | null>(null);
  const [sessionError, setSessionError] = React.useState<Error | null>(null);
  const [loadingSession, setLoadingSession] = React.useState(false);
  const [live, setLive] = React.useState<Live | null>(null);
  const [draft, setDraft] = React.useState("");
  const running = React.useRef<{ controller: AbortController; sessionId: string | null } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const pendingDeletes = React.useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const inputRef = React.useRef<HTMLTextAreaElement>(null);
  const formRef = React.useRef<HTMLFormElement>(null);
  const skipLoad = React.useRef<string | null>(null);

  const settingsOpen = wide ? settingsOpenWide : settingsSheet;
  const toggleSettings = (on = !settingsOpen) => (wide ? setSettingsOpenWide(on) : setSettingsSheet(on));

  // Load the session in the URL (unless we just created it by streaming).
  React.useEffect(() => {
    if (!sessionId) {
      setSession(null);
      setSessionError(null);
      return;
    }
    if (skipLoad.current === sessionId) {
      skipLoad.current = null;
      return;
    }
    const ctrl = new AbortController();
    setLoadingSession(true);
    api
      .get<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`, { signal: ctrl.signal })
      .then((s) => {
        setSession(s);
        setSessionError(null);
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        if (e instanceof ApiError && e.status === 404) {
          toast("That chat no longer exists.");
          navigate("/playground", { replace: true });
          return;
        }
        setSessionError(e);
      })
      .finally(() => !ctrl.signal.aborted && setLoadingSession(false));
    return () => ctrl.abort();
  }, [sessionId, navigate]);

  const newChat = React.useCallback(() => {
    if (running.current) {
      toast("Wait for the current turn to finish or stop it first.");
      return;
    }
    setLive(null);
    setSession(null);
    setSessionsSheet(false);
    navigate("/playground");
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [navigate]);

  React.useEffect(() => {
    const on = () => newChat();
    window.addEventListener(NEW_CHAT_EVENT, on);
    return () => window.removeEventListener(NEW_CHAT_EVENT, on);
  }, [newChat]);
  React.useEffect(() => {
    if ((location.state as { newChat?: number } | null)?.newChat) inputRef.current?.focus();
  }, [location.state]);

  // Flush pending deletes and abort a running stream when leaving the page.
  React.useEffect(() => {
    const deletes = pendingDeletes.current;
    return () => {
      running.current?.controller.abort();
      for (const [id, timer] of deletes) {
        clearTimeout(timer);
        api.del(`/api/sessions/${encodeURIComponent(id)}`).catch(() => {});
      }
    };
  }, []);

  useKeydown((ev) => {
    if (ev.key === "/") {
      ev.preventDefault();
      inputRef.current?.focus();
    } else if (ev.key === ".") {
      ev.preventDefault();
      toggleSettings();
    }
  });

  const openSession = (id: string) => {
    if (running.current) {
      toast("Wait for the current turn to finish or stop it first.");
      return;
    }
    setSessionsSheet(false);
    if (id !== sessionId) {
      setLive(null);
      navigate(`/playground/${encodeURIComponent(id)}`);
    }
  };

  const deleteSession = (s: SessionSummary) => {
    if (running.current?.sessionId === s.id) {
      toast.error("Stop the running turn before deleting this chat.");
      return;
    }
    sessionsQ.setData((list) => (list || []).filter((x) => x.id !== s.id));
    const timer = setTimeout(async () => {
      pendingDeletes.current.delete(s.id);
      try {
        await api.del(`/api/sessions/${encodeURIComponent(s.id)}`);
      } catch (err) {
        toast.error(`Delete failed: ${(err as Error).message}`);
        sessionsQ.reload();
      }
    }, 5000);
    pendingDeletes.current.set(s.id, timer);
    if (s.id === sessionId) newChat();
    toast("Chat deleted", {
      duration: 5000,
      action: {
        label: "Undo",
        onClick: () => {
          clearTimeout(timer);
          pendingDeletes.current.delete(s.id);
          sessionsQ.reload();
        },
      },
    });
  };

  const stop = async () => {
    const run = running.current;
    if (!run) return;
    try {
      if (run.sessionId) await api.post(`/api/sessions/${encodeURIComponent(run.sessionId)}/stop`);
    } catch {
      /* fall back to aborting the stream */
    }
    setTimeout(() => {
      if (running.current === run) run.controller.abort();
    }, 2500);
  };

  const send = async (textArg?: string) => {
    const text = (textArg ?? draft).trim();
    if (!text || running.current) return;
    setDraft("");
    const controller = new AbortController();
    running.current = { controller, sessionId };
    setBusy(true);
    const startedAt = performance.now();
    let turn = newAssistantTurn(settings.model || defaultModel);
    setLive({ user: text, turn, startedAt });
    const tools = toolsQ.data;
    let finished = false;
    let sid = sessionId;
    try {
      await streamSSE(
        "/api/chat",
        {
          message: text,
          session_id: sessionId,
          model: settings.model || null,
          tools: tools && tools.length ? enabledTools(settings, tools) : null,
          system_prompt: settings.system_prompt || null,
          max_steps: settings.max_steps,
        },
        (ev) => {
          turn = applyChatEvent(turn, ev);
          if (ev.event === "session") {
            const d = ev.data as { session_id: string; title: string };
            sid = d.session_id;
            if (running.current) running.current.sessionId = sid;
            if (sid !== sessionId) {
              skipLoad.current = sid;
              navigate(`/playground/${encodeURIComponent(sid)}`, { replace: true });
            }
            sessionsQ.reload();
          }
          if (ev.event === "done" || ev.event === "stopped" || ev.event === "error") finished = true;
          setLive({ user: text, turn, startedAt });
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name === "AbortError") turn = { ...turn, status: "stopped" };
      else turn = { ...turn, status: "error", error: (err as Error).message };
      finished = true;
    } finally {
      if (!finished) turn = { ...turn, status: "error", error: "The stream ended unexpectedly." };
      if (!turn.duration_ms) turn = { ...turn, duration_ms: performance.now() - startedAt };
      setLive({ user: text, turn, startedAt });
      running.current = null;
      setBusy(false);
      if (sid) {
        try {
          const fresh = await api.get<Session>(`/api/sessions/${encodeURIComponent(sid)}`);
          setSession(fresh);
          setLive(null);
        } catch {
          /* keep the streamed view */
        }
      }
      sessionsQ.reload();
      inputRef.current?.focus();
    }
  };

  const turns: Turn[] = session?.messages || [];
  const allTurns: Turn[] = live
    ? [...turns, { role: "user", content: live.user, ts: 0 }, live.turn]
    : turns;
  const toolCount = enabledTools(settings, toolsQ.data || []).length;
  const effectiveModel = settings.model || defaultModel || "";
  const showMock = !mockDismissed && /^mock\b/.test(effectiveModel);
  const title = session?.title || (live ? live.user.slice(0, 60) : "New chat");

  const sessionsPanel = (
    <SessionList
      sessions={sessionsQ.data || []}
      loading={sessionsQ.loading}
      error={sessionsQ.error}
      currentId={sessionId}
      onOpen={openSession}
      onDelete={deleteSession}
      onNew={newChat}
      disabled={busy}
    />
  );
  const settingsPanel = (
    <RunSettings
      value={settings}
      onChange={setSettings}
      tools={toolsQ.data}
      toolsError={toolsQ.error}
      models={models}
      defaultModel={defaultModel}
      onClose={() => toggleSettings(false)}
    />
  );

  return (
    <div className="flex h-full min-h-0">
      {medium ? <aside className="hidden w-64 shrink-0 border-r bg-sidebar/40 lg:block">{sessionsPanel}</aside> : null}

      <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
          {!medium ? (
            <Button variant="ghost" size="icon-sm" onClick={() => setSessionsSheet(true)} aria-label="Show chats">
              <MessagesSquareIcon />
            </Button>
          ) : null}
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h1>
          <ContextUsage turns={allTurns} />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={settingsOpen ? "secondary" : "ghost"}
                size="icon-sm"
                onClick={() => toggleSettings()}
                aria-label="Run settings (.)"
                aria-expanded={settingsOpen}
              >
                <PanelRightIcon />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Run settings (.)</TooltipContent>
          </Tooltip>
        </div>

        <div className="relative min-h-0 flex-1">
          {sessionError ? (
            <div className="p-6">
              <ErrorState error={sessionError} onRetry={() => navigate(0)} />
            </div>
          ) : loadingSession && !session ? (
            <div className="mx-auto max-w-3xl space-y-6 p-6">
              <SkeletonRows rows={4} />
            </div>
          ) : !allTurns.length ? (
            <div className="h-full overflow-y-auto">
              <Empty className="mx-auto h-full max-w-2xl">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <MessageCircleDashedIcon />
                  </EmptyMedia>
                  <EmptyTitle>Ask the agent something</EmptyTitle>
                  <EmptyDescription>
                    Replies stream in. Each one starts with a short run summary you can expand into the full step
                    timeline: model calls, tool arguments and results, timings. Every reply links to its trace.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent className="max-w-xl gap-4">
                  {showMock ? (
                    <Alert className="text-left">
                      <TriangleAlertIcon className="text-warning" />
                      <AlertTitle>You're using the offline mock model</AlertTitle>
                      <AlertDescription>
                        <p>
                          It handles arithmetic and simple tool calls so you can explore without a model server. For
                          real answers, restart with <code className="font-mono">agentcore serve --model ollama:qwen2.5:7b</code>,
                          or set <code className="font-mono">OPENAI_BASE_URL</code> and use{" "}
                          <code className="font-mono">--model openai:&lt;name&gt;</code>. You can also pick a model in
                          Run settings.
                        </p>
                        <Button variant="outline" size="xs" className="mt-2" onClick={() => setMockDismissed(true)}>
                          Got it
                        </Button>
                      </AlertDescription>
                    </Alert>
                  ) : null}
                  <div className="flex flex-wrap justify-center gap-2" aria-label="Example prompts">
                    {EXAMPLES.map((q) => (
                      <Button key={q} variant="outline" size="sm" onClick={() => send(q)} disabled={busy}>
                        {q}
                      </Button>
                    ))}
                  </div>
                </EmptyContent>
              </Empty>
            </div>
          ) : (
            <MessageScrollerProvider>
              <MessageScroller>
                <MessageScrollerViewport aria-label="Messages">
                  <MessageScrollerContent aria-busy={busy} className="mx-auto w-full max-w-3xl gap-10 px-4 py-6 md:px-6">
                    {allTurns.map((t, i) => (
                      <MessageScrollerItem
                        key={`${i}-${t.role}`}
                        messageId={`m${i}`}
                        scrollAnchor={t.role === "user"}
                      >
                        {t.role === "user" ? (
                          <UserMessage text={t.content} />
                        ) : (
                          <AssistantMessage turn={t} startedAt={live && t === live.turn ? live.startedAt : undefined} />
                        )}
                      </MessageScrollerItem>
                    ))}
                  </MessageScrollerContent>
                </MessageScrollerViewport>
                <MessageScrollerButton />
              </MessageScroller>
            </MessageScrollerProvider>
          )}
        </div>

        <div className="shrink-0 px-3 pb-3 md:px-6 md:pb-5">
          <form
            ref={formRef}
            className="mx-auto w-full max-w-3xl"
            onSubmit={(e) => {
              e.preventDefault();
              if (busy) void stop();
              else void send();
            }}
          >
            <InputGroup className="rounded-xl bg-card shadow-xs">
              <InputGroupTextarea
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Message the agent…"
                aria-label="Message"
                aria-keyshortcuts="/"
                maxLength={100000}
                autoFocus
                className="max-h-56 min-h-14 px-3.5 pt-3 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (!busy) formRef.current?.requestSubmit();
                  } else if (e.key === "Escape") {
                    e.currentTarget.blur();
                  }
                }}
              />
              <InputGroupAddon align="block-end" className="gap-1.5 pt-0">
                <ModelSelector
                  value={settings.model}
                  onChange={(model) => setSettings({ ...settings, model })}
                  models={models}
                  defaultModel={defaultModel}
                  className="h-7 max-w-[11rem] sm:max-w-[16rem]"
                />
                <InputGroupButton
                  variant="ghost"
                  size="xs"
                  onClick={() => toggleSettings(true)}
                  className="text-muted-foreground"
                  aria-label={`Run settings: ${plural(toolCount, "tool")}, ${settings.max_steps} max steps`}
                >
                  {plural(toolCount, "tool")} · {settings.max_steps} steps
                </InputGroupButton>
                <InputGroupText className="ml-auto hidden gap-1 text-xs font-normal xl:flex">
                  <Kbd>Enter</Kbd> send · <Kbd>Shift</Kbd>
                  <Kbd>Enter</Kbd> new line
                </InputGroupText>
                {busy ? (
                  <InputGroupButton
                    type="submit"
                    variant="destructive"
                    size="icon-sm"
                    className="ml-auto rounded-full xl:ml-0"
                    aria-label="Stop the running turn"
                  >
                    <SquareIcon className="fill-current" />
                  </InputGroupButton>
                ) : (
                  <InputGroupButton
                    type="submit"
                    variant="default"
                    size="icon-sm"
                    className="ml-auto rounded-full xl:ml-0"
                    disabled={!draft.trim()}
                    aria-label="Send message"
                  >
                    <ArrowUpIcon />
                  </InputGroupButton>
                )}
              </InputGroupAddon>
            </InputGroup>
          </form>
        </div>
      </section>

      {wide && settingsOpen ? <aside className="w-80 shrink-0 border-l bg-sidebar/40" aria-label="Run settings">{settingsPanel}</aside> : null}

      <Sheet open={!wide && settingsSheet} onOpenChange={setSettingsSheet}>
        <SheetContent side="right" className="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-sm" showCloseButton={false}>
          <SheetTitle className="sr-only">Run settings</SheetTitle>
          <SheetDescription className="sr-only">Model, tools, max steps and system prompt</SheetDescription>
          {settingsPanel}
        </SheetContent>
      </Sheet>
      <Sheet open={!medium && sessionsSheet} onOpenChange={setSessionsSheet}>
        <SheetContent side="left" className="gap-0 p-0 data-[side=left]:w-[85vw] data-[side=left]:sm:max-w-xs" showCloseButton={false}>
          <SheetTitle className="sr-only">Chats</SheetTitle>
          <SheetDescription className="sr-only">Chat history</SheetDescription>
          {sessionsPanel}
        </SheetContent>
      </Sheet>
    </div>
  );
}
