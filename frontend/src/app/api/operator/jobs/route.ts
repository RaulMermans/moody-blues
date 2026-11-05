import { crossOrigin, forward, sameOrigin } from "@/lib/operator-proxy";

export async function POST(request: Request): Promise<Response> {
  if (!sameOrigin(request)) return crossOrigin();
  const body = (await request.json().catch(() => null)) as { mission_id?: unknown } | null;
  // Only the mission id crosses this boundary, whatever else was sent.
  return forward("/operator/jobs", {
    method: "POST",
    body: JSON.stringify({ mission_id: body?.mission_id }),
  });
}
