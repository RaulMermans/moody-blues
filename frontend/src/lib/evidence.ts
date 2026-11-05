import "server-only";

import { cookies } from "next/headers";

import { backendUrl } from "./backend";
import type {
  ExperimentView,
  InvestigationDetail,
  InvestigationList,
  RealityRun,
  RunList,
  TimelinePage,
} from "./evidence-types";

export const OPERATOR_COOKIE = "mb_operator";
const TIMEOUT_MS = 5000;

export type Failure = {
  ok: false;
  kind: "not_found" | "integrity" | "unreachable" | "error";
  message: string;
  requestId: string | null;
};
export type Loaded<T> = { ok: true; data: T } | Failure;

export async function operatorToken(): Promise<string | null> {
  return (await cookies()).get(OPERATOR_COOKIE)?.value ?? null;
}

async function read<T>(path: string): Promise<Loaded<T>> {
  const token = await operatorToken();
  try {
    const res = await fetch(`${backendUrl()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: {
        accept: "application/json",
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
    });
    const requestId = res.headers.get("x-request-id");
    if (res.ok) return { ok: true, data: (await res.json()) as T };
    const body = (await res.json().catch(() => null)) as {
      error?: { category?: string; message?: string };
    } | null;
    const category = body?.error?.category;
    return {
      ok: false,
      kind:
        res.status === 404 || category === "not_found"
          ? "not_found"
          : category === "evidence_integrity"
            ? "integrity"
            : "error",
      message: body?.error?.message ?? `HTTP ${res.status}`,
      requestId,
    };
  } catch {
    return {
      ok: false,
      kind: "unreachable",
      message: "The evidence service could not be reached.",
      requestId: null,
    };
  }
}

const seg = encodeURIComponent;

export const listInvestigations = () => read<InvestigationList>("/investigations");
export const getInvestigation = (id: string) =>
  read<InvestigationDetail>(`/investigations/${seg(id)}`);
export const getTimeline = (id: string) =>
  read<TimelinePage>(`/investigations/${seg(id)}/timeline`);
export const getExperiments = (id: string) =>
  read<{ investigation_id: string; experiments: ExperimentView[] }>(
    `/investigations/${seg(id)}/experiments`,
  );
export const getRuns = (id: string) => read<RunList>(`/investigations/${seg(id)}/runs`);
export const getRun = (id: string, runId: string) =>
  read<RealityRun>(`/investigations/${seg(id)}/runs/${seg(runId)}`);
