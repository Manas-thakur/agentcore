import * as React from "react";
import { cn } from "cn";
import { ExternalLinkIcon, PlayIcon, ShieldAlertIcon, WrenchIcon } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";

import { ToolCall } from "@/components/ai/tool-call";
import { CodeView, JsonView } from "@/components/app/code-view";
import { EmptyState, ErrorState, Panel, SkeletonRows } from "@/components/app/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { Trace } from "@/components/ui/trace";
import { api } from "@/lib/api";
import { compactArgs, fmtMs } from "@/lib/format";
import { useFetch, useMediaQuery } from "@/lib/hooks";
import type { JsonSchema, ToolInfo, ToolInvokeResult } from "@/lib/types";

/** Tools that run code, write files or reach the network ask before running (Confirmation pattern). */
function needsConfirmation(t: ToolInfo): boolean {
  return t.category === "code" || t.category === "web" || /^(write|delete|remove)/.test(t.name);
}

function schemaType(s: JsonSchema): string | undefined {
  if (Array.isArray(s.type)) return s.type.find((x) => x !== "null");
  if (s.type) return s.type;
  if (s.anyOf) return s.anyOf.find((x) => x.type !== "null")?.type as string | undefined;
  return undefined;
}

type Values = Record<string, string | boolean>;

function initialValues(props: Record<string, JsonSchema>): Values {
  const v: Values = {};
  for (const [name, s] of Object.entries(props)) {
    const type = schemaType(s);
    if (type === "boolean") v[name] = s.default === true;
    else if (s.enum) v[name] = s.default !== undefined ? JSON.stringify(s.default) : "";
    else if (type === "object" || type === "array") v[name] = s.default !== undefined ? JSON.stringify(s.default) : "";
    else v[name] = s.default !== undefined && s.default !== null ? String(s.default) : "";
  }
  return v;
}

function collect(props: Record<string, JsonSchema>, required: Set<string>, values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, s] of Object.entries(props)) {
    const type = schemaType(s);
    const raw = values[name];
    let v: unknown;
    if (type === "boolean") v = raw;
    else if (raw === "" || raw === undefined) v = undefined;
    else if (s.enum) v = JSON.parse(String(raw));
    else if (type === "integer" || type === "number") v = Number(raw);
    else if (type === "object" || type === "array") {
      try {
        v = JSON.parse(String(raw));
      } catch (cause) {
        throw new Error(`${name}: not valid JSON`, { cause });
      }
    } else v = raw;
    if (v !== undefined) out[name] = v;
    else if (required.has(name)) throw new Error(`${name} is required`);
  }
  return out;
}

function TryIt({ tool }: { tool: ToolInfo }) {
  const props = tool.parameters?.properties || {};
  const required = React.useMemo(() => new Set(tool.parameters?.required || []), [tool]);
  const [values, setValues] = React.useState<Values>(() => initialValues(props));
  const [raw, setRaw] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<ToolInvokeResult | null>(null);
  const [reqError, setReqError] = React.useState<string | null>(null);

  const getArgs = (): Record<string, unknown> => {
    if (raw !== null) {
      let v: unknown;
      try {
        v = JSON.parse(raw || "{}");
      } catch (e) {
        throw new Error(`Invalid JSON: ${(e as Error).message}`, { cause: e });
      }
      if (typeof v !== "object" || v === null || Array.isArray(v)) throw new Error("Arguments must be a JSON object");
      return v as Record<string, unknown>;
    }
    return collect(props, required, values);
  };

  const invoke = async (args: Record<string, unknown>) => {
    setPending(null);
    setBusy(true);
    setReqError(null);
    try {
      setResult(await api.post<ToolInvokeResult>(`/api/tools/${encodeURIComponent(tool.name)}/invoke`, { arguments: args }));
    } catch (e) {
      setResult(null);
      setReqError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    let args: Record<string, unknown>;
    try {
      args = getArgs();
    } catch (err) {
      setError((err as Error).message);
      return;
    }
    if (needsConfirmation(tool)) setPending(args);
    else void invoke(args);
  };

  const fields = Object.entries(props).map(([name, s]) => {
    const id = `arg-${name}`;
    const type = schemaType(s);
    const hint = [type, s.description].filter(Boolean).join(" · ");
    const set = (v: string | boolean) => setValues((cur) => ({ ...cur, [name]: v }));
    if (type === "boolean")
      return (
        <Field key={name} orientation="horizontal">
          <Checkbox id={id} checked={Boolean(values[name])} onCheckedChange={(c) => set(c === true)} />
          <FieldLabel htmlFor={id} className="font-mono">
            {name}
          </FieldLabel>
          {s.description ? <FieldDescription>{s.description}</FieldDescription> : null}
        </Field>
      );
    let control: React.ReactNode;
    if (s.enum) {
      control = (
        <Select value={String(values[name] || "__unset__")} onValueChange={(v) => set(v === "__unset__" ? "" : v)}>
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {!required.has(name) ? <SelectItem value="__unset__">(not set)</SelectItem> : null}
            {s.enum.map((v) => (
              <SelectItem key={JSON.stringify(v)} value={JSON.stringify(v)}>
                {String(v)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    } else if (type === "integer" || type === "number") {
      control = (
        <Input id={id} type="number" step={type === "integer" ? 1 : "any"} value={String(values[name])} onChange={(e) => set(e.target.value)} />
      );
    } else if (type === "object" || type === "array" || /code|text|content|body|query|expression/i.test(name)) {
      control = (
        <Textarea
          id={id}
          rows={name === "code" ? 6 : type === "object" || type === "array" ? 3 : 2}
          spellCheck={false}
          className="font-mono text-xs"
          placeholder={type === "array" ? "[ ]" : type === "object" ? "{ }" : undefined}
          value={String(values[name])}
          onChange={(e) => set(e.target.value)}
        />
      );
    } else {
      control = <Input id={id} spellCheck={false} value={String(values[name])} onChange={(e) => set(e.target.value)} />;
    }
    return (
      <Field key={name}>
        <FieldLabel htmlFor={id} className="font-mono">
          {name}
          {required.has(name) ? <span className="text-destructive" aria-hidden="true">*</span> : null}
          {required.has(name) ? <span className="sr-only">(required)</span> : null}
        </FieldLabel>
        {control}
        {hint ? <FieldDescription>{hint}</FieldDescription> : null}
      </Field>
    );
  });

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {raw === null ? (
          fields.length ? (
            <div className="space-y-4">{fields}</div>
          ) : (
            <p className="text-sm text-muted-foreground">This tool takes no arguments.</p>
          )
        ) : (
          <Field>
            <FieldLabel htmlFor="raw-args">Arguments (JSON)</FieldLabel>
            <Textarea id="raw-args" rows={8} spellCheck={false} className="font-mono text-xs" value={raw} onChange={(e) => setRaw(e.target.value)} />
          </Field>
        )}
        {error ? <FieldError>{error}</FieldError> : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={busy || Boolean(pending)}>
            {busy ? <Spinner /> : <PlayIcon />} Invoke
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              if (raw === null) {
                let v: Record<string, unknown> = {};
                try {
                  v = collect(props, new Set(), values);
                } catch {
                  /* start from an empty object */
                }
                setRaw(JSON.stringify(v, null, 2));
              } else setRaw(null);
              setError(null);
            }}
          >
            {raw === null ? "Edit as JSON" : "Edit as form"}
          </Button>
        </div>
      </form>

      {pending ? (
        <Item variant="outline" size="sm" role="alertdialog" aria-label={`Confirm running ${tool.name}`}>
          <ItemMedia variant="icon">
            <ShieldAlertIcon className="text-warning" />
          </ItemMedia>
          <ItemContent>
            <ItemTitle>
              Run <span className="font-mono">{tool.name}</span>
              <span className="font-mono text-xs text-muted-foreground">({compactArgs(pending).replace(/^\(\)$/, "")})</span>?
            </ItemTitle>
            <ItemDescription>
              {tool.category === "code"
                ? "This executes code on the server in a sandboxed subprocess."
                : tool.category === "web"
                  ? "This makes a network request from the server."
                  : "This changes files in the server's workspace."}
            </ItemDescription>
          </ItemContent>
          <ItemActions>
            <Button size="sm" variant="outline" onClick={() => setPending(null)}>
              Deny
            </Button>
            <Button size="sm" autoFocus onClick={() => void invoke(pending)}>
              Approve
            </Button>
          </ItemActions>
        </Item>
      ) : null}

      <div aria-live="polite" className="space-y-3">
        {busy ? (
          <Trace>
            <ToolCall call={{ name: tool.name, arguments: {}, status: "running" }} />
          </Trace>
        ) : reqError ? (
          <FieldError>{reqError}</FieldError>
        ) : result ? (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {result.success ? (
                <Badge className="bg-success/15 text-success">ok</Badge>
              ) : (
                <Badge variant="destructive">{result.error_type || "error"}</Badge>
              )}
              <span className="text-muted-foreground tabular">
                {fmtMs(result.latency_ms)} · {result.attempts} attempt{result.attempts === 1 ? "" : "s"}
              </span>
              {result.trace_id ? (
                <Link to={`/traces/${result.trace_id}`} className="ml-auto inline-flex items-center gap-1 text-brand hover:underline">
                  View trace <ExternalLinkIcon className="size-3" />
                </Link>
              ) : null}
            </div>
            <JsonView value={result.success ? result.output : result.error} variant={result.success ? "default" : "destructive"} />
          </>
        ) : (
          <p className="text-xs text-muted-foreground">Results appear here. Each invocation is traced like an agent tool call.</p>
        )}
      </div>
    </div>
  );
}

export default function ToolsPage() {
  const { toolName } = useParams();
  const navigate = useNavigate();
  const q = useFetch<ToolInfo[]>("/api/tools");
  const tools = q.data || [];
  const tool = tools.find((t) => t.name === toolName) || tools[0];
  const lg = useMediaQuery("(min-width: 1024px)");

  let body: React.ReactNode;
  if (q.error) body = <ErrorState error={q.error} onRetry={q.reload} />;
  else if (!q.data) body = <SkeletonRows rows={6} />;
  else if (!tools.length || !tool)
    body = (
      <EmptyState
        icon={WrenchIcon}
        title="No tools enabled"
        description={
          <>
            Start the server with <code className="font-mono">--tools calculator,current_time</code> or list tools in{" "}
            <code className="font-mono">agentcore.toml</code>.
          </>
        }
      />
    );
  else
    body = (
      <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        {lg ? (
          <nav aria-label="Tools" className="space-y-1">
            {tools.map((t) => (
              <Link
                key={t.name}
                to={`/tools/${encodeURIComponent(t.name)}`}
                replace
                aria-current={t.name === tool.name ? "page" : undefined}
                className="flex flex-col gap-0.5 rounded-lg border border-transparent px-2.5 py-2 transition-colors hover:bg-muted aria-[current=page]:border-border aria-[current=page]:bg-card aria-[current=page]:shadow-xs"
              >
                <span className="font-mono text-sm font-medium">{t.name}</span>
                <span className="line-clamp-2 text-xs text-muted-foreground">{t.description}</span>
              </Link>
            ))}
          </nav>
        ) : (
          <Select value={tool.name} onValueChange={(v) => navigate(`/tools/${encodeURIComponent(v)}`, { replace: true })}>
            <SelectTrigger aria-label="Tool" className="w-full font-mono">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {tools.map((t) => (
                <SelectItem key={t.name} value={t.name} className="font-mono">
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <div className="min-w-0 space-y-4">
          <Panel
            title={<span className="font-mono">{tool.name}</span>}
            actions={
              <>
                {tool.category ? <Badge variant="secondary">{tool.category}</Badge> : null}
                <Badge variant="outline" className={cn(tool.source === "custom" && "border-brand/40 text-brand")}>
                  {tool.source}
                </Badge>
                {tool.timeout ? <Badge variant="outline">timeout {tool.timeout}s</Badge> : null}
                {needsConfirmation(tool) ? (
                  <Badge variant="outline" className="border-warning/50 text-warning">
                    asks before running
                  </Badge>
                ) : null}
              </>
            }
          >
            <p className="text-sm">{tool.description || "No description."}</p>
          </Panel>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Try it">
              <TryIt key={tool.name} tool={tool} />
            </Panel>
            <Panel title="JSON Schema" description="Generated from type hints and docstrings">
              <CodeView code={JSON.stringify(tool.parameters, null, 2)} language="json" contentClassName="max-h-[28rem]" />
            </Panel>
          </div>
        </div>
      </div>
    );

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">Tools</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Tools enabled on this server. Schemas are generated from type hints and docstrings; invoke one directly to check
            it before the agent does.
          </p>
        </div>
        {body}
      </div>
    </div>
  );
}
