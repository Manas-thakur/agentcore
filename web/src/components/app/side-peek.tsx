import * as React from "react";
import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/hooks";
import { storage } from "@/lib/storage";

/**
 * A list with a resizable side peek on wide screens, and a full-screen sheet on narrow ones.
 * The peek keeps your place in the list (open a row, move with j/k, close with Esc).
 */
export function SplitWithPeek({
  id,
  main,
  peek,
  open,
  onClose,
  label,
  defaultSize = 42,
}: {
  id: string;
  main: React.ReactNode;
  peek: React.ReactNode;
  open: boolean;
  onClose: () => void;
  label: string;
  defaultSize?: number;
}) {
  const wide = useMediaQuery("(min-width: 1024px)");
  const key = `peek.${id}`;
  const [size] = React.useState(() => {
    const v = Number(storage.get<number>(key, defaultSize));
    return Number.isFinite(v) && v >= 20 && v <= 75 ? v : defaultSize;
  });

  if (!wide) {
    return (
      <>
        <div className="h-full min-h-0 overflow-auto">{main}</div>
        <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
          <SheetContent side="right" className="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-full" showCloseButton={false}>
            <SheetTitle className="sr-only">{label}</SheetTitle>
            <SheetDescription className="sr-only">{label}</SheetDescription>
            <div className="flex h-full min-h-0 flex-col">{peek}</div>
          </SheetContent>
        </Sheet>
      </>
    );
  }

  return (
    <ResizablePanelGroup
      id={`group-${id}`}
      orientation="horizontal"
      className="min-h-0"
      onLayoutChanged={(layout, meta) => {
        if (meta?.isUserInteraction && layout[`${id}-peek`]) storage.set(key, Math.round(layout[`${id}-peek`]));
      }}
    >
      <ResizablePanel id={`${id}-main`} minSize={360} className="min-w-0">
        <div className="h-full min-h-0 overflow-auto">{main}</div>
      </ResizablePanel>
      {open ? (
        <>
          <ResizableHandle withHandle aria-label={`Resize ${label.toLowerCase()}`} />
          <ResizablePanel id={`${id}-peek`} defaultSize={`${size}`} minSize={340} maxSize="75" className="min-w-0">
            <aside aria-label={label} className="flex h-full min-h-0 flex-col bg-background">
              {peek}
            </aside>
          </ResizablePanel>
        </>
      ) : null}
    </ResizablePanelGroup>
  );
}

/** Header row for a peek: title area, actions and a close button. */
export function PeekHeader({
  children,
  actions,
  onClose,
}: {
  children: React.ReactNode;
  actions?: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <div className="flex min-w-0 flex-1 items-center gap-2">{children}</div>
      {actions}
      <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close (Esc)" title="Close (Esc)">
        <XIcon />
      </Button>
    </div>
  );
}
