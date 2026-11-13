import * as React from "react";
import { ExternalLinkIcon, KeyRoundIcon, MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { toast } from "sonner";

import { useApp } from "@/app/app-context";
import { CodeView } from "@/components/app/code-view";
import { ErrorState, Page, PageHeader, Panel, SkeletonRows } from "@/components/app/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { getApiKey, promptForKey, setApiKey } from "@/lib/api";
import { useFetch } from "@/lib/hooks";
import { storage } from "@/lib/storage";
import { useTheme, type ThemePref } from "@/lib/theme";
import type { ServerConfig } from "@/lib/types";

function Row({ title, description, children }: { title: string; description?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="grid gap-3 py-4 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="space-y-0.5">
        <h3 className="text-sm font-medium">{title}</h3>
        {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export default function SettingsPage() {
  const { pref, setPref } = useTheme();
  const { health } = useApp();
  const [hasKey, setHasKey] = React.useState(() => Boolean(getApiKey()));
  const cfg = useFetch<ServerConfig>("/api/config");
  const list = (xs: string[] | null | undefined) => (xs && xs.length ? xs.join(", ") : "-");

  return (
    <div className="h-full overflow-y-auto">
      <Page className="max-w-4xl">
        <PageHeader
          title="Settings"
          description="Browser preferences are stored locally. Server settings come from agentcore.toml, environment variables and CLI flags."
        />
        <Panel title="This browser" bodyClassName="divide-y">
          <Row title="Theme" description="Follows your operating system unless you pick one.">
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={pref}
              onValueChange={(v) => v && setPref(v as ThemePref)}
              aria-label="Theme"
            >
              <ToggleGroupItem value="system" className="px-3">
                <MonitorIcon /> System
              </ToggleGroupItem>
              <ToggleGroupItem value="light" className="px-3">
                <SunIcon /> Light
              </ToggleGroupItem>
              <ToggleGroupItem value="dark" className="px-3">
                <MoonIcon /> Dark
              </ToggleGroupItem>
            </ToggleGroup>
          </Row>
          <Row
            title="API key"
            description={
              <>
                Needed only when the server sets <code className="font-mono">AGENTCORE_API_KEY</code>. Sent as a bearer token.
              </>
            }
          >
            {health?.auth ? <Badge variant="secondary">required by server</Badge> : <Badge variant="outline">not required</Badge>}
            {hasKey ? <Badge className="bg-success/15 text-success">key saved</Badge> : <Badge variant="outline">no key saved</Badge>}
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                if (await promptForKey("")) {
                  setHasKey(true);
                  toast.success("API key saved");
                }
              }}
            >
              <KeyRoundIcon /> {hasKey ? "Change key" : "Enter key"}
            </Button>
            {hasKey ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setApiKey(null);
                  setHasKey(false);
                  toast("API key removed from this browser");
                }}
              >
                Forget key
              </Button>
            ) : null}
          </Row>
          <Row title="Preferences" description="Playground settings, trace filters, panel sizes and the selected eval suite.">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                storage.resetPreferences();
                toast.success("Preferences reset");
              }}
            >
              Reset preferences
            </Button>
          </Row>
        </Panel>

        <Panel
          title="Server"
          actions={
            <Button asChild variant="outline" size="sm">
              <a href="/docs" target="_blank" rel="noopener noreferrer">
                API docs <ExternalLinkIcon />
              </a>
            </Button>
          }
        >
          {cfg.error ? (
            <ErrorState error={cfg.error} onRetry={cfg.reload} />
          ) : !cfg.data ? (
            <SkeletonRows rows={8} />
          ) : (
            <div className="space-y-4">
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[12rem_minmax(0,1fr)]">
                {(
                  [
                    ["Version", `${cfg.data.version} (python ${cfg.data.python})`],
                    ["Config file", cfg.data.config_file || "none (defaults + env)"],
                    ["Default model", <span className="font-mono">{cfg.data.default_model}</span>],
                    ["Extra models", list(cfg.data.models)],
                    ["Enabled tools", <span className="font-mono">{list(cfg.data.enabled_tools)}</span>],
                    ["Custom tools", list(cfg.data.custom_tools)],
                    ["Trace dir", <span className="font-mono break-all">{cfg.data.trace_dir}</span>],
                    ["State dir", <span className="font-mono break-all">{cfg.data.state_dir}</span>],
                    ["Eval dirs", <span className="font-mono break-all">{list(cfg.data.eval_dirs)}</span>],
                    ["Auth", cfg.data.server.auth_enabled ? "API key required" : "open (no API key)"],
                    ["CORS origins", list(cfg.data.server.cors_origins)],
                    ["Max request body", `${Math.round(cfg.data.server.max_body_bytes / 1024)} KB`],
                  ] as [string, React.ReactNode][]
                ).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="min-w-0">{v}</dd>
                  </div>
                ))}
              </dl>
              <CodeView code={JSON.stringify(cfg.data, null, 2)} language="json" title="Raw configuration" contentClassName="max-h-80" />
            </div>
          )}
        </Panel>
      </Page>
    </div>
  );
}
