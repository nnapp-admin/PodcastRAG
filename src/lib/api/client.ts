import { z } from "zod";

import {
  artifactListSchema,
  artifactSchema,
  chatResponseSchema,
  errorEnvelopeSchema,
  healthSchema,
  retrievalResponseSchema,
  sessionDetailSchema,
  sessionListSchema,
  sessionSchema,
  type Capability,
} from "./schemas";

/**
 * The single typed API client. Nothing in the UI calls `fetch` directly, and
 * there is no mock/fallback path: if the FastAPI backend is unreachable the
 * client throws `ApiError` with `kind: "network"` and the UI says so.
 */

export const API_BASE_URL = (
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://localhost:8000"
).replace(/\/+$/, "");

export type ApiErrorKind = "network" | "http" | "contract";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(init: {
    kind: ApiErrorKind;
    message: string;
    status?: number | null;
    code?: string;
    details?: Record<string, unknown>;
    requestId?: string | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status ?? null;
    this.code = init.code ?? init.kind;
    this.details = init.details ?? {};
    this.requestId = init.requestId ?? null;
  }

  /** True when the backend itself could not be reached at all. */
  get isDisconnected() {
    return this.kind === "network";
  }
}

async function request<T extends z.ZodTypeAny>(
  path: string,
  schema: T,
  init?: RequestInit & { expectEmpty?: boolean },
): Promise<z.infer<T>> {
  const url = `${API_BASE_URL}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        "content-type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (cause) {
    throw new ApiError({
      kind: "network",
      code: "backend_unreachable",
      message: `Cannot reach the API at ${API_BASE_URL}. Start the stack with \`docker compose up\`.`,
      details: { url, cause: String(cause) },
    });
  }

  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const raw = await response.text();
    let code = `http_${response.status}`;
    let message = `Request failed with status ${response.status}.`;
    let details: Record<string, unknown> = {};
    try {
      const parsed = errorEnvelopeSchema.parse(JSON.parse(raw));
      code = parsed.error.code;
      message = parsed.error.message;
      details = parsed.error.details;
    } catch {
      if (raw) details = { body: raw.slice(0, 500) };
    }
    throw new ApiError({
      kind: "http",
      status: response.status,
      code,
      message,
      details,
      requestId,
    });
  }

  if (init?.expectEmpty || response.status === 204) {
    return schema.parse(undefined);
  }

  const payload = await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError({
      kind: "contract",
      status: response.status,
      code: "response_contract_mismatch",
      message: `The API response for ${path} did not match the expected contract.`,
      details: { issues: parsed.error.issues.slice(0, 5) },
      requestId,
    });
  }
  return parsed.data;
}

export const api = {
  health: () => request("/health", healthSchema),

  listSessions: () => request("/sessions", sessionListSchema),

  createSession: (title?: string) =>
    request("/sessions", sessionSchema, {
      method: "POST",
      body: JSON.stringify({ title: title ?? null }),
    }),

  getSession: (sessionId: string) => request(`/sessions/${sessionId}`, sessionDetailSchema),

  deleteSession: (sessionId: string) =>
    request(`/sessions/${sessionId}`, z.void(), { method: "DELETE", expectEmpty: true }),

  sendMessage: (
    sessionId: string,
    body: { message: string; capability?: Capability | null; top_k?: number | null },
  ) =>
    request(`/sessions/${sessionId}/messages`, chatResponseSchema, {
      method: "POST",
      body: JSON.stringify({
        message: body.message,
        capability: body.capability ?? null,
        top_k: body.top_k ?? null,
      }),
    }),

  listSessionArtifacts: (sessionId: string) =>
    request(`/sessions/${sessionId}/artifacts`, artifactListSchema),

  getArtifact: (artifactId: string) => request(`/artifacts/${artifactId}`, artifactSchema),

  search: (query: string, topK?: number) =>
    request("/retrieval/search", retrievalResponseSchema, {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK ?? 6 }),
    }),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error.";
}
