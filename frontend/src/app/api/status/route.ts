import { connection } from "next/server";

import { getSystemStatus } from "@/lib/backend";

// Controlled server-side proxy: the browser talks only to this route, never to the
// FastAPI backend or any model provider directly.
export async function GET(): Promise<Response> {
  await connection(); // always evaluate at request time
  const status = await getSystemStatus();
  return Response.json(status, { headers: { "cache-control": "no-store" } });
}
