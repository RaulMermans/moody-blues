// The typed presentation contract for the Reality Fracture components.
//
// Every visual state here is copied from a named evidence field. Nothing is inferred from text and
// nothing is computed that the Oracle did not record: a component is told what to draw, so a fracture
// can only appear where this mapping was given a recorded reason for one.
import { disclosureLine } from "@/components/verdict-strip";
import type {
  CaseStudy,
  CustomerView,
  Discrepancy,
  ExecutionMode,
  InvestigationDetail,
  OracleFindingView,
  ProductOutcome,
  RealityRun,
  RunList,
  Verdict,
} from "@/lib/evidence-types";

/**
 * What a seal may say. Only `verdict` is the Oracle speaking. `incomplete` and `unverified` mean no
 * verdict exists, and they exist so that absence can never look like a result.
 */
export type SealState =
  | { kind: "verdict"; verdict: Verdict; qualifier: string | null }
  | { kind: "incomplete"; outcome: "failed" | "cancelled" | "budget_exhausted" }
  | { kind: "unverified"; reason: "no_target_run" | "outcome_uncertain" | "integrity_failed" };

/**
 * How far the two realities came apart.
 * - `violation`: the Oracle recorded a VIOLATION. The only state that breaks the frame.
 * - `delivery`: the agent was told something false, but the Oracle found the state correct.
 * - `unresolved`: the Oracle returned INCONCLUSIVE.
 * - `none`: no discrepancy was recorded.
 */
export type DivergenceState = "violation" | "delivery" | "unresolved" | "none";

export type RecordMention = "structured_claim" | "message_only" | "not_named" | "not_assessed";

export interface RecordView {
  customer: CustomerView;
  mention: RecordMention;
}

export interface PhantomWrite {
  callSeq: number;
  delivered: string;
}

export interface ComparisonModel {
  investigationId: string;
  runId: string;
  caseTitle: string | null;
  caseSummary: string | null;
  mode: ExecutionMode;
  targetLabel: string;
  world: string;
  runIndex: number;
  runTotal: number;
  faultsDelivered: number;
  task: string | null;
  seal: SealState;
  divergence: DivergenceState;
  claim: { status: string; customerId: string | null; message: string; truncated: boolean } | null;
  claimedIdCount: number;
  termination: string;
  disclosure: string | null;
  phantomWrites: PhantomWrite[];
  newRecords: RecordView[];
  seedRecordCount: number;
  objectiveSatisfied: boolean;
  violations: OracleFindingView[];
  invariants: { name: string; held: boolean }[];
  discrepancies: Discrepancy[];
  caseStudy: CaseStudy | null;
}

export function sealFromRun(run: RealityRun): SealState {
  const impaired = run.impairments.length ? `Impaired run: ${run.impairments.join(", ")}` : null;
  const noClaim =
    run.run_outcome === "state_correct_claim_missing"
      ? "State correct, but no valid claim. Not a success."
      : null;
  return { kind: "verdict", verdict: run.verdict, qualifier: noClaim ?? impaired };
}

/** For an investigation with no run to read a verdict from. */
export function sealWithoutRun(outcome: ProductOutcome, integrity: "verified" | "corrupt"): SealState {
  if (integrity === "corrupt") return { kind: "unverified", reason: "integrity_failed" };
  if (outcome === "failed" || outcome === "cancelled" || outcome === "budget_exhausted") {
    return { kind: "incomplete", outcome };
  }
  if (outcome === "outcome_uncertain") return { kind: "unverified", reason: "outcome_uncertain" };
  return { kind: "unverified", reason: "no_target_run" };
}

export function divergenceFrom(run: RealityRun): DivergenceState {
  if (run.verdict === "VIOLATION") return "violation";
  if (run.verdict === "INCONCLUSIVE") return "unresolved";
  return run.discrepancies.length ? "delivery" : "none";
}

function mentionOf(customer: CustomerView, run: RealityRun): RecordMention {
  if (customer.named_in_claim) return "structured_claim";
  const disclosure = run.agent.disclosure;
  if (!disclosure || !customer.flagged_duplicate) return "not_assessed";
  return disclosure.mentioned_in_message.includes(customer.customer_id) ? "message_only" : "not_named";
}

function targetLabel(run: RealityRun): string {
  if (run.target_evidence === "live_provider") return `Model ${run.reported_models.join(", ")}`;
  if (run.target_evidence === "reference_executor") return "Reference script, not a model";
  return "Offline fixture, not a model";
}

export function comparisonFrom(
  detail: InvestigationDetail,
  runs: RunList,
  run: RealityRun,
): ComparisonModel {
  const claim = run.agent.claim;
  const violated = new Set(run.actual.invariants_violated);
  return {
    investigationId: detail.summary.investigation_id,
    runId: run.run_id,
    caseTitle: detail.summary.case?.title ?? null,
    caseSummary: detail.summary.case?.summary ?? null,
    mode: detail.summary.mode,
    targetLabel: targetLabel(run),
    world: run.world_ref,
    runIndex: runs.runs.findIndex((r) => r.run_id === run.run_id) + 1,
    runTotal: runs.runs.length,
    faultsDelivered: run.faults_delivered,
    task: run.agent.mission?.text.split("\n")[0].replace(/^Mission:\s*/, "").split(/(?<=\.)\s/)[0] ?? null,
    seal: sealFromRun(run),
    divergence: divergenceFrom(run),
    claim: claim
      ? {
          status: claim.status,
          customerId: claim.customer_id,
          message: claim.message.text,
          truncated: claim.message.truncated,
        }
      : null,
    claimedIdCount: claim?.customer_id ? 1 : 0,
    termination: run.agent.termination,
    disclosure: disclosureLine(run),
    phantomWrites: run.agent.tool_events
      .filter((e) => e.ok && e.fault_effect === "aborted_new_write")
      .map((e) => ({ callSeq: e.call_seq, delivered: e.delivered_summary })),
    newRecords: run.actual.customers
      .filter((c) => c.role === "new")
      .map((customer) => ({ customer, mention: mentionOf(customer, run) })),
    seedRecordCount: run.actual.customers.filter((c) => c.role === "seed").length,
    objectiveSatisfied: run.actual.objective_satisfied,
    violations: run.actual.findings.filter((f) => f.severity === "violation"),
    invariants: run.actual.invariants_evaluated.map((name) => ({ name, held: !violated.has(name) })),
    discrepancies: run.discrepancies,
    caseStudy: detail.case_study,
  };
}
