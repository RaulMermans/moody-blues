// Which environment a run tested, and the words for it, read from the run's own record.
//
// A run with no `world` was recorded before worlds existed, and every such run is the CRM: the same
// mapping the backend applies (`LEGACY_WORLD_TYPE`). Records are never rewritten to say so. This is
// the one place that knows a run's records may be customers or something else.
import type { RealityRun } from "@/lib/evidence-types";

export interface WorldWords {
  /** The environment's name, for a label. */
  name: string;
  /** What holds the records, as a noun: CRM, job queue. */
  store: string;
  /** One record: customer, job. */
  record: string;
  /** The tool that writes. */
  writeTool: string;
  /** The verb a write is counted by: create, submit. */
  writeVerb: string;
}

const CRM: WorldWords = {
  name: "Synthetic CRM",
  store: "CRM",
  record: "customer",
  writeTool: "create_customer",
  writeVerb: "create",
};

export function wordsFor(run: RealityRun): WorldWords {
  const world = run.world;
  if (!world) return CRM;
  return {
    name: world.name,
    store: world.store_noun,
    record: world.record_noun,
    writeTool: world.write_tool,
    writeVerb: world.write_tool.split("_")[0],
  };
}

/** One authoritative row, whatever the world calls it. Copied from the record, field for field. */
export interface RunRecord {
  id: string;
  title: string;
  detail: string | null;
  status: string | null;
  statusHistory: string[];
  created_by_call: number;
  role: "seed" | "new";
  objective_match: boolean;
  flagged_duplicate: boolean;
  named_in_claim: boolean;
}

export function runRecords(run: RealityRun): RunRecord[] {
  const records = run.actual.records ?? [];
  if (records.length) {
    return records.map((r) => ({
      id: r.record_id,
      title: r.title,
      detail: r.status ? `status ${r.status}` : null,
      status: r.status,
      statusHistory: r.status_history,
      created_by_call: r.created_by_call,
      role: r.role,
      objective_match: r.objective_match,
      flagged_duplicate: r.flagged_duplicate,
      named_in_claim: r.named_in_claim,
    }));
  }
  return run.actual.customers.map((c) => ({
    id: c.customer_id,
    title: c.name,
    detail: c.email,
    status: null,
    statusHistory: [],
    created_by_call: c.created_by_call,
    role: c.role,
    objective_match: c.objective_match,
    flagged_duplicate: c.flagged_duplicate,
    named_in_claim: c.named_in_claim,
  }));
}

export function newRecordIds(run: RealityRun): string[] {
  return run.actual.new_record_ids?.length ? run.actual.new_record_ids : run.actual.new_customer_ids;
}

export function claimedRecordId(run: RealityRun): string | null {
  const claim = run.agent.claim;
  return claim ? (claim.record_id ?? claim.customer_id) : null;
}

export function changeRecordId(change: RealityRun["actual"]["changes"][number]): string {
  return change.record_id ?? change.customer_id ?? "";
}

/** Whether the run could test what it set out to. Never a verdict, and absent on older records. */
export function validityLine(run: RealityRun): string | null {
  const validity = run.validity;
  if (!validity) return null;
  const kinds = (names: string[]) => names.map((k) => k.replaceAll("_", " ")).join(", ");
  switch (validity.classification) {
    case "control":
      return "No fault was set for this run, so it is a control.";
    case "exercised":
      return `The fault set for this run fired: ${kinds(validity.eligible_fault_kinds)}.`;
    case "partially_exercised":
      return `Part of the fault set for this run fired: ${kinds(validity.eligible_fault_kinds)}.`;
    case "not_exercised":
      return `The fault set for this run never fired (${kinds(validity.not_exercised_fault_kinds)}), so this run tested nothing about it.`;
    default:
      return null;
  }
}
