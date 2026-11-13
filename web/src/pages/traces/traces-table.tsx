import * as React from "react";
import { cn } from "cn";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon } from "lucide-react";

import { StatusDot } from "@/components/app/common";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fmtAgo, fmtCost, fmtMs, fmtNum, fmtTime } from "@/lib/format";
import type { TraceSummary } from "@/lib/types";

export type SortKey = "time" | "name" | "status" | "latency" | "tokens" | "cost" | "model";

interface Meta {
  maxLat: number;
  p95: number;
  rows: number;
}

const columns: ColumnDef<TraceSummary>[] = [
  {
    id: "time",
    header: "Time",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="text-muted-foreground tabular" title={fmtTime(row.original.start_time)}>
        {fmtAgo(row.original.start_time)}
      </span>
    ),
    meta: { className: "w-24" },
  },
  {
    id: "name",
    header: "Name",
    enableSorting: true,
    cell: ({ row }) => <span className="block max-w-[8rem] truncate font-mono text-xs sm:max-w-[14rem]" title={row.original.name}>{row.original.name}</span>,
  },
  {
    id: "status",
    header: "Status",
    enableSorting: true,
    cell: ({ row }) => (
      <>
        <StatusDot status={row.original.status} className="hidden sm:inline-flex" />
        <StatusDot status={row.original.status} label={false} className="sm:hidden" />
      </>
    ),
    meta: { className: "w-12 sm:w-20" },
  },
  {
    id: "latency",
    header: "Latency",
    enableSorting: true,
    cell: ({ row, table }) => {
      const m = table.options.meta as Meta;
      const t = row.original;
      const slow = m.p95 > 0 && t.duration_ms >= m.p95 && m.rows > 2;
      return (
        <span className="flex items-center justify-end gap-2">
          <span className="tabular">{fmtMs(t.duration_ms)}</span>
          <span className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-muted md:block" aria-hidden="true">
            <i
              className={cn("block h-full rounded-full", slow ? "bg-warning" : "bg-chart-1/70")}
              style={{ width: `${(t.duration_ms / m.maxLat) * 100}%` }}
            />
          </span>
        </span>
      );
    },
    meta: { className: "text-right w-36", num: true },
  },
  {
    id: "tokens",
    header: "Tokens",
    enableSorting: true,
    cell: ({ row }) => <span className="tabular">{fmtNum(row.original.total_tokens)}</span>,
    meta: { className: "text-right hidden md:table-cell", num: true },
  },
  {
    id: "cost",
    header: "Cost",
    enableSorting: true,
    cell: ({ row }) => <span className="tabular">{fmtCost(row.original.cost_usd)}</span>,
    meta: { className: "text-right hidden md:table-cell", num: true },
  },
  {
    id: "model",
    header: "Model",
    enableSorting: true,
    cell: ({ row }) => (
      <span className="block max-w-[10rem] truncate font-mono text-xs text-muted-foreground">
        {row.original.model || "-"}
      </span>
    ),
    meta: { className: "hidden lg:table-cell" },
  },
  {
    id: "input",
    header: "Input",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="block max-w-[28rem] truncate text-muted-foreground" title={row.original.input}>
        {row.original.input || "-"}
      </span>
    ),
    meta: { className: "hidden xl:table-cell" },
  },
];

/** Dense, server-sorted trace table (TanStack Table + shadcn Table). */
export function TracesTable({
  rows,
  sort,
  order,
  onSort,
  activeIndex,
  openId,
  onOpen,
  p95,
}: {
  rows: TraceSummary[];
  sort: SortKey;
  order: "asc" | "desc";
  onSort: (key: SortKey, order: "asc" | "desc") => void;
  activeIndex: number;
  openId: string | null;
  onOpen: (index: number) => void;
  p95: number;
}) {
  const sorting: SortingState = [{ id: sort, desc: order === "desc" }];
  const meta: Meta = React.useMemo(
    () => ({ maxLat: Math.max(1, ...rows.map((r) => r.duration_ms)), p95, rows: rows.length }),
    [rows, p95],
  );
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    manualSorting: true,
    enableSortingRemoval: false,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (r) => r.trace_id,
    meta,
  });
  const bodyRef = React.useRef<HTMLTableSectionElement>(null);

  React.useEffect(() => {
    if (activeIndex < 0) return;
    const tr = bodyRef.current?.querySelectorAll("tr")[activeIndex];
    tr?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <Table aria-label="Traces" aria-rowcount={rows.length + 1} className="text-[13px]">
      <TableHeader className="sticky top-0 z-10 bg-background">
        {table.getHeaderGroups().map((hg) => (
          <TableRow key={hg.id} className="hover:bg-transparent">
            {hg.headers.map((h) => {
              const m = h.column.columnDef.meta as { className?: string; num?: boolean } | undefined;
              const sorted = sort === h.column.id;
              return (
                <TableHead
                  key={h.id}
                  className={cn("h-9 text-xs", m?.className)}
                  aria-sort={sorted ? (order === "asc" ? "ascending" : "descending") : undefined}
                >
                  {h.column.getCanSort() ? (
                    <button
                      type="button"
                      className={cn(
                        "-mx-1 inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-muted hover:text-foreground",
                        m?.num && "flex-row-reverse",
                        sorted && "text-foreground",
                      )}
                      onClick={() => {
                        const key = h.column.id as SortKey;
                        if (sorted) onSort(key, order === "desc" ? "asc" : "desc");
                        else onSort(key, ["name", "model", "status"].includes(key) ? "asc" : "desc");
                      }}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {sorted ? (
                        order === "asc" ? (
                          <ArrowUpIcon className="size-3" />
                        ) : (
                          <ArrowDownIcon className="size-3" />
                        )
                      ) : (
                        <ChevronsUpDownIcon className="size-3 opacity-40" />
                      )}
                    </button>
                  ) : (
                    flexRender(h.column.columnDef.header, h.getContext())
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody ref={bodyRef}>
        {table.getRowModel().rows.map((row, i) => {
          const t = row.original;
          const isOpen = t.trace_id === openId;
          const isActive = i === activeIndex;
          return (
            <TableRow
              key={row.id}
              data-state={isOpen ? "selected" : undefined}
              data-active={isActive || undefined}
              tabIndex={isActive || (activeIndex < 0 && i === 0) ? 0 : -1}
              aria-label={`${t.name}, ${t.status}, ${fmtMs(t.duration_ms)}, ${fmtAgo(t.start_time)}`}
              onClick={() => onOpen(i)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.target === e.currentTarget) {
                  e.preventDefault();
                  onOpen(i);
                }
              }}
              className={cn(
                "h-9 cursor-pointer outline-none focus-visible:bg-muted/70 data-[active=true]:shadow-[inset_2px_0_0_var(--brand)]",
                t.status !== "ok" && "bg-destructive/[0.03]",
              )}
            >
              {row.getVisibleCells().map((cell) => {
                const m = cell.column.columnDef.meta as { className?: string } | undefined;
                return (
                  <TableCell key={cell.id} className={cn("py-1.5", m?.className)}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                );
              })}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
