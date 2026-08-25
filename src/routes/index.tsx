import { createFileRoute } from "@tanstack/react-router";
import { CircleAlert, Terminal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ArtifactViewer } from "@/components/assistant/artifact-viewer";
import { ChatPanel } from "@/components/assistant/chat-panel";
import { SessionSidebar } from "@/components/assistant/session-sidebar";
import { StatusHeader } from "@/components/assistant/status-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { API_BASE_URL, ApiError, errorMessage } from "@/lib/api/client";
import {
  useCreateSession,
  useDeleteSession,
  useHealth,
  useSendMessage,
  useSession,
  useSessionArtifacts,
  useSessions,
} from "@/lib/api/hooks";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "The Lenny Growth Assistant — Grounded Podcast Answers" },
      {
        name: "description",
        content:
          "Ask product and growth questions and get answers grounded in Lenny's Podcast transcripts, with source citations and Ship 30 essay artifacts.",
      },
      { property: "og:title", content: "The Lenny Growth Assistant" },
      {
        property: "og:description",
        content:
          "A retrieval-grounded assistant over Lenny's Podcast transcripts: cited answers, Ship 30 essays and shareable artifacts.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: AssistantPage,
});

const ACTIVE_SESSION_KEY = "lenny.activeSessionId";

function AssistantPage() {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [openArtifactId, setOpenArtifactId] = useState<string | null>(null);
  const [artifactSheetOpen, setArtifactSheetOpen] = useState(false);
  const [sessionSheetOpen, setSessionSheetOpen] = useState(false);

  const health = useHealth();
  const sessions = useSessions();
  const sessionDetail = useSession(activeSessionId);
  const artifacts = useSessionArtifacts(activeSessionId);
  const createSession = useCreateSession();
  const deleteSession = useDeleteSession();
  const sendMessage = useSendMessage();

  const disconnected =
    (health.error instanceof ApiError && health.error.isDisconnected) ||
    (sessions.error instanceof ApiError && sessions.error.isDisconnected);

  // Restore the last conversation after a reload (client-only read).
  useEffect(() => {
    const stored = window.localStorage.getItem(ACTIVE_SESSION_KEY);
    if (stored) setActiveSessionId(stored);
  }, []);

  useEffect(() => {
    if (activeSessionId) window.localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
  }, [activeSessionId]);

  // A stored id can point at a deleted session: fall back to the newest one.
  useEffect(() => {
    const list = sessions.data;
    if (!list) return;
    if (activeSessionId && list.some((session) => session.id === activeSessionId)) return;
    setActiveSessionId(list[0]?.id ?? null);
  }, [sessions.data, activeSessionId]);

  const artifactList = useMemo(() => artifacts.data ?? [], [artifacts.data]);
  const openArtifact = useMemo(
    () => artifactList.find((artifact) => artifact.id === openArtifactId) ?? null,
    [artifactList, openArtifactId],
  );

  async function handleNewChat() {
    try {
      const session = await createSession.mutateAsync(undefined);
      setActiveSessionId(session.id);
      setOpenArtifactId(null);
      setSessionSheetOpen(false);
    } catch {
      /* surfaced by the banner / mutation error below */
    }
  }

  async function handleSend(message: string) {
    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = await createSession.mutateAsync(message.slice(0, 80));
      sessionId = session.id;
      setActiveSessionId(session.id);
    }
    if (!sessionId) return;
    const turn = await sendMessage.mutateAsync({ sessionId, message }).catch(() => null);
    if (turn?.artifact) {
      setOpenArtifactId(turn.artifact.id);
      setArtifactSheetOpen(true);
    }
  }

  async function handleDelete(sessionId: string) {
    if (sessionId === activeSessionId) {
      const remaining = (sessions.data ?? []).filter((s) => s.id !== sessionId);
      const nextId = remaining[0]?.id ?? null;
      setActiveSessionId(nextId);
      setOpenArtifactId(null);
      if (nextId) {
        window.localStorage.setItem(ACTIVE_SESSION_KEY, nextId);
      } else {
        window.localStorage.removeItem(ACTIVE_SESSION_KEY);
      }
    }
    await deleteSession.mutateAsync(sessionId).catch(() => null);
  }

  function openArtifactById(artifactId: string) {
    setOpenArtifactId(artifactId);
    setArtifactSheetOpen(true);
  }

  const composerDisabled = disconnected || createSession.isPending;

  return (
    <div className="flex h-screen min-h-0 flex-col bg-background">
      <StatusHeader
        health={health.data}
        isDisconnected={disconnected}
        isLoading={health.isLoading}
        artifactCount={artifactList.length}
        onToggleSessions={() => setSessionSheetOpen(true)}
        onToggleArtifact={() => {
          if (!openArtifactId && artifactList[0]) setOpenArtifactId(artifactList[0].id);
          setArtifactSheetOpen(true);
        }}
      />

      {disconnected ? (
        <Alert variant="destructive" className="rounded-none border-x-0">
          <Terminal className="size-4" aria-hidden />
          <AlertTitle>Backend unavailable</AlertTitle>
          <AlertDescription className="space-y-1">
            <span>
              The UI is running, but the FastAPI backend at{" "}
              <code className="font-mono">{API_BASE_URL}</code> is not responding. Nothing is
              mocked, so the assistant stays disabled until it is up.
            </span>
            <code className="block font-mono text-xs">
              cp .env.example .env &amp;&amp; docker compose up --build
            </code>
          </AlertDescription>
        </Alert>
      ) : null}

      {!disconnected && health.data?.status === "degraded" ? (
        <Alert className="rounded-none border-x-0">
          <CircleAlert className="size-4" aria-hidden />
          <AlertTitle>Backend is degraded</AlertTitle>
          <AlertDescription>
            {Object.entries(health.data.components)
              .filter(([, component]) => component.status !== "ok")
              .map(([name, component]) => `${name}: ${component.detail ?? component.status}`)
              .join(" · ")}
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-60 shrink-0 border-r border-border/70 bg-card/30 md:block">
          <SessionSidebar
            sessions={sessions.data ?? []}
            activeSessionId={activeSessionId}
            isLoading={sessions.isLoading}
            isDisconnected={disconnected}
            creating={createSession.isPending}
            onNewChat={handleNewChat}
            onSelect={(id) => {
              setActiveSessionId(id);
              setOpenArtifactId(null);
            }}
            onDelete={handleDelete}
          />
        </aside>

        <main className="flex min-w-0 flex-1 bg-background/50">
          <div className="min-w-0 flex-1">
            <ChatPanel
              messages={sessionDetail.data?.messages ?? []}
              isLoadingSession={sessionDetail.isLoading}
              isSending={sendMessage.isPending}
              sendError={sendMessage.error ? errorMessage(sendMessage.error) : null}
              loadError={sessionDetail.error ? errorMessage(sessionDetail.error) : null}
              disabled={composerDisabled}
              disabledReason={disconnected ? "Backend unavailable" : null}
              onSend={handleSend}
              onOpenArtifact={openArtifactById}
            />
          </div>

          {openArtifact ? (
            <div className="hidden w-[28rem] shrink-0 border-l border-border/70 bg-card/30 lg:block xl:w-[34rem]">
              <ArtifactViewer
                artifact={openArtifact}
                artifacts={artifactList}
                onSelect={setOpenArtifactId}
                onClose={() => setOpenArtifactId(null)}
              />
            </div>
          ) : null}
        </main>
      </div>

      {/* Mobile / tablet: the artifact viewer becomes a sheet. */}
      <Sheet open={artifactSheetOpen && Boolean(openArtifact)} onOpenChange={setArtifactSheetOpen}>
        <SheetContent
          side="right"
          overlayClassName="lg:hidden"
          className="w-full p-0 sm:max-w-xl lg:hidden"
        >
          <SheetTitle className="sr-only">Artifact viewer</SheetTitle>
          {openArtifact ? (
            <ArtifactViewer
              artifact={openArtifact}
              artifacts={artifactList}
              onSelect={setOpenArtifactId}
              onClose={() => setArtifactSheetOpen(false)}
            />
          ) : null}
        </SheetContent>
      </Sheet>

      {/* Mobile: session sidebar becomes a sheet. */}
      <Sheet open={sessionSheetOpen} onOpenChange={setSessionSheetOpen}>
        <SheetContent
          side="left"
          overlayClassName="md:hidden"
          className="w-72 p-0 md:hidden"
        >
          <SheetTitle className="sr-only">Conversations</SheetTitle>
          <SessionSidebar
            sessions={sessions.data ?? []}
            activeSessionId={activeSessionId}
            isLoading={sessions.isLoading}
            isDisconnected={disconnected}
            creating={createSession.isPending}
            onNewChat={handleNewChat}
            onSelect={(id) => {
              setActiveSessionId(id);
              setOpenArtifactId(null);
              setSessionSheetOpen(false);
            }}
            onDelete={handleDelete}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}
