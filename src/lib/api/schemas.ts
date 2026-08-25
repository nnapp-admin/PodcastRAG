import { z } from "zod";

/**
 * Zod mirrors of the FastAPI pydantic contracts (backend/app/schemas.py).
 * Every response is parsed, so backend/frontend contract drift surfaces as a
 * clear UI error instead of an undefined-property crash.
 */

export const componentHealthSchema = z.object({
  status: z.enum(["ok", "degraded", "error"]),
  detail: z.string().nullable().optional(),
  extra: z.record(z.unknown()).default({}),
});

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded", "error"]),
  version: z.string(),
  environment: z.string(),
  provider: z.string(),
  model: z.string(),
  embedding_model: z.string(),
  agent_runtime: z.string(),
  components: z.record(componentHealthSchema),
});

export const citationSchema = z.object({
  chunk_id: z.string(),
  transcript_id: z.string(),
  episode_title: z.string(),
  guest: z.string().nullable().optional(),
  source_url: z.string().nullable().optional(),
  published_at: z.string().nullable().optional(),
  chunk_index: z.number(),
  start_timestamp: z.string().nullable().optional(),
  end_timestamp: z.string().nullable().optional(),
  score: z.number(),
  excerpt: z.string(),
});

export const capabilitySchema = z.enum(["qa", "essay", "artifact"]);
export const artifactKindSchema = z.enum(["markdown", "html"]);

export const messageSchema = z.object({
  id: z.string(),
  session_id: z.string(),
  role: z.string(),
  content: z.string(),
  created_at: z.string(),
  citations: z.array(citationSchema).default([]),
  capability: capabilitySchema.nullable().optional(),
  grounded: z.boolean().default(true),
  provider: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
  artifact_id: z.string().nullable().optional(),
});

export const sessionSchema = z.object({
  id: z.string(),
  title: z.string(),
  provider: z.string(),
  model: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  last_message_at: z.string().nullable(),
  message_count: z.number().default(0),
  artifact_count: z.number().default(0),
});

export const sessionListSchema = z.object({ sessions: z.array(sessionSchema) });

export const artifactSchema = z.object({
  id: z.string(),
  session_id: z.string(),
  message_id: z.string().nullable(),
  kind: artifactKindSchema,
  title: z.string(),
  content: z.string(),
  byte_size: z.number(),
  created_at: z.string(),
  citations: z.array(citationSchema).default([]),
});

export const artifactListSchema = z.object({ artifacts: z.array(artifactSchema) });

export const sessionDetailSchema = z.object({
  session: sessionSchema,
  messages: z.array(messageSchema),
});

export const chatResponseSchema = z.object({
  session_id: z.string(),
  user_message: messageSchema,
  assistant_message: messageSchema,
  artifact: artifactSchema.nullable().optional(),
});

export const retrievalResponseSchema = z.object({
  query: z.string(),
  top_k: z.number(),
  score_threshold: z.number(),
  chunk_count: z.number(),
  latency_ms: z.number(),
  results: z.array(citationSchema),
});

export const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.unknown()).default({}),
    request_id: z.string().nullable().optional(),
  }),
});

export type ComponentHealth = z.infer<typeof componentHealthSchema>;
export type Health = z.infer<typeof healthSchema>;
export type Citation = z.infer<typeof citationSchema>;
export type Capability = z.infer<typeof capabilitySchema>;
export type ArtifactKind = z.infer<typeof artifactKindSchema>;
export type ChatMessage = z.infer<typeof messageSchema>;
export type ChatSession = z.infer<typeof sessionSchema>;
export type Artifact = z.infer<typeof artifactSchema>;
export type SessionDetail = z.infer<typeof sessionDetailSchema>;
export type ChatTurn = z.infer<typeof chatResponseSchema>;
