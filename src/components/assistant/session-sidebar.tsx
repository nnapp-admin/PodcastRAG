import { MessageSquare, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatSession } from "@/lib/api/schemas";
import { cn } from "@/lib/utils";

/** Session history. Each session is an independent conversation server-side. */
export function SessionSidebar({
  sessions,
  activeSessionId,
  isLoading,
  isDisconnected,
  onNewChat,
  onSelect,
  onDelete,
  creating,
}: {
  sessions: ChatSession[];
  activeSessionId: string | null;
  isLoading: boolean;
  isDisconnected: boolean;
  onNewChat: () => void;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  creating: boolean;
}) {
  return (
    <nav aria-label="Chat sessions" className="flex h-full min-h-0 flex-col gap-3 p-3">
      <Button
        onClick={onNewChat}
        disabled={creating || isDisconnected}
        variant="outline"
        className="h-8.5 w-full justify-start gap-2 border-border/80 bg-background px-3 text-xs font-medium text-foreground shadow-xs transition-all hover:bg-accent hover:text-accent-foreground"
      >
        <Plus className="size-3.5" aria-hidden />
        <span>New conversation</span>
      </Button>

      <div className="flex items-center justify-between px-1 pt-1">
        <span className="text-[10px] font-semibold tracking-wider text-muted-foreground/70 uppercase">
          History
        </span>
        {sessions.length > 0 ? (
          <span className="font-mono text-[10px] text-muted-foreground/60">{sessions.length}</span>
        ) : null}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <ul className="w-full min-w-0 space-y-0.5 pr-1">
          {isLoading ? (
            <div className="space-y-1.5 pt-1">
              <Skeleton className="h-8 w-full rounded-md" />
              <Skeleton className="h-8 w-full rounded-md" />
              <Skeleton className="h-8 w-full rounded-md" />
            </div>
          ) : null}

          {!isLoading && sessions.length === 0 ? (
            <li className="px-2 py-8 text-center text-xs text-muted-foreground">
              {isDisconnected
                ? "Session history loads once the backend is reachable."
                : "No conversations yet."}
            </li>
          ) : null}

          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <li key={session.id} className="w-full min-w-0">
                <div
                  className={cn(
                    "flex w-full min-w-0 items-center justify-between rounded-md border border-transparent transition-colors",
                    isActive
                      ? "border-border/80 bg-accent/80 font-medium text-foreground shadow-2xs"
                      : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(session.id)}
                    aria-current={isActive}
                    className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <MessageSquare className="size-3.5 shrink-0 opacity-70" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{session.title}</span>
                  </button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="mr-1.5 size-6 shrink-0 rounded-sm text-muted-foreground/70 hover:bg-destructive/10 hover:text-destructive focus-visible:ring-1 focus-visible:ring-ring"
                    aria-label={`Delete conversation ${session.title}`}
                    title="Delete conversation"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onDelete(session.id);
                    }}
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </nav>
  );
}
