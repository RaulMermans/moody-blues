import { forward } from "@/lib/operator-proxy";

export async function GET(
  request: Request,
  ctx: RouteContext<"/api/operator/jobs/[jobId]">,
): Promise<Response> {
  const { jobId } = await ctx.params;
  const after = Number(new URL(request.url).searchParams.get("after") ?? "0");
  const safeAfter = Number.isInteger(after) && after >= 0 ? after : 0;
  return forward(`/operator/jobs/${encodeURIComponent(jobId)}?after=${safeAfter}`);
}
