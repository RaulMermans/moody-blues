import type { Authorship, CaseKind, ExecutionMode, ProductOutcome, Verdict } from "./evidence-types";

export const OUTCOME_LABEL: Record<ProductOutcome, string> = {
  violation_verified: "Violation verified",
  violation_impaired: "Violation in an impaired run",
  no_violation_found: "No violation found",
  inconclusive: "Inconclusive",
  outcome_uncertain: "Outcome uncertain",
  failed: "Failed",
  cancelled: "Cancelled",
  budget_exhausted: "Budget exhausted",
};

export const OUTCOME_TONE: Record<ProductOutcome, Tone> = {
  violation_verified: "bad",
  violation_impaired: "warn",
  no_violation_found: "good",
  inconclusive: "warn",
  outcome_uncertain: "warn",
  failed: "neutral",
  cancelled: "neutral",
  budget_exhausted: "neutral",
};

export type Tone = "bad" | "good" | "warn" | "neutral" | "agent" | "truth";

export const VERDICT_TONE: Record<Verdict, Tone> = {
  PASS: "good",
  VIOLATION: "bad",
  INCONCLUSIVE: "warn",
};

export const MODE_LABEL: Record<ExecutionMode, string> = {
  recorded: "Recorded investigation",
  live: "Live investigation",
  rehearsal: "Rehearsal, no model",
};

export const MODE_NOTE: Record<ExecutionMode, string> = {
  recorded: "A real past execution, exported from its records. It is not running now.",
  live: "A real model-driven investigation started from this application.",
  rehearsal:
    "Real sandboxes, world and Oracle, driven by a fixture and a reference script. Not evidence of model behavior.",
};

export const CASE_LABEL: Record<CaseKind, string> = {
  verified_violation: "False completion",
  honest_violation: "Honest failure",
  successful_recovery: "Recovery",
  negative_result: "Negative result",
  inconclusive: "Inconclusive",
};

export const STRATEGY_LABEL: Record<string, string> = {
  fixed: "Fixed",
  one_shot: "Non-adaptive",
  adaptive: "Adaptive",
};

export const AUTHOR_LABEL: Record<Authorship, string> = {
  investigator_model: "Investigator model",
  coordinator: "Coordinator",
  sandbox: "Sandbox",
  gateway: "Gateway",
  target_agent: "Target agent",
  oracle: "Truth Oracle",
};

export const AUTHOR_NOTE: Record<Authorship, string> = {
  investigator_model: "Interpretation, not fact",
  coordinator: "Trusted record",
  sandbox: "Untrusted code, checked by the coordinator",
  gateway: "True record of delivery; content may be distorted",
  target_agent: "Asserted by the target; may be false",
  oracle: "Authoritative",
};

export const AUTHOR_TONE: Record<Authorship, Tone> = {
  investigator_model: "neutral",
  coordinator: "neutral",
  sandbox: "neutral",
  gateway: "warn",
  target_agent: "agent",
  oracle: "truth",
};

export const FAULT_LABEL: Record<string, string> = {
  phantom_failure: "Phantom failure: the write committed, the agent was told it failed",
  phantom_success: "Phantom success: the write rolled back, the agent was told it worked",
  stale_read: "Stale read: the read came from an old snapshot",
};

export const DISCREPANCY_LABEL: Record<string, string> = {
  misleading_write_response: "Misleading write",
  stale_read: "Stale read",
  claim_versus_state: "Claim against state",
  duplicate_side_effect: "Duplicate side effect",
};

export const ADAPTATION_LABEL: Record<string, { title: string; note: string }> = {
  first_experiment: { title: "First experiment", note: "No prior observation existed." },
  cited_prior_observations: {
    title: "Cited prior observations",
    note: "The model named earlier results. A citation is not proof they caused this choice; Sprint 6 did not demonstrate adaptive value.",
  },
  planned_without_results: {
    title: "Planned without results",
    note: "Written before any experiment ran.",
  },
  predetermined_program: { title: "Predetermined program", note: "No model chose this." },
};

export const FINDING_CLASS_LABEL: Record<string, string> = {
  oracle_confirmed_violation: "Oracle-confirmed violation",
  impaired_violation: "Violation in an impaired run",
  impaired_run: "Impaired run",
  target_shortfall: "Agent shortfall",
  correct_recovery: "Correct recovery",
  clean_success: "Clean success",
};

export const REPRODUCTION_LABEL: Record<string, string> = {
  reproduced: "Reproduced",
  not_reproduced: "Not reproduced",
  untested: "Not retested here",
  not_applicable: "Not applicable",
};

export const BLOCKED_LABEL: Record<string, string> = {
  another_job_running: "Another investigation is running.",
  live_runs_disabled: "Live runs are disabled on this server.",
  provider_not_configured: "No provider credentials are configured.",
  ledger_unreadable: "The spend ledger is unreadable, so all spending is refused.",
  budget_insufficient: "The spend ledger does not cover one investigation.",
};

export const JOB_STATUS_LABEL: Record<string, string> = {
  created: "Created",
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  budget_exhausted: "Budget exhausted",
  outcome_uncertain: "Outcome uncertain",
};

export const JOB_EVENT_LABEL: Record<string, string> = {
  created: "Job created",
  queued: "Queued",
  running: "Running",
  cancel_requested: "Cancellation requested",
  experiment_completed: "Experiment completed",
  finding_verified: "Finding verified by the Oracle",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  budget_exhausted: "Budget exhausted",
  outcome_uncertain: "Outcome uncertain",
};

const SCRIPT_WORDS: [string, string][] = [
  ["Target agent", "Reference script"],
  ["Agent run", "Script run"],
  ["Agent reported", "Script reported"],
  ["Investigator model", "Investigator fixture"],
  ["Model call", "Fixture call"],
  ["the agent", "the script"],
  ["The agent", "The script"],
  ["agent's", "script's"],
  ["the model", "the fixture"],
  ["The model", "The fixture"],
  ["model's", "fixture's"],
];

/**
 * Shared words as they read in a rehearsal, where a fixture stood in for the model and a reference
 * script for the agent. A recorded protocol name such as `run_target_agent` is never passed through this.
 */
export function inRehearsal(text: string): string {
  return SCRIPT_WORDS.reduce((copy, [from, to]) => copy.replaceAll(from, to), text);
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "none";
  const text = code.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function formatWhen(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

export function formatClock(iso: string): string {
  return new Date(iso).toISOString().slice(11, 19);
}
