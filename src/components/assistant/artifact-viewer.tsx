import { Code2, Download, Eye, FileText, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { MarkdownView } from "@/components/assistant/markdown-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Artifact } from "@/lib/api/schemas";

/**
 * Artifact viewer.
 *
 * HTML artifacts render inside a sandboxed iframe via `srcdoc`:
 *   - no `allow-scripts` and no `allow-same-origin` => no script execution and
 *     an opaque origin, so the artifact cannot touch the app's DOM, storage or
 *     React state,
 *   - a restrictive CSP meta tag is injected as defence in depth,
 *   - the backend has already sanitized the HTML before persisting it.
 * Markdown artifacts are rendered through react-markdown (no raw HTML pass-through).
 */

const CSP =
  "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none';";

function wrapHtml(content: string) {
  const head = `<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${CSP}"><style>
    :root { color-scheme: light; }
    body { margin: 0; padding: 20px; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1c1917; background: #ffffff; }
    h1,h2,h3 { line-height: 1.25; }
    img { max-width: 100%; height: auto; }
    pre { overflow-x: auto; background: #f5f5f4; padding: 12px; border-radius: 8px; }
  </style>`;
  if (/<html[\s>]/i.test(content)) {
    return content.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${head}`);
  }
  return `<!doctype html><html><head>${head}</head><body>${content}</body></html>`;
}

export function ArtifactViewer({
  artifact,
  artifacts,
  onSelect,
  onClose,
}: {
  artifact: Artifact;
  artifacts: Artifact[];
  onSelect: (artifactId: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"preview" | "code">("preview");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setTab("preview");
  }, [artifact.id]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const srcDoc = useMemo(
    () => (artifact.kind === "html" ? wrapHtml(artifact.content) : ""),
    [artifact.kind, artifact.content],
  );

  function download() {
    const blob = new Blob([artifact.content], {
      type: artifact.kind === "html" ? "text/html" : "text/markdown",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    const safeTitle =
      artifact.title
        .replace(/[^a-z0-9-_]+/gi, "-")
        .replace(/^-+|-+$/g, "")
        .toLowerCase() || "artifact";
    anchor.download = `${safeTitle}.${artifact.kind === "html" ? "html" : "md"}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section
      aria-label="Artifact viewer"
      className="flex h-full min-h-0 flex-col bg-card/60 backdrop-blur-xs"
      data-testid="artifact-viewer"
    >
      <header className="flex items-center justify-between border-b border-border/70 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <FileText className="size-3.5" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xs font-semibold tracking-tight text-foreground sm:text-sm">
              {artifact.title}
            </h2>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <Badge
                variant="outline"
                className="font-mono text-[9px] uppercase tracking-wider px-1 py-0"
              >
                {artifact.kind}
              </Badge>
              <span>{(artifact.byte_size / 1024).toFixed(1)} KB</span>
              {artifact.citations.length > 0 ? (
                <span>· {artifact.citations.length} sources</span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-7 rounded-md text-muted-foreground hover:text-foreground"
            onClick={download}
            aria-label="Download artifact"
          >
            <Download className="size-3.5" aria-hidden />
          </Button>
          <Button
            ref={closeRef}
            variant="ghost"
            size="icon"
            className="size-7 rounded-md text-muted-foreground hover:text-foreground"
            onClick={onClose}
            aria-label="Close artifact viewer (Escape)"
          >
            <X className="size-3.5" aria-hidden />
          </Button>
        </div>
      </header>

      {artifacts.length > 1 ? (
        <div className="flex gap-1 overflow-x-auto border-b border-border/60 bg-muted/20 px-3 py-1.5">
          {artifacts.map((item) => (
            <Button
              key={item.id}
              variant={item.id === artifact.id ? "secondary" : "ghost"}
              size="sm"
              className="h-6.5 shrink-0 rounded-md px-2 text-[11px] font-medium"
              onClick={() => onSelect(item.id)}
              aria-current={item.id === artifact.id}
            >
              {item.title.slice(0, 24)}
            </Button>
          ))}
        </div>
      ) : null}

      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as "preview" | "code")}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="px-4 pt-2.5 pb-1">
          <TabsList className="h-7 w-fit bg-muted/70 p-0.5">
            <TabsTrigger value="preview" className="h-6 gap-1.5 rounded-sm px-2.5 text-[11px]">
              <Eye className="size-3" aria-hidden /> Preview
            </TabsTrigger>
            <TabsTrigger value="code" className="h-6 gap-1.5 rounded-sm px-2.5 text-[11px]">
              <Code2 className="size-3" aria-hidden /> Source
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent
          value="preview"
          className="min-h-0 flex-1 p-0 data-[state=active]:flex data-[state=active]:flex-col"
        >
          {artifact.kind === "html" ? (
            <iframe
              key={artifact.id}
              title={`Artifact preview: ${artifact.title}`}
              // No allow-scripts and no allow-same-origin: fully isolated.
              sandbox=""
              srcDoc={srcDoc}
              className="h-full w-full flex-1 border-0 bg-white"
            />
          ) : (
            <ScrollArea className="h-full flex-1">
              <div className="p-4">
                <MarkdownView>{artifact.content}</MarkdownView>
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        <TabsContent
          value="code"
          className="min-h-0 flex-1 p-0 data-[state=active]:flex data-[state=active]:flex-col"
        >
          <ScrollArea className="h-full flex-1">
            <pre className="p-4 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-foreground/90 bg-muted/20">
              {artifact.content}
            </pre>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </section>
  );
}
