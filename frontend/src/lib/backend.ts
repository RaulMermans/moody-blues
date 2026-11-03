import "server-only";

import type { HealthResponse, ReadinessResponse, SystemStatus } from "./status-types";

// Server-side only. Read at request time so one build works against any backend.
function backendUrl(): string {
  return (process.env.MOODY_BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

const TIMEOUT_MS = 5000;

async function getJson<T>(path: string): Promise<{ body: T; requestId: string | null }> {
  const res = await fetch(`${backendUrl()}${path}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(TIMEOUT_MS),
    headers: { accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`${path} returned HTTP ${res.status}`);
  }
  return { body: (await res.json()) as T, requestId: res.headers.get("x-request-id") };
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const checkedAt = new Date().toISOString();
  try {
    const [health, readiness] = await Promise.all([
      getJson<HealthResponse>("/health"),
      getJson<ReadinessResponse>("/ready"),
    ]);
    if (health.body.status !== "ok") {
      throw new Error(`unexpected health status: ${String(health.body.status)}`);
    }
    return {
      backend: "connected",
      checkedAt,
      requestId: health.requestId,
      health: health.body,
      readiness: readiness.body,
    };
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    return { backend: "unreachable", checkedAt, error: `Backend unreachable: ${reason}` };
  }
}
