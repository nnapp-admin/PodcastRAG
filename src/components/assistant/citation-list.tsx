import { ExternalLink, Quote } from "lucide-react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import type { Citation } from "@/lib/api/schemas";

/** Per-answer source attribution: episode, guest, timestamp, link, score. */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <Accordion
      type="single"
      collapsible
      className="mt-3 rounded-lg border border-border/70 bg-card/50 shadow-2xs"
    >
      <AccordionItem value="sources" className="border-b-0">
        <AccordionTrigger className="px-3.5 py-2 text-xs font-medium text-muted-foreground hover:text-foreground hover:no-underline">
          <span className="flex items-center gap-2">
            <Quote className="size-3.5 text-primary/70" aria-hidden />
            <span>
              {citations.length} Grounded Source{citations.length === 1 ? "" : "s"}
            </span>
          </span>
        </AccordionTrigger>
        <AccordionContent className="space-y-2.5 px-3.5 pb-3.5">
          {citations.map((citation, index) => (
            <div
              key={citation.chunk_id}
              className="rounded-md border border-border/60 bg-background/60 p-3 shadow-2xs"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] font-semibold text-primary">
                  [{index + 1}]
                </span>
                <span className="text-xs font-semibold text-foreground">
                  {citation.episode_title}
                </span>
                {citation.guest ? (
                  <span className="text-xs text-muted-foreground">· {citation.guest}</span>
                ) : null}
                {citation.start_timestamp ? (
                  <span className="rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    @{citation.start_timestamp}
                  </span>
                ) : null}
                <span className="ml-auto font-mono text-[10px] text-muted-foreground/80">
                  score {citation.score.toFixed(3)}
                </span>
              </div>
              <p className="mt-2 border-l-2 border-primary/30 pl-2.5 text-xs italic leading-relaxed text-muted-foreground">
                “{citation.excerpt.trim()}”
              </p>
              {citation.source_url ? (
                <div className="mt-2 flex justify-end">
                  <a
                    href={citation.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline underline-offset-2"
                  >
                    <span>Listen to episode</span>
                    <ExternalLink className="size-2.5" aria-hidden />
                  </a>
                </div>
              ) : null}
            </div>
          ))}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
