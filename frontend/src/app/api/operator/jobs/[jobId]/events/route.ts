import { backendUrl } from "@/lib/backend";
import { operatorToken } from "@/lib/evidence";

// Passes the backend's event stream through. Payloads hold ids and fixed codes only.
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/operator/jobs/[jobId]/events">,
): Promise<Response> {
  const token = await operatorToken();
  if (!token) return new Response(null, { status: 401 });
  const { jobId } = await ctx.params;
  const lastEventId = request.headers.get("last-event-id");
  try {
    const upstream = await fetch(
      `${backendUrl()}/operator/jobs/${encodeURIComponent(jobId)}/events`,
      {
        cache: "no-store",
        signal: request.signal,
        headers: {
          authorization: `Bearer ${token}`,
          ...(lastEventId && /^\d+$/.test(lastEventId) ? { "last-event-id": lastEventId } : {}),
        },
      },
    );
    if (!upstream.ok || !upstream.body) return new Response(null, { status: upstream.status });
    return new Response(upstream.body, {
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-store",
        "x-accel-buffering": "no",
      },
    });
  } catch {
    return new Response(null, { status: 503 });
  }
}
