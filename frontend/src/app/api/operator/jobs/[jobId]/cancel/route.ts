import { crossOrigin, forward, sameOrigin } from "@/lib/operator-proxy";

export async function POST(
  request: Request,
  ctx: RouteContext<"/api/operator/jobs/[jobId]/cancel">,
): Promise<Response> {
  if (!sameOrigin(request)) return crossOrigin();
  const { jobId } = await ctx.params;
  return forward(`/operator/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}
