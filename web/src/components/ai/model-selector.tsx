import * as React from "react";
import { cn } from "cn";
import { BoxIcon, CheckIcon, ChevronsUpDownIcon, CloudIcon, CpuIcon, ServerIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ModelInfo } from "@/lib/types";

/** How a model spec is served: by its prefix (mock, ollama:, openai: and aliases). */
export function modelProvider(id: string): { label: string; icon: typeof CpuIcon } {
  if (id === "mock" || id.startsWith("mock")) return { label: "Offline", icon: BoxIcon };
  if (id === "auto") return { label: "Auto", icon: CpuIcon };
  if (id.startsWith("ollama:")) return { label: "Local (Ollama)", icon: ServerIcon };
  return { label: "OpenAI-compatible", icon: CloudIcon };
}

/**
 * Model Selector pattern: the models the server knows about (GET /v1/models: default, configured
 * `models`, `mock`, local Ollama models) plus any spec typed in, e.g. `openai:<model>`.
 */
export function ModelSelector({
  value,
  onChange,
  models,
  defaultModel,
  className,
  size = "sm",
  align = "start",
  id,
}: {
  value: string;
  onChange: (v: string) => void;
  models: ModelInfo[];
  defaultModel?: string;
  className?: string;
  size?: "sm" | "default";
  align?: "start" | "end";
  id?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const groups = React.useMemo(() => {
    const out = new Map<string, ModelInfo[]>();
    for (const m of models) {
      const g = modelProvider(m.id).label;
      out.set(g, [...(out.get(g) || []), m]);
    }
    return [...out.entries()];
  }, [models]);
  const typed = search.trim();
  const custom = typed && !models.some((m) => m.id === typed) ? typed : "";
  const shown = value || defaultModel || "server default";
  const Icon = modelProvider(value || defaultModel || "mock").icon;

  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    setSearch("");
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant="outline"
          size={size}
          role="combobox"
          aria-expanded={open}
          aria-label={`Model: ${shown}${value ? "" : " (server default)"}`}
          className={cn("min-w-0 justify-between gap-1.5 font-mono font-normal", className)}
        >
          <Icon className="text-muted-foreground" />
          <span className="truncate">{shown}</span>
          {!value ? <span className="font-sans text-muted-foreground">default</span> : null}
          <ChevronsUpDownIcon className="ml-auto text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align={align}>
        <Command>
          <CommandInput
            placeholder="Search or type a spec…"
            value={search}
            onValueChange={setSearch}
            onKeyDown={(e) => {
              if (e.key === "Enter" && custom && !document.querySelector("[cmdk-item][data-selected=true]")) {
                e.preventDefault();
                pick(custom);
              }
            }}
          />
          <CommandList>
            <CommandEmpty>No known model. Type a spec like ollama:&lt;model&gt;.</CommandEmpty>
            <CommandGroup heading="Server">
              <CommandItem value="__default__ server default" onSelect={() => pick("")}>
                <CheckIcon className={cn(value ? "opacity-0" : "opacity-100")} />
                <span>Server default</span>
                {defaultModel ? (
                  <span className="ml-auto truncate font-mono text-xs text-muted-foreground">{defaultModel}</span>
                ) : null}
              </CommandItem>
            </CommandGroup>
            {groups.map(([label, list]) => (
              <CommandGroup key={label} heading={label}>
                {list.map((m) => (
                  <CommandItem key={m.id} value={m.id} onSelect={() => pick(m.id)} className="font-mono">
                    <CheckIcon className={cn(value === m.id ? "opacity-100" : "opacity-0")} />
                    <span className="truncate">{m.id}</span>
                    {m.default ? <span className="ml-auto font-sans text-xs text-muted-foreground">default</span> : null}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
            {custom ? (
              <>
                <CommandSeparator />
                <CommandGroup heading="Custom spec">
                  <CommandItem value={`__custom__ ${custom}`} onSelect={() => pick(custom)} className="font-mono">
                    <CpuIcon />
                    Use “{custom}”
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
        <p className="border-t px-3 py-2 text-xs text-muted-foreground">
          Specs: <code className="font-mono">mock</code>, <code className="font-mono">ollama:&lt;model&gt;</code>,{" "}
          <code className="font-mono">openai:&lt;model&gt;</code>
        </p>
      </PopoverContent>
    </Popover>
  );
}
