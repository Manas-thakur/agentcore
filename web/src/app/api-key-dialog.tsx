import * as React from "react";
import { KeyRoundIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { registerKeyPrompter, setApiKey } from "@/lib/api";

/** Prompts for AGENTCORE_API_KEY when the server answers 401; stored in this browser only. */
export function ApiKeyDialog() {
  const [state, setState] = React.useState<{ message: string; resolve: (ok: boolean) => void } | null>(null);
  const [value, setValue] = React.useState("");
  const [invalid, setInvalid] = React.useState(false);

  React.useEffect(() => {
    registerKeyPrompter(
      (message) =>
        new Promise<boolean>((resolve) => {
          setValue("");
          setInvalid(false);
          setState({ message, resolve });
        }),
    );
    return () => registerKeyPrompter(null);
  }, []);

  const close = (ok: boolean) => {
    state?.resolve(ok);
    setState(null);
  };

  return (
    <Dialog open={state !== null} onOpenChange={(o) => !o && close(false)}>
      <DialogContent className="sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const key = value.trim();
            if (!key) {
              setInvalid(true);
              return;
            }
            setApiKey(key);
            close(true);
          }}
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <KeyRoundIcon className="size-4" /> API key required
            </DialogTitle>
            <DialogDescription>
              This server was started with <code className="font-mono text-xs">AGENTCORE_API_KEY</code>. Enter the
              key once; it is kept in this browser's local storage and sent as a bearer token.
            </DialogDescription>
          </DialogHeader>
          <Field data-invalid={invalid || Boolean(state?.message) || undefined}>
            <FieldLabel htmlFor="api-key">API key</FieldLabel>
            <Input
              id="api-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              autoFocus
              value={value}
              aria-invalid={invalid || undefined}
              onChange={(e) => {
                setValue(e.target.value);
                setInvalid(false);
              }}
            />
            {state?.message ? <FieldError>{state.message}</FieldError> : null}
            {invalid ? <FieldError>Enter the key.</FieldError> : null}
            <FieldDescription>Remove it any time from Settings.</FieldDescription>
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit">Save key</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
