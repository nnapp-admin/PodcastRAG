import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "./client";
import type { Artifact, Capability, ChatMessage, ChatSession, SessionDetail } from "./schemas";

/** React Query bindings for the FastAPI backend. */

export const queryKeys = {
  health: ["health"] as const,
  sessions: ["sessions"] as const,
  session: (id: string) => ["session", id] as const,
  artifacts: (id: string) => ["artifacts", id] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: api.health,
    refetchInterval: 20_000,
    retry: false,
    staleTime: 5_000,
  });
}

export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: api.listSessions,
    retry: false,
    select: (data) => data.sessions,
  });
}

export function useSession(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.session(sessionId ?? "none"),
    queryFn: () => api.getSession(sessionId as string),
    enabled: Boolean(sessionId),
    retry: false,
  });
}

export function useSessionArtifacts(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.artifacts(sessionId ?? "none"),
    queryFn: () => api.listSessionArtifacts(sessionId as string),
    enabled: Boolean(sessionId),
    retry: false,
    select: (data) => data.artifacts,
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (title?: string) => api.createSession(title),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sessions }),
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => api.deleteSession(sessionId),
    onMutate: async (deletedSessionId: string) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.sessions });
      const previous = queryClient.getQueryData<{ sessions: ChatSession[] }>(queryKeys.sessions);
      if (previous?.sessions) {
        queryClient.setQueryData<{ sessions: ChatSession[] }>(queryKeys.sessions, {
          sessions: previous.sessions.filter((s) => s.id !== deletedSessionId),
        });
      }
      return { previous };
    },
    onError: (_err, _sessionId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.sessions, context.previous);
      }
    },
    onSuccess: (_data, deletedSessionId) => {
      queryClient.removeQueries({ queryKey: queryKeys.session(deletedSessionId) });
      queryClient.removeQueries({ queryKey: queryKeys.artifacts(deletedSessionId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { sessionId: string; message: string; capability?: Capability | null }) => {
      if (!input.sessionId) {
        throw new ApiError({
          kind: "http",
          code: "no_session",
          message: "Start a chat before sending a message.",
        });
      }
      return api.sendMessage(input.sessionId, input);
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.session(input.sessionId) });
      const previousSession = queryClient.getQueryData<SessionDetail>(
        queryKeys.session(input.sessionId),
      );

      const optimisticUserMessage: ChatMessage = {
        id: `temp-${Date.now()}`,
        session_id: input.sessionId,
        role: "user",
        content: input.message,
        created_at: new Date().toISOString(),
        citations: [],
        capability: input.capability ?? null,
        grounded: true,
        provider: null,
        model: null,
        latency_ms: null,
        artifact_id: null,
      };

      if (previousSession) {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(input.sessionId), {
          ...previousSession,
          messages: [...previousSession.messages, optimisticUserMessage],
        });
      } else {
        queryClient.setQueryData<SessionDetail>(queryKeys.session(input.sessionId), {
          session: {
            id: input.sessionId,
            title: input.message.slice(0, 80),
            provider: "ollama",
            model: "llama",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            last_message_at: new Date().toISOString(),
            message_count: 1,
            artifact_count: 0,
          },
          messages: [optimisticUserMessage],
        });
      }

      return { previousSession, sessionId: input.sessionId };
    },
    onError: (_err, _input, context) => {
      if (context?.previousSession) {
        queryClient.setQueryData(queryKeys.session(context.sessionId), context.previousSession);
      }
    },
    onSuccess: (turn, input) => {
      // 1. Immediately replace optimistic message with real server messages
      queryClient.setQueryData<SessionDetail>(queryKeys.session(input.sessionId), (old) => {
        if (!old) {
          return {
            session: {
              id: input.sessionId,
              title: turn.user_message.content.slice(0, 80),
              provider: turn.assistant_message.provider ?? "ollama",
              model: turn.assistant_message.model ?? "llama",
              created_at: turn.user_message.created_at,
              updated_at: turn.assistant_message.created_at,
              last_message_at: turn.assistant_message.created_at,
              message_count: 2,
              artifact_count: turn.artifact ? 1 : 0,
            },
            messages: [turn.user_message, turn.assistant_message],
          };
        }
        const withoutTemp = old.messages.filter((m) => !m.id.startsWith("temp-"));
        const hasUser = withoutTemp.some((m) => m.id === turn.user_message.id);
        const updated = hasUser
          ? [...withoutTemp, turn.assistant_message]
          : [...withoutTemp, turn.user_message, turn.assistant_message];
        return {
          ...old,
          messages: updated,
        };
      });

      // 2. Immediately update session artifacts cache so openArtifact is immediately visible without click
      if (turn.artifact) {
        queryClient.setQueryData<{ artifacts: Artifact[] }>(
          queryKeys.artifacts(input.sessionId),
          (old) => {
            const list = old?.artifacts ?? [];
            if (list.some((a) => a.id === turn.artifact!.id)) return old ?? { artifacts: list };
            return {
              artifacts: [turn.artifact!, ...list],
            };
          },
        );
      }

      // Only invalidate the sessions list and artifacts list — not the session detail,
      // which was already set manually above. A second invalidation triggers a background
      // network fetch that causes a visible flicker re-render.
      queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(input.sessionId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });
}
