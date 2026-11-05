import { cookies } from "next/headers";

import { backendUrl } from "@/lib/backend";
import { OPERATOR_COOKIE } from "@/lib/evidence";
import { crossOrigin, sameOrigin } from "@/lib/operator-proxy";

const SESSION_SECONDS = 8 * 60 * 60;

// The token is checked by the backend and then kept in an httpOnly cookie, which page scripts
// cannot read. It is never returned to the browser in a body.
export async function POST(request: Request): Promise<Response> {
  if (!sameOrigin(request)) return crossOrigin();
  const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
  const token = typeof body?.token === "string" ? body.token.trim() : "";
  if (!token || token.length > 256) {
    return Response.json({ error: { message: "enter the operator token" } }, { status: 400 });
  }
  let status: number;
  try {
    const res = await fetch(`${backendUrl()}/operator/session`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
      headers: { authorization: `Bearer ${token}` },
    });
    status = res.status;
  } catch {
    return Response.json({ error: { message: "the backend could not be reached" } }, { status: 503 });
  }
  if (status !== 200) {
    const message =
      status === 403
        ? "operator access is not enabled on this server"
        : status === 429
          ? "too many failed attempts; wait a minute"
          : "that token was not accepted";
    return Response.json({ error: { message } }, { status });
  }
  (await cookies()).set(OPERATOR_COOKIE, token, {
    httpOnly: true,
    sameSite: "strict",
    secure: new URL(request.url).protocol === "https:",
    path: "/",
    maxAge: SESSION_SECONDS,
  });
  return Response.json({ operator: true }, { headers: { "cache-control": "no-store" } });
}

export async function DELETE(request: Request): Promise<Response> {
  if (!sameOrigin(request)) return crossOrigin();
  (await cookies()).delete(OPERATOR_COOKIE);
  return Response.json({ operator: false });
}
