import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * Markdown renderer for model answers and markdown artifacts.
 * `react-markdown` is used without `rehype-raw`, so embedded HTML in model
 * output is never injected into the page DOM.
 */
export function MarkdownView({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("space-y-3 text-[13.5px] leading-relaxed text-foreground/95", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (props) => (
            <h1 className="mt-4 mb-2 text-lg font-bold tracking-tight text-foreground" {...props} />
          ),
          h2: (props) => (
            <h2
              className="mt-3 mb-1.5 text-base font-semibold tracking-tight text-foreground"
              {...props}
            />
          ),
          h3: (props) => (
            <h3 className="mt-2.5 mb-1 text-sm font-semibold text-foreground" {...props} />
          ),
          p: (props) => <p className="leading-relaxed" {...props} />,
          ul: (props) => <ul className="ml-4 list-disc space-y-1 text-foreground/90" {...props} />,
          ol: (props) => (
            <ol className="ml-4 list-decimal space-y-1 text-foreground/90" {...props} />
          ),
          strong: (props) => <strong className="font-semibold text-foreground" {...props} />,
          blockquote: (props) => (
            <blockquote
              className="border-l-2 border-primary/50 pl-3 py-0.5 text-xs text-muted-foreground italic leading-relaxed"
              {...props}
            />
          ),
          code: ({ className: codeClass, ...props }) => (
            <code
              className={cn(
                "rounded bg-muted/80 px-1.5 py-0.5 font-mono text-[11.5px] text-foreground font-medium",
                codeClass,
              )}
              {...props}
            />
          ),
          pre: (props) => (
            <pre
              className="overflow-x-auto rounded-lg border border-border/80 bg-muted/40 p-3.5 font-mono text-[11.5px] leading-relaxed text-foreground shadow-2xs"
              {...props}
            />
          ),
          a: (props) => (
            <a
              className="text-primary underline underline-offset-2 hover:text-primary/80 transition-colors font-medium"
              target="_blank"
              rel="noreferrer noopener"
              {...props}
            />
          ),
          table: (props) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-border/80">
              <table className="w-full border-collapse text-left text-xs" {...props} />
            </div>
          ),
          th: (props) => (
            <th
              className="border-b border-border bg-muted/40 px-3 py-2 font-semibold text-foreground"
              {...props}
            />
          ),
          td: (props) => (
            <td
              className="border-b border-border/60 px-3 py-2 text-foreground/90 last:border-b-0"
              {...props}
            />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
