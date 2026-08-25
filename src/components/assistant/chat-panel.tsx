import {
  ArrowRight,
  BookOpen,
  CircleAlert,
  CornerDownLeft,
  FileCode2,
  FileText,
  Loader2,
  Radio,
  ShieldAlert,
  Sparkles,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type React from "react";

import { CitationList } from "@/components/assistant/citation-list";
import { MarkdownView } from "@/components/assistant/markdown-view";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import type { ChatMessage } from "@/lib/api/schemas";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  {
    category: "Product Strategy",
    icon: Sparkles,
    prompt: "What do guests say about finding product-market fit?",
  },
  {
    category: "Growth & Retention",
    icon: Zap,
    prompt: "How should an early team think about growth loops and retention?",
  },
  {
    category: "Ship 30 Essay",
    icon: BookOpen,
    prompt: "Write a Ship 30 for 30 essay about onboarding activation",
  },
];

export function ChatPanel({
  messages,
  isLoadingSession,
  isSending,
  sendError,
  loadError,
  disabled,
  disabledReason,
  onSend,
  onOpenArtifact,
}: {
  messages: ChatMessage[];
  isLoadingSession: boolean;
  isSending: boolean;
  sendError: string | null;
  loadError: string | null;
  disabled: boolean;
  disabledReason: string | null;
  onSend: (message: string) => void;
  onOpenArtifact: (artifactId: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lastMessageRef = useRef<HTMLElement>(null);
  const [sendPhase, setSendPhase] = useState<"retrieving" | "generating" | "finishing">(
    "retrieving",
  );
  const phaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Scroll management: when sending, show the bottom spinner; when done, focus the answer top
  useEffect(() => {
    if (isSending) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    } else if (messages.length > 0 && lastMessageRef.current) {
      lastMessageRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [messages.length, isSending]);

  // Glitch 3 fix: advance status label through realistic phases
  useEffect(() => {
    if (isSending) {
      setSendPhase("retrieving");
      phaseTimerRef.current = setTimeout(() => setSendPhase("generating"), 3_000);
      const finishing = setTimeout(() => setSendPhase("finishing"), 20_000);
      return () => {
        clearTimeout(phaseTimerRef.current ?? undefined);
        clearTimeout(finishing);
      };
    } else {
      setSendPhase("retrieving");
    }
  }, [isSending]);

  // Glitch 4 fix: restore textarea focus once the response lands
  useEffect(() => {
    if (!isSending && !disabled) {
      textareaRef.current?.focus();
    }
  }, [isSending, disabled]);

  function submit() {
    const value = draft.trim();
    if (!value || disabled || isSending) return;
    onSend(value);
    setDraft("");
  }

  return (
    <section aria-label="Conversation" className="flex h-full min-h-0 flex-col bg-background/50">
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8">
          {loadError ? (
            <Alert variant="destructive">
              <CircleAlert className="size-4" aria-hidden />
              <AlertTitle>Could not load this conversation</AlertTitle>
              <AlertDescription>{loadError}</AlertDescription>
            </Alert>
          ) : null}

          {isLoadingSession ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
              <Loader2 className="size-3.5 animate-spin" />
              <span>Loading conversation history…</span>
            </div>
          ) : null}

          {!isLoadingSession && messages.length === 0 && !loadError ? (
            <div className="rounded-xl border border-border/80 bg-card/60 p-6 shadow-2xs backdrop-blur-xs">
              <div className="flex items-center gap-2">
                <span className="flex size-6 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Radio className="size-3.5" />
                </span>
                <h2 className="text-sm font-semibold tracking-tight text-foreground">
                  Grounded Podcast Intelligence
                </h2>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                Query 50 indexed episodes of Lenny&apos;s Podcast. Every claim is strictly grounded
                in transcript evidence with source citations, or cleanly refused when unsupported.
              </p>

              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                {SUGGESTIONS.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.prompt}
                      type="button"
                      disabled={disabled}
                      onClick={() => {
                        setDraft(item.prompt);
                        textareaRef.current?.focus();
                      }}
                      className="group flex flex-col justify-between rounded-lg border border-border/70 bg-background/80 p-3 text-left transition-all hover:border-foreground/20 hover:bg-accent/40 hover:shadow-2xs focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50"
                    >
                      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground group-hover:text-foreground">
                        <Icon className="size-3 text-primary/80" />
                        <span>{item.category}</span>
                      </div>
                      <p className="mt-2 text-xs font-normal text-foreground/90 line-clamp-2">
                        {item.prompt}
                      </p>
                      <div className="mt-2 flex items-center justify-end text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                        <ArrowRight className="size-3" />
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {messages.map((message, index) => {
            const isLast = index === messages.length - 1;
            return message.role === "user" ? (
              <div
                key={message.id}
                ref={isLast ? (lastMessageRef as React.RefObject<HTMLDivElement>) : null}
                className="flex justify-end pt-1"
              >
                <div className="max-w-[85%] rounded-2xl rounded-tr-xs bg-primary px-4 py-2.5 text-[13px] leading-relaxed text-primary-foreground shadow-2xs">
                  {message.content}
                </div>
              </div>
            ) : (
              <article
                key={message.id}
                ref={isLast ? lastMessageRef : null}
                className="space-y-2 pt-1 max-w-none animate-in fade-in duration-300"
              >
                <div className="flex flex-wrap items-center gap-2 pb-1">
                  <div className="flex items-center gap-1.5">
                    <span className="size-1.5 rounded-full bg-emerald-500" />
                    <span className="text-xs font-semibold tracking-tight text-foreground">
                      Assistant
                    </span>
                  </div>
                  {message.capability ? (
                    <Badge
                      variant="outline"
                      className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground"
                    >
                      {message.capability}
                    </Badge>
                  ) : null}
                  {message.grounded ? null : (
                    <Badge variant="destructive" className="gap-1 text-[10px]">
                      <ShieldAlert className="size-3" aria-hidden /> not grounded
                    </Badge>
                  )}
                  {message.model ? (
                    <span className="font-mono text-[10px] text-muted-foreground/70">
                      {message.provider}/{message.model}
                      {message.latency_ms ? ` · ${(message.latency_ms / 1000).toFixed(1)}s` : ""}
                    </span>
                  ) : null}
                </div>

                <div className="rounded-xl border border-border/60 bg-card/40 p-4 shadow-2xs">
                  <MarkdownView>{message.content}</MarkdownView>

                  {message.artifact_id ? (
                    <div className="mt-4 pt-3 border-t border-border/60">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 gap-1.5 border-border/80 bg-background text-xs font-medium text-foreground shadow-2xs hover:bg-accent"
                        onClick={() => onOpenArtifact(message.artifact_id as string)}
                      >
                        <FileCode2 className="size-3.5 text-primary" aria-hidden />
                        <span>Open generated artifact</span>
                      </Button>
                    </div>
                  ) : null}

                  <CitationList citations={message.citations} />
                </div>
              </article>
            );
          })}

          {isSending ? (
            <div
              className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-card/40 px-3.5 py-2.5 text-xs text-muted-foreground shadow-2xs animate-in fade-in duration-200"
              role="status"
              aria-live="polite"
            >
              <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
              <span>
                {sendPhase === "retrieving"
                  ? "Searching transcript index…"
                  : sendPhase === "generating"
                    ? "Drafting a grounded answer…"
                    : "Finishing up…"}
              </span>
            </div>
          ) : null}

          {sendError ? (
            <Alert variant="destructive">
              <CircleAlert className="size-4" aria-hidden />
              <AlertTitle>The assistant could not answer</AlertTitle>
              <AlertDescription>{sendError}</AlertDescription>
            </Alert>
          ) : null}

          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <div className="border-t border-border/70 bg-card/75 px-4 py-3 backdrop-blur-md">
        <form
          className="mx-auto w-full max-w-3xl"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label htmlFor="chat-input" className="sr-only">
            Message the assistant
          </label>
          <div className="relative rounded-xl border border-border/80 bg-background/90 p-2 shadow-xs transition-all focus-within:border-foreground/30 focus-within:ring-1 focus-within:ring-foreground/20">
            <Textarea
              id="chat-input"
              ref={textareaRef}
              value={draft}
              disabled={disabled}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              rows={2}
              placeholder={
                disabled
                  ? (disabledReason ?? "Unavailable")
                  : "Ask a product or growth question, or request a Ship 30 essay…"
              }
              className="min-h-[52px] resize-none border-0 bg-transparent px-1.5 py-1 text-xs sm:text-sm shadow-none focus-visible:ring-0 focus-visible:outline-none"
              aria-describedby="chat-input-help"
            />
            <div className="flex items-center justify-between pt-1 border-t border-border/40">
              <span id="chat-input-help" className="text-[10px] text-muted-foreground/70">
                ↵ Send · Shift+↵ New line · Esc closes artifact
              </span>
              <Button
                type="submit"
                size="sm"
                disabled={disabled || isSending || draft.trim().length === 0}
                className="h-7 gap-1 rounded-md px-2.5 text-xs font-medium"
              >
                {isSending ? (
                  <Loader2 className="size-3 animate-spin" aria-hidden />
                ) : (
                  <CornerDownLeft className="size-3" aria-hidden />
                )}
                <span>Send</span>
              </Button>
            </div>
          </div>
        </form>
      </div>
    </section>
  );
}
