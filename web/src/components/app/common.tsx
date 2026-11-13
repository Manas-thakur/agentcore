import * as React from "react";
import { cn } from "cn";
import { AlertTriangleIcon, RotateCwIcon, type LucideIcon } from "lucide-react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";

export function PageHeader({
  title,
  description,
  actions,
  className,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-x-6 gap-y-3", className)}>
      <div className="min-w-0 space-y-1">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="max-w-2xl text-sm text-muted-foreground">{description}</p> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Page({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("mx-auto w-full max-w-7xl space-y-6 p-4 md:p-6", className)} {...props} />;
}

export function StatusDot({
  status,
  label = true,
  className,
}: {
  status: string;
  label?: boolean;
  className?: string;
}) {
  const ok = status === "ok" || status === "completed" || status === "pass";
  const running = status === "running" || status === "queued";
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
      <span
        aria-hidden="true"
        className={cn(
          "size-2 shrink-0 rounded-full",
          ok ? "bg-success" : running ? "animate-pulse bg-brand" : "bg-destructive",
        )}
      />
      {label ? (
        <span className={cn(ok ? "text-muted-foreground" : running ? "text-foreground" : "text-destructive")}>
          {status}
        </span>
      ) : (
        <span className="sr-only">{status}</span>
      )}
    </span>
  );
}

export type SpanKind = "agent" | "step" | "model" | "tool" | "other";

export const kindColor: Record<SpanKind, string> = {
  agent: "bg-span-agent",
  step: "bg-span-step",
  model: "bg-span-model",
  tool: "bg-span-tool",
  other: "bg-muted-foreground",
};

export function KindDot({ kind, error, className }: { kind: SpanKind; error?: boolean; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block size-2 shrink-0 rounded-[3px]",
        error ? "bg-destructive" : kindColor[kind],
        className,
      )}
    />
  );
}

/** Compact label/value chip used for trace and eval metadata. */
export function Pill({
  label,
  value,
  tone,
  title,
  href,
  className,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "error";
  title?: string;
  href?: string;
  className?: string;
}) {
  const cls = cn(
    "inline-flex h-6 max-w-full items-center gap-1.5 rounded-md border bg-card px-2 text-xs",
    tone === "error" && "border-destructive/40 text-destructive",
    href && "transition-colors hover:bg-muted",
    className,
  );
  const inner = (
    <>
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-medium tabular">{value}</span>
    </>
  );
  if (href)
    return (
      <Link to={href} className={cls} title={title}>
        {inner}
      </Link>
    );
  return (
    <span className={cls} title={title}>
      {inner}
    </span>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <Empty className={cn("border border-dashed py-10", className)}>
      <EmptyHeader>
        {Icon ? (
          <EmptyMedia variant="icon">
            <Icon />
          </EmptyMedia>
        ) : null}
        <EmptyTitle>{title}</EmptyTitle>
        {description ? <EmptyDescription>{description}</EmptyDescription> : null}
      </EmptyHeader>
      {children ? <EmptyContent>{children}</EmptyContent> : null}
    </Empty>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const err = error as Error;
  const offline = err instanceof ApiError && err.status === 0;
  return (
    <Empty className={cn("border border-dashed border-destructive/30 py-10", className)} role="alert">
      <EmptyHeader>
        <EmptyMedia variant="icon" className="bg-destructive/10 text-destructive">
          <AlertTriangleIcon />
        </EmptyMedia>
        <EmptyTitle>{offline ? "Server unreachable" : "Something went wrong"}</EmptyTitle>
        <EmptyDescription className="break-words">{err?.message || String(error)}</EmptyDescription>
      </EmptyHeader>
      {onRetry ? (
        <EmptyContent>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCwIcon /> Try again
          </Button>
        </EmptyContent>
      ) : null}
    </Empty>
  );
}

export function SkeletonRows({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-8 w-full" style={{ opacity: 1 - i * (0.7 / rows) }} />
      ))}
    </div>
  );
}

export function SectionTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("text-[11px] font-medium tracking-wide text-muted-foreground uppercase", className)}
      {...props}
    />
  );
}

/** A bordered panel with an optional header row. */
export function Panel({
  title,
  description,
  actions,
  className,
  bodyClassName,
  children,
  ...props
}: Omit<React.ComponentProps<"section">, "title"> & {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-xl border bg-card text-card-foreground", className)} {...props}>
      {title || actions ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-3">
          <div className="min-w-0 flex-1">
            {title ? <h2 className="text-sm font-semibold">{title}</h2> : null}
            {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
