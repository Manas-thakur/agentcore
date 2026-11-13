import { SHORTCUTS } from "@/app/nav";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Kbd, KbdGroup } from "@/components/ui/kbd";

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Single-key shortcuts work when you are not typing in a field.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-6 sm:grid-cols-2">
          {SHORTCUTS.map((g) => (
            <section key={g.group} className="space-y-2">
              <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{g.group}</h3>
              <dl className="space-y-1.5">
                {g.keys.map(([keys, desc]) => (
                  <div key={desc} className="flex items-center justify-between gap-4 text-sm">
                    <dt className="text-muted-foreground">{desc}</dt>
                    <dd>
                      <KbdGroup>
                        {keys.map((k) => (
                          <Kbd key={k}>{k}</Kbd>
                        ))}
                      </KbdGroup>
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
