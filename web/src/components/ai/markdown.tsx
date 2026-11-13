import * as React from "react";
import { cn } from "cn";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CodeView } from "@/components/app/code-view";

// react-markdown never renders raw HTML (no rehype-raw), so model output cannot inject markup.
const components: Components = {
  pre({ children }) {
    return <>{children}</>;
  },
  code({ className, children, ...props }) {
    const lang = /language-(\w+)/.exec(className || "")?.[1];
    const text = String(children ?? "");
    const block = Boolean(lang) || text.includes("\n");
    if (!block) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return <CodeView code={text.replace(/\n$/, "")} language={lang || "text"} className="my-1" />;
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    );
  },
};

export const Markdown = React.memo(function Markdown({
  children,
  className,
  streaming,
}: {
  children: string;
  className?: string;
  streaming?: boolean;
}) {
  return (
    <div
      className={cn(
        "prose-agent",
        streaming && "[&>*:last-child]:streaming-caret",
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
});
