import { RotateCcwIcon, XIcon } from "lucide-react";

import { ModelSelector } from "@/components/ai/model-selector";
import { SkeletonRows } from "@/components/app/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { ModelInfo, ToolInfo } from "@/lib/types";

export interface RunSettingsValue {
  model: string;
  tools: string[] | null; // null = every enabled tool
  system_prompt: string;
  max_steps: number;
}

export const DEFAULT_SETTINGS: RunSettingsValue = { model: "", tools: null, system_prompt: "", max_steps: 8 };

export function enabledTools(settings: RunSettingsValue, tools: ToolInfo[]): string[] {
  const all = tools.map((t) => t.name);
  return settings.tools === null ? all : settings.tools.filter((t) => all.includes(t));
}

export function RunSettings({
  value,
  onChange,
  tools,
  toolsError,
  models,
  defaultModel,
  onClose,
}: {
  value: RunSettingsValue;
  onChange: (v: RunSettingsValue) => void;
  tools: ToolInfo[] | undefined;
  toolsError: Error | null;
  models: ModelInfo[];
  defaultModel?: string;
  onClose?: () => void;
}) {
  const on = new Set(enabledTools(value, tools || []));
  const setSteps = (n: number) => onChange({ ...value, max_steps: Math.min(50, Math.max(1, Math.round(n) || 8)) });
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
        <h2 className="flex-1 text-sm font-semibold">Run settings</h2>
        {onClose ? (
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close run settings">
            <XIcon />
          </Button>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-4">
        <section className="space-y-2">
          <Label htmlFor="rs-model">Model</Label>
          <ModelSelector
            id="rs-model"
            value={value.model}
            onChange={(model) => onChange({ ...value, model })}
            models={models}
            defaultModel={defaultModel}
            className="w-full"
            size="default"
          />
          <p className="text-xs text-muted-foreground">
            Pick one or type any spec: <code className="font-mono">mock</code>,{" "}
            <code className="font-mono">ollama:&lt;model&gt;</code>, <code className="font-mono">openai:&lt;model&gt;</code>.
          </p>
        </section>

        <section className="space-y-2" aria-labelledby="rs-tools">
          <div className="flex items-center justify-between">
            <span id="rs-tools" className="text-sm font-medium">
              Tools
            </span>
            {tools ? (
              <span className="text-xs text-muted-foreground tabular">
                {on.size}/{tools.length}
              </span>
            ) : null}
          </div>
          {toolsError ? (
            <p className="text-xs text-destructive">Could not load tools: {toolsError.message}</p>
          ) : !tools ? (
            <SkeletonRows rows={2} />
          ) : !tools.length ? (
            <p className="text-xs text-muted-foreground">No tools are enabled on this server.</p>
          ) : (
            <div className="divide-y rounded-lg border" role="group" aria-labelledby="rs-tools">
              {tools.map((t) => (
                <label
                  key={t.name}
                  htmlFor={`rs-tool-${t.name}`}
                  className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-muted/50"
                  title={t.description}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-mono text-xs font-medium">{t.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{t.description || t.category}</span>
                  </span>
                  <Switch
                    id={`rs-tool-${t.name}`}
                    checked={on.has(t.name)}
                    onCheckedChange={(checked) => {
                      const next = new Set(on);
                      if (checked) next.add(t.name);
                      else next.delete(t.name);
                      onChange({ ...value, tools: tools.map((x) => x.name).filter((n) => next.has(n)) });
                    }}
                  />
                </label>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <Label htmlFor="rs-steps">Max steps</Label>
            <span className="text-xs text-muted-foreground tabular">{value.max_steps}</span>
          </div>
          <div className="flex items-center gap-3">
            <Slider
              min={1}
              max={20}
              step={1}
              value={[Math.min(20, value.max_steps)]}
              onValueChange={([v]) => setSteps(v)}
              aria-label="Max steps"
              className="flex-1"
            />
            <Input
              id="rs-steps"
              type="number"
              min={1}
              max={50}
              value={value.max_steps}
              onChange={(e) => setSteps(Number(e.target.value))}
              className="h-8 w-16 tabular"
              aria-label="Max steps (exact)"
            />
          </div>
          <p className="text-xs text-muted-foreground">Upper bound on model calls per turn.</p>
        </section>

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="rs-system">System prompt</Label>
            <span className="text-xs text-muted-foreground tabular">
              {value.system_prompt ? `${value.system_prompt.length} chars` : "default"}
            </span>
          </div>
          <Textarea
            id="rs-system"
            rows={6}
            value={value.system_prompt}
            placeholder="Use the server's default system prompt"
            onChange={(e) => onChange({ ...value, system_prompt: e.target.value })}
            className="text-sm"
          />
        </section>

        <section className="space-y-2">
          <Button variant="outline" size="sm" onClick={() => onChange({ ...DEFAULT_SETTINGS })}>
            <RotateCcwIcon /> Reset to defaults
          </Button>
          <p className="text-xs text-muted-foreground">Settings apply to the next message and are saved in this browser.</p>
        </section>
      </div>
    </div>
  );
}
