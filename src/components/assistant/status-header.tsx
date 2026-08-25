import { Activity, CircleAlert, CircleCheck, Compass, MessageSquare, PanelRight, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { API_BASE_URL } from "@/lib/api/client";
import type { Health } from "@/lib/api/schemas";

/** Header: app identity, active provider/model, agent runtime, backend status. */
export function StatusHeader({
  health,
  isDisconnected,
  isLoading,
  onToggleArtifact,
  onToggleSessions,
  artifactCount,
}: {
  health: Health | undefined;
  isDisconnected: boolean;
  isLoading: boolean;
  onToggleArtifact: () => void;
  onToggleSessions?: () => void;
  artifactCount: number;
}) {
  const status = isDisconnected ? "error" : (health?.status ?? (isLoading ? "loading" : "error"));
  const retrieval = health?.components?.["retrieval"];
  const chunks = Number(retrieval?.extra?.["chunks"] ?? 0);

  return (
    <header className="flex h-13 shrink-0 items-center justify-between border-b border-border/70 bg-card/75 px-4 backdrop-blur-md">
      <div className="flex min-w-0 items-center gap-3">
        <div
          aria-hidden
          className="flex size-7 items-center justify-center rounded-lg bg-foreground/5 border border-border/80 text-foreground"
        >
          <Compass className="size-4 text-foreground/85" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-xs font-semibold tracking-tight text-foreground sm:text-sm">
              The Lenny Growth Assistant
            </h1>
            <span className="hidden items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground sm:inline-flex">
              <Sparkles className="size-2.5 text-primary/70" /> 50 Transcripts
            </span>
          </div>
          <p className="hidden truncate text-[11px] text-muted-foreground md:block">
            Grounded product &amp; growth intelligence
          </p>
        </div>
      </div>

      <TooltipProvider>
        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="hidden cursor-pointer items-center gap-1.5 rounded-md border border-border/80 bg-muted/30 px-2.5 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 sm:inline-flex">
                <Activity className="size-3 text-muted-foreground/80" aria-hidden />
                <span>{health ? `${health.provider}/${health.model}` : "initializing"}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs text-xs">
              {health ? (
                <span>
                  Agent runtime: {health.agent_runtime}. Embeddings: {health.embedding_model}.{" "}
                  {chunks} transcript chunks indexed.
                </span>
              ) : (
                <span>Provider and model are reported by GET /health.</span>
              )}
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <div
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border/80 bg-muted/30 px-2.5 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-muted/60"
                data-testid="connection-status"
              >
                <span className="relative flex size-2">
                  {status === "ok" ? (
                    <>
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75 duration-1000" />
                      <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
                    </>
                  ) : status === "loading" ? (
                    <span className="relative inline-flex size-2 animate-pulse rounded-full bg-amber-400" />
                  ) : (
                    <span className="relative inline-flex size-2 rounded-full bg-red-500" />
                  )}
                </span>
                <span className="capitalize text-muted-foreground">
                  {status === "loading" ? "connecting" : status === "ok" ? "connected" : "offline"}
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs text-xs">
              <span className="font-mono">{API_BASE_URL}</span>
              {health ? (
                <ul className="mt-1 space-y-0.5">
                  {Object.entries(health.components).map(([name, component]) => (
                    <li key={name}>
                      {name}: {component.status}
                      {component.detail ? ` — ${component.detail}` : ""}
                    </li>
                  ))}
                </ul>
              ) : null}
            </TooltipContent>
          </Tooltip>

          {onToggleSessions ? (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 text-xs md:hidden"
              onClick={onToggleSessions}
              aria-label="Open conversation history"
            >
              <MessageSquare className="size-3.5" aria-hidden />
              <span>Chats</span>
            </Button>
          ) : null}

          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 text-xs lg:hidden"
            onClick={onToggleArtifact}
            disabled={artifactCount === 0}
          >
            <PanelRight className="size-3.5" aria-hidden />
            Artifacts ({artifactCount})
          </Button>
        </div>
      </TooltipProvider>
    </header>
  );
}
