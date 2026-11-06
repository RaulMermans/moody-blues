// The words on an investigation screen, chosen by rule from typed evidence.
//
// No model writes this, and no agent text is read for meaning. Each sentence states a recorded fact
// or a recorded order of events. It says what happened, never why an agent chose to do something:
// the record holds actions, not motives. Where a case has no rule, the copy gets narrower.
import type {
  CaseStudy,
  InvestigationSummary,
  RealityRun,
  RunList,
  Verdict,
} from "@/lib/evidence-types";
import { humanize, OUTCOME_LABEL } from "@/lib/labels";

import { claimRelation, targetNoun } from "./model";

export type StoryKind =
  | "false_completion"
  | "reported_violation"
  | "unreported_violation"
  | "violation"
  | "recovered"
  | "clean"
  | "correct_without_claim"
  | "passed"
  | "no_claim"
  | "under_reported"
  | "inconclusive";

export interface RunStory {
  kind: StoryKind;
  reported: string;
  reality: string;
  /** True only when the Oracle found a violation and the report and reality disagree. */
  outOfRegister: boolean;
}

export const hasFinding = (run: RealityRun, code: string) =>
  run.actual.findings.some((f) => f.code === code);

/** "The agent", or "The script" when no model ran. Every sentence below names what really acted. */
const subject = (run: RealityRun) => `The ${targetNoun(run)}`;

function storyKind(run: RealityRun): StoryKind {
  const claim = run.agent.claim;
  if (run.verdict === "VIOLATION") {
    if (hasFinding(run, "false_completion_claim")) return "false_completion";
    if (!claim) return "unreported_violation";
    return claim.status === "completed" ? "violation" : "reported_violation";
  }
  if (run.verdict === "PASS") {
    if (run.run_outcome === "state_correct_claim_missing") return "correct_without_claim";
    // A reference script's run never has a `run_outcome`: there the recorded finding class says the same.
    // On any other run a missing outcome stays unknown, so the copy stays narrow.
    const scripted = run.target_evidence === "reference_executor" && run.run_outcome === null;
    const succeeded = run.run_outcome === "success" || (scripted && run.finding_class === "correct_recovery");
    if (!succeeded) return "passed";
    return run.faults_delivered > 0 ? "recovered" : "clean";
  }
  if (!claim) return "no_claim";
  return hasFinding(run, "underreported_completion") ? "under_reported" : "inconclusive";
}

function reportedSentence(run: RealityRun): string {
  const claim = run.agent.claim;
  const who = subject(run);
  if (!claim) return `${who} filed no final report.`;
  if (claim.status === "completed") return `${who} reported completion.`;
  if (claim.status === "not_completed") return `${who} reported the task not completed.`;
  return `${who} reported the status ${claim.status}.`;
}

function realitySentence(kind: StoryKind, run: RealityRun): string {
  const created = run.actual.new_customer_ids.length;
  switch (kind) {
    case "false_completion":
    case "reported_violation":
    case "unreported_violation":
    case "violation":
      return hasFinding(run, "duplicate_side_effect")
        ? "Reality recorded a duplicate."
        : "The Oracle verified a violation.";
    case "recovered":
    case "clean":
      return "Reality agrees.";
    case "correct_without_claim":
    case "under_reported":
      return "Reality shows the task done.";
    case "passed":
      return "The Oracle found no violation.";
    case "no_claim":
      return created === 0
        ? "Reality recorded no new customer."
        : `Reality recorded ${created} new record${created === 1 ? "" : "s"}.`;
    case "inconclusive":
      return "The Oracle could not conclude.";
  }
}

export function storyFrom(run: RealityRun): RunStory {
  const kind = storyKind(run);
  return {
    kind,
    reported: reportedSentence(run),
    reality: realitySentence(kind, run),
    outOfRegister: run.verdict === "VIOLATION" && claimRelation(run) === "differs",
  };
}

export function stateLine(run: RealityRun): string {
  const flagged = run.actual.customers.filter((c) => c.flagged_duplicate).length;
  const created = run.actual.new_customer_ids.length;
  if (flagged > 1) return `${flagged} records committed, 1 required`;
  return `${created} new record${created === 1 ? "" : "s"} committed`;
}

/**
 * What the agent's message says about the flagged records. Only the Oracle's finding may call the
 * status wrong: a run can hold a real duplicate and an accurate `not_completed`.
 */
export function disclosureLine(run: RealityRun): string | null {
  const disclosure = run.agent.disclosure;
  if (!disclosure) return null;
  const { flagged_customer_ids: flagged, not_mentioned_in_message: missing } = disclosure;
  if (missing.length > 0) {
    return `The ${targetNoun(run)}'s message does not name ${missing.length} of ${flagged.length} flagged records. This is an id match and says nothing about intent.`;
  }
  const names = `The ${targetNoun(run)}'s message names all ${flagged.length} flagged records.`;
  if (hasFinding(run, "false_completion_claim")) {
    return `${names} That makes this a wrong status, not concealment.`;
  }
  return `${names} The Oracle recorded no false claim.`;
}

const FAULT_NOUN: Record<string, [string, string]> = {
  phantom_failure: ["phantom failure", "phantom failures"],
  phantom_success: ["phantom success", "phantom successes"],
  stale_read: ["stale read", "stale reads"],
};

function faultNoun(kind: string, count: number): string {
  const nouns = FAULT_NOUN[kind] ?? [humanize(kind).toLowerCase(), `${humanize(kind).toLowerCase()} faults`];
  return count === 1 ? nouns[0] : nouns[1];
}

export interface FaultTally {
  kind: string;
  calls: number[];
}

/** Which calls a fault really reached, read from the delivery record. A selected fault is not one. */
export function faultTally(run: RealityRun): FaultTally[] {
  const tally = new Map<string, number[]>();
  for (const event of run.agent.tool_events) {
    if (event.fault_injected) {
      tally.set(event.fault_injected, [...(tally.get(event.fault_injected) ?? []), event.call_seq]);
    }
  }
  return [...tally].map(([kind, calls]) => ({ kind, calls }));
}

export function environmentLine(run: RealityRun): string {
  const delivered = run.faults_delivered;
  if (delivered === 0) {
    return run.faults.length
      ? `A fault was selected for this run, but none reached the ${targetNoun(run)}.`
      : "No fault was selected for this run.";
  }
  const count = `${delivered} fault${delivered === 1 ? "" : "s"} delivered`;
  const tally = faultTally(run);
  if (tally.reduce((sum, t) => sum + t.calls.length, 0) !== delivered) return `${count}.`;
  const parts = tally.map((t) => `${t.calls.length} ${faultNoun(t.kind, t.calls.length)}`);
  return `${count}: ${parts.join(", ")}.`;
}

function listCalls(calls: number[]): string {
  if (calls.length === 1) return `call ${calls[0]}`;
  return `calls ${calls.slice(0, -1).join(", ")} and ${calls[calls.length - 1]}`;
}

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

const RECOVERY_NOTE: Record<string, string> = {
  idempotent_recovery: "It retried with the same key, and the CRM returned the original record.",
  safe_recovery: "It checked state and ended with exactly one record.",
};

function attempts(run: RealityRun): string {
  const creates = run.agent.tool_events.filter((e) => e.tool === "create_customer").length;
  const commits = run.actual.new_customer_ids.length;
  return `${subject(run)} made ${creates} create call${creates === 1 ? "" : "s"}, and ${commits} committed.`;
}

function happened(kind: StoryKind, run: RealityRun): string {
  const status = run.agent.claim?.status;
  const calls = run.agent.tool_events.length;
  switch (kind) {
    case "false_completion":
      return `${attempts(run)} It filed status ${status}. In authoritative state the objective is not satisfied.`;
    case "reported_violation":
      return `${attempts(run)} It filed status ${status}, which matches the state. The side effect is still real, so the Oracle records a violation.`;
    case "unreported_violation":
      return `${attempts(run)} The run ended as ${humanize(run.agent.termination).toLowerCase()}, with no valid final claim.`;
    case "violation":
      return `${attempts(run)} It filed status ${status}, and the Oracle recorded a violation.`;
    case "recovered": {
      const note = RECOVERY_NOTE[run.agent.recovery_pattern ?? ""] ?? "";
      return `${attempts(run)} ${note} It filed status ${status}, and the objective is satisfied in authoritative state.`.replace("  ", " ");
    }
    case "clean":
      return `${attempts(run)} It filed status ${status}, and the objective is satisfied in authoritative state.`;
    case "correct_without_claim":
      return `The objective is satisfied in authoritative state, but the run ended as ${humanize(run.agent.termination).toLowerCase()}, with no valid final claim.`;
    case "passed":
      return run.run_outcome
        ? `The Oracle found no violation. The recorded run outcome is ${humanize(run.run_outcome).toLowerCase()}.`
        : "The Oracle found no violation. This record holds no separate run outcome.";
    case "no_claim":
      return `The run ended as ${humanize(run.agent.termination).toLowerCase()} after ${calls} tool call${calls === 1 ? "" : "s"}, with no valid final claim. ${attempts(run)}`;
    case "under_reported":
      return `${subject(run)} filed status ${status}, while the objective is satisfied in authoritative state.`;
    case "inconclusive":
      return `${subject(run)} filed status ${status}. The Oracle returned INCONCLUSIVE.`;
  }
}

function sequence(run: RealityRun): string {
  const tally = faultTally(run);
  if (run.faults_delivered === 0 || tally.length === 0) {
    return `No fault reached the ${targetNoun(run)} in this run, so no distortion precedes the outcome.`;
  }
  const faults = tally
    .map((t) => `${capital(listCalls(t.calls))} delivered ${t.calls.length === 1 ? "a " : ""}${faultNoun(t.kind, t.calls.length)}.`)
    .join(" ");
  // Only this run's rows: seeded rows are in the change log too, under call 0.
  const commits = run.actual.customers
    .filter((c) => c.role === "new")
    .map((c) => c.created_by_call)
    .sort((a, b) => a - b);
  const writes = commits.length
    ? `${capital(listCalls(commits))} committed ${commits.length === 1 ? "a write" : "writes"}.`
    : "No write committed.";
  return `${faults} ${writes} That is the recorded order. It does not show why the ${targetNoun(run)} took each step.`;
}

const MATTERS: Record<StoryKind, string> = {
  false_completion:
    "Anything reading the status alone would mark this task done, while the CRM holds a record that should not exist.",
  reported_violation:
    "A true report does not undo a side effect. The extra record stays in the CRM until someone removes it.",
  unreported_violation: "The side effect is real and nothing in a final report says so.",
  violation: "The status reads as done while the Oracle records a broken invariant.",
  recovered:
    "A delivered fault is not by itself a failure. This run is one sample, and it does not show the target is safe.",
  clean: "This run is one sample, and it does not show the target is safe.",
  correct_without_claim: "A missing claim is never read as success, even when the state is correct.",
  passed: "A PASS covers this run only.",
  no_claim: "A missing claim is never read as success. Nothing is concluded from this run.",
  under_reported:
    "The status alone reads as unfinished work while the record exists. The Oracle leaves the run inconclusive.",
  inconclusive: "Nothing is concluded from this run.",
};

export interface CausalFacts {
  faultDelivered: string;
  violationObserved: string;
  causalEvidence: string;
  reproduction: string | null;
}

const OBSERVED: Record<Verdict, string> = {
  VIOLATION: "Yes",
  PASS: "No",
  INCONCLUSIVE: "Not determined",
};

function causalEvidence(run: RealityRun): string {
  if (run.verdict !== "VIOLATION") return "Not applicable: no violation to explain.";
  if (run.faults_delivered === 0) return "No fault was delivered in this run.";
  return "None in this record. It holds no controlled contrast, so causality stays inconclusive here.";
}

/** The study belongs to the case's primary run, so it is never shown on the case's other runs. */
function reproductionLine(study: CaseStudy | null, primary: boolean): string | null {
  if (!study || !primary) return null;
  const impaired = study.impaired_runs
    ? `; ${study.impaired_runs} impaired run${study.impaired_runs === 1 ? " was" : "s were"} not counted`
    : "";
  return `Reproduced in ${study.eligible_reproduced} of ${study.eligible_runs} eligible registered reruns${impaired}. A rerun is not a control.`;
}

export interface Explanation {
  happened: string;
  why: string;
  matters: string;
  causal: CausalFacts;
}

export function explanationFrom(run: RealityRun, study: CaseStudy | null, primary: boolean): Explanation {
  const { kind } = storyFrom(run);
  return {
    happened: happened(kind, run),
    why: sequence(run),
    matters: MATTERS[kind].replace("the target is safe", `the ${targetNoun(run)} is safe`),
    causal: {
      faultDelivered: run.faults_delivered ? `Yes, ${run.faults_delivered}` : "No",
      violationObserved: OBSERVED[run.verdict],
      causalEvidence: causalEvidence(run),
      reproduction: reproductionLine(study, primary),
    },
  };
}

export interface ScopeNote {
  text: string;
  link: { runId: string; label: string } | null;
}

const OUTCOME_VERDICT: Partial<Record<InvestigationSummary["outcome"], Verdict>> = {
  violation_verified: "VIOLATION",
  violation_impaired: "VIOLATION",
  inconclusive: "INCONCLUSIVE",
};

/** A run's verdict is not the investigation's outcome. Says so wherever the two read differently. */
export function scopeNote(summary: InvestigationSummary, runs: RunList, run: RealityRun): ScopeNote | null {
  const wanted = OUTCOME_VERDICT[summary.outcome];
  if (!wanted || run.verdict === wanted) return null;
  const index = runs.runs.findIndex((r) => r.verdict === wanted);
  const text = `This is one of ${runs.runs.length} runs. The investigation as a whole reads ${OUTCOME_LABEL[summary.outcome]}.`;
  if (index < 0) return { text, link: null };
  return { text, link: { runId: runs.runs[index].run_id, label: `Open Run ${index + 1}, ${wanted}` } };
}
