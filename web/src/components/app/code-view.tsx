import { cn } from "cn";

import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockHeader,
  CodeBlockTitle,
} from "@/components/ui/code-block";
import { useHighlightedCode } from "@/hooks/use-highlighted-code";
import { parseMaybeJson, pretty } from "@/lib/format";

/** Syntax-highlighted code with a copy button (shiki, loaded on first use). */
export function CodeView({
  code,
  language = "json",
  title,
  wrap = true,
  size = "sm",
  className,
  contentClassName,
  variant,
}: {
  code: string;
  language?: string;
  title?: React.ReactNode;
  wrap?: boolean;
  size?: "sm" | "default";
  className?: string;
  contentClassName?: string;
  variant?: "default" | "destructive";
}) {
  const lines = useHighlightedCode(code, language);
  return (
    <CodeBlock size={size} variant={variant} className={cn("bg-muted/40", className)}>
      {title ? (
        <CodeBlockHeader>
          <CodeBlockTitle>{title}</CodeBlockTitle>
          <CodeBlockActions>
            <CodeBlockCopyButton value={code} />
          </CodeBlockActions>
        </CodeBlockHeader>
      ) : (
        <CodeBlockActions>
          <CodeBlockCopyButton value={code} />
        </CodeBlockActions>
      )}
      <CodeBlockContent wrap={wrap} className={cn("max-h-96", contentClassName)}>
        {lines.map((line, i) => (
          <span key={i} className="block min-h-lh">
            {line}
          </span>
        ))}
      </CodeBlockContent>
    </CodeBlock>
  );
}

/** JSON (or JSON-looking string) pretty-printed and highlighted. */
export function JsonView({ value, ...props }: { value: unknown } & Omit<Parameters<typeof CodeView>[0], "code">) {
  const parsed = parseMaybeJson(value);
  const isObj = parsed !== null && typeof parsed === "object";
  return <CodeView code={isObj ? pretty(parsed) : String(value ?? "")} language={isObj ? "json" : "text"} {...props} />;
}

/** Tool arguments as a definition list (strings shown raw, other values as JSON). */
export function ArgsList({ args }: { args: Record<string, unknown> | undefined | null }) {
  const entries = Object.entries(args || {});
  if (!entries.length) return <p className="text-xs text-muted-foreground">No arguments.</p>;
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-mono text-muted-foreground">{k}</dt>
          <dd className="min-w-0 font-mono break-words whitespace-pre-wrap text-foreground">
            {typeof v === "string" ? v : JSON.stringify(v, null, 2)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
