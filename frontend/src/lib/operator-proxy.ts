import "server-only";

import { backendUrl } from "./backend";
import { operatorToken } from "./evidence";

const TIMEOUT_MS = 10_000;

function refused(status: number, category: string, message: string): Response {
  return Response.json(
    { error: { category, message, retryable: false } },
    { status, headers: { "cache-control": "no-store" } },
  );
}

// A state-changing request must come from this site. SameSite=Strict already blocks the cookie
// cross-site; this also refuses anything that sends a mismatched Origin.
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

export function crossOrigin(): Response {
  return refused(403, "forbidden", "cross-origin request refused");
}

export async function forward(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await operatorToken();
  if (!token) return refused(401, "unauthorized", "operator session required");
  try {
    const res = await fetch(`${backendUrl()}${path}`, {
      ...init,
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
    });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch {
    return refused(503, "internal", "the backend could not be reached");
  }
}
