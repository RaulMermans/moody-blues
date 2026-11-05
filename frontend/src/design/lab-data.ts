import "server-only";

import { type Failure, getInvestigation, getRun, getRuns, listInvestigations } from "@/lib/evidence";

import { type ComparisonModel, comparisonFrom, sealWithoutRun, type SealState } from "./model";

export type LoadedCase =
  | { ok: true; model: ComparisonModel }
  | { ok: true; model: null; investigationId: string; seal: SealState }
  | Failure;

/**
 * Loads one case through the same evidence API the product uses. With no id, this is the same
 * signature case the dashboard leads with. The lab holds no copy of any result.
 */
export async function loadCase(caseId?: string, runId?: string): Promise<LoadedCase> {
  let id = caseId;
  if (!id) {
    const list = await listInvestigations();
    if (!list.ok) return list;
    const lead = list.data.items.find((i) => i.summary?.case?.kind === "verified_violation");
    if (!lead) {
      return { ok: false, kind: "not_found", message: "No verified violation is on record.", requestId: null };
    }
    id = lead.investigation_id;
  }
  const [detail, runs] = await Promise.all([getInvestigation(id), getRuns(id)]);
  if (!detail.ok) return detail;
  if (!runs.ok) return runs;
  const chosen = runId ?? detail.data.summary.case?.primary_run_id ?? runs.data.primary_run_id;
  if (!chosen) {
    return {
      ok: true,
      model: null,
      investigationId: id,
      seal: sealWithoutRun(detail.data.summary.outcome, detail.data.integrity),
    };
  }
  const run = await getRun(id, chosen);
  if (!run.ok) return run;
  return { ok: true, model: comparisonFrom(detail.data, runs.data, run.data) };
}
