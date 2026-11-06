// The investigation as a reader follows it, chosen by rule from typed evidence.
//
// Same contract as story.ts. No model writes this and no recorded text is read for meaning. Four kinds
// of statement stay apart: a hypothesis is a proposal, an observation is a record, an assessment is the
// model's reading, and only the Oracle gives a verdict. Where the record holds no reason for a step,
// the copy gives the order of events and stops.
import type {
  ExperimentView,
  HypothesisView,
  InvestigationDetail,
  ObservationView,
  ProposalView,
  RealityRun,
  RunList,
  TimelineEntry,
  Verdict,
} from "@/lib/evidence-types";
import { humanize, inRehearsal } from "@/lib/labels";

import { targetNoun } from "./model";

export interface Trial {
  experiment: ExperimentView;
  observation: ObservationView | null;
  run: RealityRun | null;
  /** The run's place in the investigation, as the run picker numbers it. */
  runNumber: number | null;
  rerun: boolean;
}

export type DecisionKind =
  | "revised"
  | "new_hypothesis"
  | "hardened"
  | "planned"
  | "next_refused"
  | "concluded"
  | "plan_finished"
  | "generation_failed"
  | "budget"
  | "failed"
  | "ended";

export interface Decision {
  kind: DecisionKind;
  title: string;
  /** What the record shows happened next. Never a reason. */
  sequence: string;
  /** The reason as the model recorded it, with what it cited. Null when none is on record. */
  reason: { text: string; cites: string[] } | null;
  next: { key: string; label: string } | null;
}

export interface Cycle {
  key: string;
  hypothesis: HypothesisView | null;
  proposals: ProposalView[];
  trials: Trial[];
  decision: Decision;
}

export const FAULT_PLAIN: Record<string, string> = {
  phantom_failure: "a save reports failure although it committed",
  phantom_success: "a save reports success although it rolled back",
  stale_read: "reads come from an old snapshot",
};

const faultKinds = (run: RealityRun | null): string[] => [...new Set(run?.faults.map((f) => f.kind) ?? [])];

function joined(items: string[]): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

const faultNames = (kinds: string[]) =>
  kinds.length ? joined(kinds.map((k) => humanize(k).toLowerCase())) : "no fault";

const firstRun = (cycle: Cycle): RealityRun | null =>
  cycle.trials.find((t) => !t.rerun && t.run)?.run ?? null;

/** The question a hypothesis poses, from the fault its experiment was configured with. */
export function plainQuestion(cycle: Cycle): string | null {
  const kinds = faultKinds(firstRun(cycle));
  if (!kinds.length) return null;
  if (kinds.some((k) => !FAULT_PLAIN[k])) return null;
  const run = firstRun(cycle);
  const noun = run ? targetNoun(run) : "target";
  return `In plain terms: what does the ${noun} do when ${joined(kinds.map((k) => FAULT_PLAIN[k]))}?`;
}

function changeLine(from: Cycle, to: Cycle): string {
  const before = firstRun(from);
  const after = firstRun(to);
  if (!before || !after) return "";
  const parts: string[] = [];
  const was = faultKinds(before).sort().join();
  const now = faultKinds(after).sort().join();
  if (was !== now) {
    parts.push(`The configured faults moved from ${faultNames(faultKinds(before))} to ${faultNames(faultKinds(after))}.`);
  } else {
    parts.push(`The configured fault type stayed ${faultNames(faultKinds(after))}.`);
  }
  if (before.config !== after.config) parts.push(`The policy moved from ${before.config} to ${after.config}.`);
  return parts.join(" ");
}

const labelOf = (cycle: Cycle) => cycle.hypothesis?.hypothesis_id ?? "the next program";

function stepDecision(cycle: Cycle, next: Cycle): Decision {
  const target = { key: next.key, label: labelOf(next) };
  const refused = next.proposals.filter((p) => p.status === "rejected_before_execution");
  if (refused.length === next.proposals.length && next.proposals.length) {
    return {
      kind: "next_refused",
      title: "Next program refused",
      sequence: `The next ${refused.length === 1 ? "program was" : `${refused.length} programs were`} refused before execution, so no further target ran.`,
      reason: null,
      next: target,
    };
  }
  const adaptation = next.proposals[0]?.adaptation;
  if (adaptation === "planned_without_results" || adaptation === "predetermined_program") {
    return {
      kind: "planned",
      title: "Ran the next planned experiment",
      sequence: `The next experiment was written before any run took place, so this result did not choose it. ${changeLine(cycle, next)}`.trim(),
      reason: null,
      next: target,
    };
  }
  const hypothesis = next.hypothesis;
  const cites = [
    ...new Set([
      ...(hypothesis?.motivating_observations ?? []),
      ...next.proposals.flatMap((p) => p.motivated_by),
    ]),
  ];
  const reason = hypothesis?.motivation ? { text: hypothesis.motivation, cites } : null;
  const hardened = firstRun(cycle)?.config !== "hardened" && firstRun(next)?.config === "hardened";
  const revises = hypothesis?.revises;
  return {
    kind: hardened ? "hardened" : revises ? "revised" : "new_hypothesis",
    title: hardened
      ? "Investigated the hardened policy"
      : revises
        ? "Revised the hypothesis"
        : "Proposed a new hypothesis",
    sequence: [
      revises ? `${hypothesis?.hypothesis_id} revises ${revises}.` : `${labelOf(next)} is recorded as a new hypothesis.`,
      changeLine(cycle, next),
    ]
      .filter(Boolean)
      .join(" "),
    reason,
    next: target,
  };
}

function finalDecision(detail: InvestigationDetail): Decision {
  const { termination, outcome, state } = detail.summary;
  const none = { reason: null, next: null };
  if (outcome === "budget_exhausted") {
    return { kind: "budget", title: "Stopped: budget exhausted", sequence: "The investigation ended when its budget ran out.", ...none };
  }
  if (outcome === "failed" || outcome === "cancelled") {
    return { kind: "failed", title: humanize(outcome), sequence: "The investigation did not finish.", ...none };
  }
  if (termination === "generation_failed") {
    return {
      kind: "generation_failed",
      title: "Stopped: no runnable program",
      sequence: "No valid next program was produced within the limits, so the investigation ended here.",
      ...none,
    };
  }
  if (termination === "plan_finished") {
    return {
      kind: "plan_finished",
      title: "Plan finished",
      sequence: "Every planned experiment ran, and the investigation closed.",
      ...none,
    };
  }
  if (termination === "model_concluded" && detail.conclusion) {
    return {
      kind: "concluded",
      title: `Concluded: ${humanize(detail.conclusion.conclusion).toLowerCase()}`,
      sequence: "It proposed no further experiment and filed its conclusion.",
      ...none,
    };
  }
  return { kind: "ended", title: `Ended as ${humanize(termination ?? state).toLowerCase()}`, sequence: "No further step is on record.", ...none };
}

function trialsOf(
  proposals: ProposalView[],
  detail: InvestigationDetail,
  experiments: ExperimentView[],
  runs: RealityRun[],
  list: RunList,
): Trial[] {
  return proposals.flatMap((proposal) =>
    experiments
      .filter((e) => e.proposal_id === proposal.proposal_id)
      .flatMap((experiment) => {
        const observation = detail.observations.find((o) => o.experiment_id === experiment.experiment_id) ?? null;
        const base = { experiment, observation, rerun: experiment.reproduction_of !== null };
        if (!experiment.target_run_ids.length) return [{ ...base, run: null, runNumber: null }];
        return experiment.target_run_ids.map((runId) => {
          const index = list.runs.findIndex((r) => r.run_id === runId);
          return {
            ...base,
            run: runs.find((r) => r.run_id === runId) ?? null,
            runNumber: index < 0 ? null : index + 1,
          };
        });
      }),
  );
}

/**
 * One cycle per recorded hypothesis, in recorded order. Programs with no hypothesis follow: consecutive
 * refused ones share a cycle, because nothing ran between them.
 */
export function cyclesFrom(
  detail: InvestigationDetail,
  experiments: ExperimentView[],
  runs: RealityRun[],
  list: RunList,
): Cycle[] {
  const draft: Omit<Cycle, "decision">[] = detail.hypotheses.map((hypothesis) => {
    const proposals = detail.proposals.filter((p) => p.hypothesis_id === hypothesis.hypothesis_id);
    return {
      key: hypothesis.hypothesis_id,
      hypothesis,
      proposals,
      trials: trialsOf(proposals, detail, experiments, runs, list),
    };
  });
  let refused: ProposalView[] | null = null;
  for (const proposal of detail.proposals.filter((p) => p.hypothesis_id === null)) {
    if (proposal.status === "rejected_before_execution" && refused) {
      refused.push(proposal);
      continue;
    }
    const proposals = [proposal];
    refused = proposal.status === "rejected_before_execution" ? proposals : null;
    draft.push({
      key: proposal.proposal_id,
      hypothesis: null,
      proposals,
      trials: trialsOf(proposals, detail, experiments, runs, list),
    });
  }
  const final = finalDecision(detail);
  const cycles = draft.map((cycle) => {
    const rerun = cycle.trials.some((t) => t.rerun);
    const sequence = rerun ? `${final.sequence} A rerun of the same program is also on record.` : final.sequence;
    return { ...cycle, decision: { ...final, sequence } };
  });
  return cycles.map((cycle, i) =>
    i + 1 < cycles.length ? { ...cycle, decision: stepDecision(cycle, cycles[i + 1]) } : cycle,
  );
}

export const cycleVerdicts = (cycle: Cycle): Verdict[] =>
  cycle.trials.filter((t) => !t.rerun && t.run).map((t) => t.run!.verdict);

/** Which cycle a reader lands on: the one asked for, the run's, the verdict that mattered, or the last. */
export function openCycle(cycles: Cycle[], asked: string | undefined, runId: string | undefined): string | null {
  const named = cycles.find((c) => c.key === asked);
  const ofRun = cycles.find((c) => c.trials.some((t) => t.run?.run_id === runId));
  const holding = (verdict: Verdict) => cycles.find((c) => cycleVerdicts(c).includes(verdict));
  const landing = named ?? ofRun ?? holding("VIOLATION") ?? holding("INCONCLUSIVE") ?? cycles[cycles.length - 1];
  return landing?.key ?? null;
}

/** Sets the model's assessment beside what the Oracle recorded. An assessment is never a verdict. */
export function assessmentCheck(cycle: Cycle): string | null {
  const status = cycle.hypothesis?.status;
  const verdicts = cycleVerdicts(cycle);
  if (status === "not_exercised") {
    return "The fault this hypothesis needed never fired, so this experiment is no evidence either way.";
  }
  if (!status || status === "open" || !verdicts.length) return null;
  const violation = verdicts.includes("VIOLATION");
  if (status === "supported") {
    return violation
      ? "The Oracle recorded a VIOLATION in this experiment."
      : "This is the model's reading. The Oracle recorded no VIOLATION in this experiment.";
  }
  return violation ? "The Oracle recorded a VIOLATION in this experiment, whatever the model's reading." : null;
}

function count(value: number, one: string, many: string): string {
  return `${value} ${value === 1 ? one : many}`;
}

export function journeyLine(detail: InvestigationDetail): string {
  const { experiment_count: experiments, target_run_count: runs } = detail.summary;
  const refused = detail.proposals.filter((p) => p.status === "rejected_before_execution").length;
  const hypotheses = detail.hypotheses.length;
  const lead = hypotheses
    ? `${count(hypotheses, "hypothesis", "hypotheses")}, ${count(experiments, "experiment", "experiments")}`
    : count(experiments, "experiment", "experiments");
  const tail = refused ? `, and ${count(refused, "generated program", "generated programs")} refused before execution` : "";
  return `${lead}, ${count(runs, "target run", "target runs")}${tail}.`;
}

// ---- Timeline ----

const SECONDARY = new Set([
  "model_call",
  "sandbox_execution",
  "target_run_started",
  "tool_interaction",
  "fault_delivered",
  "target_run_finished",
  "observation",
]);

const CATEGORY: Record<string, string> = {
  investigation_created: "Start",
  hypothesis_created: "Hypothesis",
  hypothesis_revised: "Hypothesis",
  hypothesis_assessed: "Decision",
  experiment_generated: "Experiment",
  experiment_rejected: "Experiment",
  model_call: "Model call",
  sandbox_execution: "Sandbox",
  target_run_started: "Target agent",
  target_run_finished: "Target agent",
  tool_interaction: "Tool call",
  fault_delivered: "Fault",
  oracle_verdict: "Oracle",
  observation: "Observation",
  conclusion: "Decision",
  investigation_finished: "Final outcome",
};

export const categoryOf = (entry: TimelineEntry) => CATEGORY[entry.stage] ?? humanize(entry.stage);
export const isMilestone = (entry: TimelineEntry) => !SECONDARY.has(entry.stage);

export type TimelineNode =
  | { kind: "step"; entry: TimelineEntry }
  | { kind: "group"; entries: TimelineEntry[] };

/** Milestones stay in place, and what lies between them folds into one row. Nothing moves. */
export function timelineNodes(entries: TimelineEntry[]): TimelineNode[] {
  const nodes: TimelineNode[] = [];
  for (const entry of entries) {
    const tail = nodes[nodes.length - 1];
    if (isMilestone(entry)) nodes.push({ kind: "step", entry });
    else if (tail?.kind === "group") tail.entries.push(entry);
    else nodes.push({ kind: "group", entries: [entry] });
  }
  return nodes;
}

export const holdsRun = (entries: TimelineEntry[]) => entries.some((e) => e.stage === "target_run_finished");

/** A folded row's summary, counted from the records inside it. */
export function traceLine(entries: TimelineEntry[]): string {
  const of = (stage: string) => entries.filter((e) => e.stage === stage);
  const calls = of("tool_interaction").length;
  const faults = of("fault_delivered").length;
  const finished = of("target_run_finished")[0];
  if (!finished) return count(entries.length, "technical record", "technical records");
  const status = finished.facts.claim_status;
  const claim = typeof status === "string" ? `reported ${status}` : "filed no final claim";
  return `Agent run: ${count(calls, "tool call", "tool calls")}, ${count(faults, "fault", "faults")} delivered, ${claim}`;
}

/** Recorded titles carry enum values in some stages. Tool and fault names stay exact. */
export function eventTitle(entry: TimelineEntry): string {
  if (entry.stage === "tool_interaction" || entry.stage === "fault_delivered") return entry.title;
  return entry.title.replaceAll("_", " ");
}

const list = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);

/** One sentence on what an event is and how far it can be trusted. */
export function explainEvent(entry: TimelineEntry, fixture: boolean): string {
  const line = eventLine(entry, fixture);
  return fixture ? inRehearsal(line) : line;
}

function eventLine(entry: TimelineEntry, fixture: boolean): string {
  const facts = entry.facts;
  const author = fixture ? "fixture" : "model";
  const cited = list(facts.cited_observations);
  switch (entry.stage) {
    case "investigation_created":
      return `Trusted code opened the investigation over ${joined(list(facts.worlds)) || "its worlds"}.`;
    case "hypothesis_created":
      return `A proposal by the ${author}, not a finding.${cited.length ? ` It cites ${joined(cited)}.` : ""}`;
    case "hypothesis_revised":
      return `The ${author} replaced ${String(facts.revises)} with this proposal${cited.length ? `, citing ${joined(cited)}` : ""}. A citation does not prove what caused the change.`;
    case "hypothesis_assessed":
      return `The ${author}'s reading of ${joined(cited) || "the record"}. Only the Oracle gives a verdict.`;
    case "experiment_generated":
      return facts.authorship === "developer_script"
        ? "A developer script, run in the sandbox. No model wrote it."
        : `${String(facts.bytes)} bytes of Python written by the ${author}. It is untrusted and runs only in the sandbox.`;
    case "experiment_rejected":
      return `Refused before execution: ${humanize(String(facts.reason)).toLowerCase()}. Nothing from this program ran.`;
    case "model_call":
      return `One call to the Investigator's ${author}.`;
    case "sandbox_execution":
      return `One step of the experiment in the sandbox, with networking ${facts.network_enabled ? "on" : "off"}. The coordinator's decision: ${String(facts.decision)}.`;
    case "target_run_started":
      if (facts.config === null) return `Trusted code authorized a run with ${faultNames(list(facts.faults))} configured.`;
      return `Trusted code authorized a run under the ${String(facts.config)} policy, with ${faultNames(list(facts.faults))} configured.`;
    case "tool_interaction":
      return "The gateway's record of this call. What the agent was told may have been distorted.";
    case "fault_delivered":
      return "The gateway delivered this fault. A delivered fault is not by itself a failure: the Oracle decides that from committed state.";
    case "target_run_finished":
      return typeof facts.claim_status === "string"
        ? `The agent ended its run and filed status ${facts.claim_status}. That is the agent's assertion, and it may be false.`
        : "The agent ended its run without a valid final claim. A missing claim is never read as success.";
    case "oracle_verdict":
      return "The Oracle read committed state and never saw what the agent was told. This covers one run, and says what is true of the state, not why it came about.";
    case "observation":
      return "Trusted code recorded the experiment's result for the Investigator.";
    case "conclusion":
      return `The ${author}'s conclusion. It is an interpretation, checked against the Oracle's findings.`;
    case "investigation_finished":
      return "Trusted code closed the investigation and wrote this result.";
    default:
      return "A recorded step of this investigation.";
  }
}
