import { cn } from "cn";
import { MinusIcon, PlusIcon } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { fmtNum } from "@/lib/format";
import { selected, setValues, toggleValue } from "@/lib/query";
import type { FacetValue } from "@/lib/types";

export const FACET_FIELDS = ["status", "kind", "model", "tool", "name"] as const;
const LABELS: Record<string, string> = { status: "Status", kind: "Source", model: "Model", tool: "Tool", name: "Root name" };

export function activeFacetCount(query: string): number {
  return FACET_FIELDS.reduce((a, f) => a + selected(query, f).length + selected(query, f, true).length, 0);
}

/**
 * Facet sidebar with per-value counts. Counts for a field ignore that field's own clauses
 * (disjunctive faceting). Checkboxes and the exclude button only edit the query string.
 */
export function Facets({
  facets,
  query,
  onQuery,
}: {
  facets: Record<string, FacetValue[]>;
  query: string;
  onQuery: (q: string) => void;
}) {
  let any = false;
  const sections = FACET_FIELDS.map((field) => {
    const values = facets[field] || [];
    const inc = selected(query, field);
    const exc = selected(query, field, true);
    if (!values.length && !inc.length && !exc.length) return null;
    any = true;
    const shown: FacetValue[] = values.filter((v) => v.value !== null);
    for (const v of [...inc, ...exc]) if (!shown.some((x) => x.value === v)) shown.push({ value: v, count: 0 });
    const max = Math.max(1, ...shown.map((v) => v.count));
    const more = values.find((v) => v.value === null);
    const headId = `facet-${field}`;
    return (
      <section key={field} className="space-y-1">
        <div className="flex h-6 items-center justify-between px-1">
          <h3 id={headId} className="text-xs font-medium text-muted-foreground">
            {LABELS[field]}
          </h3>
          {inc.length || exc.length ? (
            <button
              type="button"
              className="text-xs text-brand hover:underline"
              onClick={() => onQuery(setValues(setValues(query, field, []), field, [], true))}
            >
              Clear
            </button>
          ) : null}
        </div>
        <ul aria-labelledby={headId} className="space-y-px">
          {shown.map((v) => {
            const value = v.value as string;
            const checked = inc.includes(value);
            const excluded = exc.includes(value);
            const id = `fv-${field}-${value}`.replace(/[^\w-]/g, "_");
            return (
              <li key={value} className="group/fv relative">
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0.5 left-0 rounded bg-muted"
                  style={{ width: `${(v.count / max) * 100}%` }}
                />
                <div className="relative flex h-7 items-center gap-2 rounded px-1.5 text-xs hover:bg-muted/60">
                  <Checkbox
                    id={id}
                    checked={checked}
                    onCheckedChange={() => onQuery(toggleValue(query, field, value))}
                    aria-label={`${LABELS[field]} ${value}`}
                  />
                  <label
                    htmlFor={id}
                    title={`${value} · ${v.count}`}
                    className={cn(
                      "min-w-0 flex-1 cursor-pointer truncate",
                      field !== "status" && field !== "kind" && "font-mono",
                      excluded && "text-muted-foreground line-through",
                    )}
                  >
                    {field === "status" ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span className={cn("size-2 rounded-full", value === "ok" ? "bg-success" : "bg-destructive")} />
                        {value}
                      </span>
                    ) : (
                      value
                    )}
                  </label>
                  <span className="text-muted-foreground tabular">{fmtNum(v.count)}</span>
                  <button
                    type="button"
                    className="flex size-5 items-center justify-center rounded text-muted-foreground opacity-0 group-hover/fv:opacity-100 hover:bg-background hover:text-foreground focus-visible:opacity-100 pointer-coarse:opacity-100 data-[on=true]:opacity-100"
                    data-on={excluded}
                    aria-label={excluded ? `Stop excluding ${value}` : `Exclude ${value}`}
                    title={excluded ? "Stop excluding" : "Exclude"}
                    onClick={() => onQuery(toggleValue(query, field, value, true))}
                  >
                    {excluded ? <PlusIcon className="size-3" /> : <MinusIcon className="size-3" />}
                  </button>
                </div>
              </li>
            );
          })}
          {more ? (
            <li className="px-1.5 py-1 text-xs text-muted-foreground">
              + {fmtNum(more.count)} in other values (use the query bar)
            </li>
          ) : null}
        </ul>
      </section>
    );
  });
  return (
    <div className="space-y-4">
      {sections}
      {!any ? <p className="px-1 text-xs text-muted-foreground">Facets appear once there are traces.</p> : null}
    </div>
  );
}
