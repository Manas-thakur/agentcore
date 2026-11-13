import * as React from "react";
import { cn } from "cn";
import { CircleHelpIcon, SearchIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { FIELDS, applySuggestion, isSoftError, suggest, type Suggestion } from "@/lib/query";
import type { FacetValue } from "@/lib/types";

/**
 * Query bar for the trace query language with autocomplete (fields, then facet values with
 * counts). Enter or Tab accepts a suggestion; Enter without one applies the query.
 */
export function QueryBar({
  value,
  onChange,
  onApply,
  facets,
  error,
  inputRef,
}: {
  value: string;
  onChange: (v: string) => void;
  onApply: (v: string) => void;
  facets: Record<string, FacetValue[]>;
  error: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const [caret, setCaret] = React.useState(value.length);
  const [focused, setFocused] = React.useState(false);
  const [active, setActive] = React.useState(-1);
  const [dismissed, setDismissed] = React.useState(false);
  const [help, setHelp] = React.useState(false);
  const listId = React.useId();

  const items: Suggestion[] = focused && !dismissed ? suggest(value, caret, facets, !value.trim()) : [];
  const open = items.length > 0;
  const soft = error ? isSoftError(error) : false;

  const accept = (s: Suggestion) => {
    const next = applySuggestion(value, s);
    onChange(next.value);
    setActive(-1);
    requestAnimationFrame(() => {
      inputRef.current?.setSelectionRange(next.caret, next.caret);
      setCaret(next.caret);
    });
    if (!s.keepOpen) {
      setDismissed(true);
      onApply(next.value);
    }
  };

  const syncCaret = () => setCaret(inputRef.current?.selectionStart ?? value.length);

  return (
    <div className="space-y-1.5" role="search">
      <Popover open={open}>
        <PopoverAnchor asChild>
          <div
            className={cn(
              "flex h-9 items-center gap-2 rounded-lg border bg-card px-2.5 shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30",
              error && !soft && "border-destructive focus-within:border-destructive focus-within:ring-destructive/20",
            )}
          >
            <SearchIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <input
              ref={inputRef}
              value={value}
              spellCheck={false}
              autoComplete="off"
              role="combobox"
              aria-label="Trace query"
              aria-expanded={open}
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
              aria-invalid={Boolean(error && !soft) || undefined}
              aria-describedby={`${listId}-msg`}
              aria-keyshortcuts="/"
              placeholder="status:error -model:mock tool:calculator latency:>1s or free text"
              className="h-full min-w-0 flex-1 bg-transparent font-mono text-[13px] outline-none placeholder:font-sans placeholder:text-muted-foreground"
              onChange={(e) => {
                onChange(e.target.value);
                setCaret(e.target.selectionStart ?? e.target.value.length);
                setActive(-1);
                setDismissed(false);
              }}
              onFocus={() => {
                setFocused(true);
                setDismissed(false);
                syncCaret();
              }}
              onBlur={() => setTimeout(() => setFocused(false), 120)}
              onClick={() => {
                syncCaret();
                setDismissed(false);
              }}
              onKeyUp={(e) => {
                if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home" || e.key === "End") syncCaret();
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" && open) {
                  e.preventDefault();
                  setActive((a) => (a + 1) % items.length);
                } else if (e.key === "ArrowUp" && open) {
                  e.preventDefault();
                  setActive((a) => (a <= 0 ? items.length - 1 : a - 1));
                } else if ((e.key === "Tab" || e.key === "Enter") && open && active >= 0) {
                  e.preventDefault();
                  accept(items[active]);
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  setDismissed(true);
                  onApply(value);
                } else if (e.key === "Escape") {
                  e.stopPropagation();
                  e.preventDefault();
                  if (open) setDismissed(true);
                  else e.currentTarget.blur();
                }
              }}
            />
            {value ? (
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Clear query"
                onClick={() => {
                  onChange("");
                  onApply("");
                  inputRef.current?.focus();
                }}
              >
                <XIcon />
              </Button>
            ) : null}
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Query syntax help"
              aria-expanded={help}
              onClick={() => setHelp((h) => !h)}
            >
              <CircleHelpIcon />
            </Button>
          </div>
        </PopoverAnchor>
        <PopoverContent
          align="start"
          sideOffset={4}
          className="w-[var(--radix-popper-anchor-width)] max-w-[min(36rem,calc(100vw-2rem))] p-1"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onInteractOutside={() => setDismissed(true)}
        >
          <ul id={listId} role="listbox" aria-label="Suggestions" className="max-h-72 overflow-y-auto">
            {items.map((s, i) => (
              <li
                key={`${s.label}-${i}`}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  accept(s);
                }}
                onMouseMove={() => setActive(i)}
                className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-sm aria-selected:bg-accent"
              >
                <span className="font-mono text-[13px]">{s.label}</span>
                <span className="ml-auto truncate text-xs text-muted-foreground">{s.desc}</span>
              </li>
            ))}
          </ul>
        </PopoverContent>
      </Popover>
      <div id={`${listId}-msg`} aria-live="polite" className="min-h-0 text-xs">
        {error ? (
          <p className={soft ? "text-muted-foreground" : "text-destructive"}>{soft ? `Keep typing: ${error}` : error}</p>
        ) : help ? (
          <p className="leading-relaxed text-muted-foreground">
            Fields:{" "}
            {FIELDS.map((f, i) => (
              <React.Fragment key={f.name}>
                {i ? ", " : ""}
                <code className="font-mono text-foreground">{f.name}</code>
              </React.Fragment>
            ))}
            . Prefix with <code className="font-mono text-foreground">-</code> to exclude, use{" "}
            <code className="font-mono text-foreground">,</code> for any-of, <code className="font-mono text-foreground">*</code>{" "}
            as a wildcard, <code className="font-mono text-foreground">&gt;</code> /{" "}
            <code className="font-mono text-foreground">&lt;=</code> for numbers (
            <code className="font-mono text-foreground">latency:&gt;1.5s</code>). Anything else searches id, name, model,
            input, output and error.
          </p>
        ) : null}
      </div>
    </div>
  );
}
