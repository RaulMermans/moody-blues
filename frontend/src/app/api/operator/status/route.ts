import { forward } from "@/lib/operator-proxy";

export async function GET(): Promise<Response> {
  return forward("/operator/status");
}
