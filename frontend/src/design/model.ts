// The typed presentation contract for the investigation screens.
//
// Every visual state here is copied from a named evidence field. Nothing is inferred from free text
// and nothing is computed that the Oracle did not record: a component is told what to draw, so a
// distortion can only appear where this mapping was given a recorded reason for one.
import type { CustomerView, Discrepancy, ProductOutcome, RealityRun, Verdict } from "@/lib/evidence-types";

/**
 * What a seal may say. Only `verdict` is the Oracle speaking. `incomplete` and `unverified` mean no
 * verdict exists, and they exist so that absence can never look like a result.
 */
export type SealState =
  | { kind: "verdict"; verdict: Verdict; qualifier: string | null }
  | { kind: "incomplete"; outcome: "failed" | "cancelled" | "budget_exhausted" }
  | { kind: "unverified"; reason: "no_target_run" | "outcome_uncertain" | "integrity_failed" };

/**
 * How far the two realities came apart in a run.
 * - `violation`: the Oracle recorded a VIOLATION. The only state that displaces anything.
 * - `delivery`: the agent was told something false, but the Oracle found no violation.
 * - `unresolved`: the Oracle returned INCONCLUSIVE.
 * - `none`: no discrepancy was recorded.
 */
export type DivergenceState = "violation" | "delivery" | "unresolved" | "none";

/** Whether two sides of one row agree. `unknown` is for a side that holds nothing to compare. */
export type Relation = "equal" | "differs" | "unknown";

/** How the seam between two sides is drawn at one row. Only `break` is displaced. */
export type SeamTone = "steady" | "distortion" | "break";

export type RecordMention = "structured_claim" | "message_only" | "not_named" | "not_assessed";

export interface RecordView {
  customer: CustomerView;
  mention: RecordMention;
  /** A flagged record the structured claim left out, while it named another flagged record. */
  extra: boolean;
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

/** A wrong status is a recorded discrepancy, not a reading of the agent's words. */
export function claimRelation(run: RealityRun): Relation {
  if (!run.agent.claim) return "unknown";
  return run.discrepancies.some((d) => d.kind === "claim_versus_state") ? "differs" : "equal";
}

export function seamFor(run: RealityRun, relation: Relation): SeamTone {
  if (relation !== "differs") return "steady";
  return run.verdict === "VIOLATION" ? "break" : "distortion";
}

function mentionOf(customer: CustomerView, run: RealityRun): RecordMention {
  if (customer.named_in_claim) return "structured_claim";
  const disclosure = run.agent.disclosure;
  if (!disclosure || !customer.flagged_duplicate) return "not_assessed";
  return disclosure.mentioned_in_message.includes(customer.customer_id) ? "message_only" : "not_named";
}

/** The rows this run created. Exactly the recorded rows: nothing is added for effect. */
export function recordsFrom(run: RealityRun): RecordView[] {
  const added = run.actual.customers.filter((c) => c.role === "new");
  const claimedOne = added.some((c) => c.flagged_duplicate && c.named_in_claim);
  return added.map((customer) => ({
    customer,
    mention: mentionOf(customer, run),
    extra: claimedOne && customer.flagged_duplicate && !customer.named_in_claim,
  }));
}

/** The first recorded point where a delivered response and authoritative state parted. */
export function firstDivergence(run: RealityRun): Discrepancy | null {
  const located = run.discrepancies.filter((d) => d.call_seq !== null);
  return located.reduce<Discrepancy | null>(
    (first, d) => (first === null || (d.call_seq ?? 0) < (first.call_seq ?? 0) ? d : first),
    null,
  );
}

export type TargetNoun = "agent" | "script" | "fixture";

/** What ran. Read from the evidence field, so a script is never described as an agent. */
export function targetNoun(run: RealityRun): TargetNoun {
  if (run.target_evidence === "live_provider") return "agent";
  return run.target_evidence === "reference_executor" ? "script" : "fixture";
}

export function missionLine(run: RealityRun): string | null {
  const mission = run.agent.mission;
  if (!mission) return null;
  return mission.text.split("\n")[0].replace(/^Mission:\s*/, "").split(/(?<=\.)\s/)[0];
}
