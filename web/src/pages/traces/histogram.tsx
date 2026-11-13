import * as React from "react";
import { Bar, BarChart, CartesianGrid, ReferenceArea, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { fmtTime } from "@/lib/format";
import type { HistogramBucket } from "@/lib/types";

const config = {
  ok: { label: "ok", color: "var(--chart-1)" },
  errors: { label: "failed", color: "var(--destructive)" },
} satisfies ChartConfig;

function tickLabel(t: number, span: number) {
  const d = new Date(t * 1000);
  if (span <= 2 * 86400) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Trace volume over time with failures stacked on top. Drag across the bars (the "brush") to
 * narrow the time window; the selection becomes a since/until filter.
 */
export function TraceHistogram({
  buckets,
  start,
  end,
  bucketSeconds,
  onSelect,
}: {
  buckets: HistogramBucket[];
  start: number;
  end: number;
  bucketSeconds: number;
  onSelect: (since: number, until: number) => void;
}) {
  const data = buckets.map((b) => ({ t: b.t, ok: b.count - b.errors, errors: b.errors, count: b.count }));
  const [drag, setDrag] = React.useState<{ a: number; b: number } | null>(null);
  const span = end - start;

  const finish = () => {
    if (drag && drag.a !== drag.b) {
      const lo = Math.min(drag.a, drag.b);
      const hi = Math.max(drag.a, drag.b) + bucketSeconds;
      onSelect(lo, hi);
    }
    setDrag(null);
  };

  return (
    <ChartContainer
      config={config}
      className="aspect-auto h-28 w-full select-none [&_.recharts-surface]:cursor-crosshair"
      role="img"
      aria-label={`Trace volume from ${fmtTime(start)} to ${fmtTime(end)}. Drag to zoom into a time range.`}
    >
      <BarChart
        data={data}
        barCategoryGap={1}
        margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
        onMouseDown={(s) => {
          const t = s?.activeLabel !== undefined ? Number(s.activeLabel) : null;
          if (t !== null && !Number.isNaN(t)) setDrag({ a: t, b: t });
        }}
        onMouseMove={(s) => {
          if (!drag) return;
          const t = s?.activeLabel !== undefined ? Number(s.activeLabel) : null;
          if (t !== null && !Number.isNaN(t)) setDrag({ ...drag, b: t });
        }}
        onMouseUp={finish}
        onMouseLeave={() => setDrag(null)}
      >
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="t"
          tickLine={false}
          axisLine={false}
          minTickGap={48}
          tickMargin={6}
          tickFormatter={(t: number) => tickLabel(t, span)}
        />
        <YAxis allowDecimals={false} width={28} tickLine={false} axisLine={false} />
        <ChartTooltip
          cursor={{ fill: "var(--muted)" }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const p = payload[0].payload as { t: number; count: number; errors: number };
            return (
              <div className="rounded-lg border bg-popover px-2.5 py-1.5 text-xs shadow-md">
                <div className="font-medium">
                  {fmtTime(p.t)} – {fmtTime(p.t + bucketSeconds)}
                </div>
                <div className="text-muted-foreground">
                  {p.count} trace{p.count === 1 ? "" : "s"}
                  {p.errors ? <span className="text-destructive"> · {p.errors} failed</span> : null}
                </div>
              </div>
            );
          }}
        />
        <Bar dataKey="ok" stackId="a" fill="var(--color-ok)" radius={[0, 0, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="errors" stackId="a" fill="var(--color-errors)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
        {drag && drag.a !== drag.b ? (
          <ReferenceArea
            x1={Math.min(drag.a, drag.b)}
            x2={Math.max(drag.a, drag.b)}
            fill="var(--brand)"
            fillOpacity={0.15}
            stroke="var(--brand)"
            strokeOpacity={0.5}
          />
        ) : null}
      </BarChart>
    </ChartContainer>
  );
}
