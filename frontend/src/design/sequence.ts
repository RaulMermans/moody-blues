// What happened in a run, as a short sequence of milestones, chosen by rule from typed evidence.
//
// Every step names the record it stands on, and a step with no record is left out rather than filled in:
// runs differ, so the number and kinds of step differ. No step gives a reason. The Investigator's steps
// appear only when a model produced them, and they are labeled as its proposal or decision.
import type { InvestigationDetail, RealityRun } from "@/lib/evidence-types";
import { isModelEvidence } from "@/lib/evidence-types";
import { humanize } from "@/lib/labels";

import type { Cycle } from "./journey";
import { plainQuestion } from "./journey";
import { firstDivergence, targetNoun } from "./model";
import { actsAfterFault, firstFault } from "./outcome";
import { hasFinding } from "./story";

export type StepKind = "hypothesis" | "attempt" | "fault" | "actual" | "response" | "verdict" | "decision";

export type StepLink = { to: "call"; call: number } | { to: "cycle"; cycle: string } | { to: "oracle" };

export interface StoryStep {
  kind: StepKind;
  label: string;
  detail: string;
  link: StepLink | null;
  linkLabel: string | null;
}

const TOOL_ACT: Record<string, string> = {
  create_customer: "asked the CRM to create a customer",
  get_customer: "read a customer from the CRM",
  search_customers: "searched the CRM",
  submit_job: "asked the queue to run a job",
  get_job: "read a job from the queue",
  get_job_status: "read a job's status from the queue",
  list_jobs: "listed the queue",
};

function attemptStep(run: RealityRun): StoryStep | null {
  const first = run.agent.tool_events[0];
  if (!first) return null;
  const act = TOOL_ACT[first.tool] ?? `called ${first.tool}`;
  return {
    kind: "attempt",
    label: "Operation attempted",
    detail: `The ${targetNoun(run)} ${act}.`,
    link: { to: "call", call: first.call_seq },
    linkLabel: `Call ${first.call_seq}`,
  };
}

function faultStep(run: RealityRun): StoryStep | null {
  const fault = firstFault(run);
  if (!fault) return null;
  const more = run.faults_delivered - 1;
  const tail = more > 0 ? ` ${more} more ${more === 1 ? "fault" : "faults"} followed.` : "";
  return {
    kind: "fault",
    label: "Misleading response delivered",
    detail: `The tool said: ${fault.delivered_summary}.${tail}`,
    link: { to: "call", call: fault.call_seq },
    linkLabel: `Call ${fault.call_seq}`,
  };
}

/** The recorded truth, stated once. The Oracle's text is used as written, with only a capital added. */
function actualLine(actually: string, read: boolean): string {
  if (read) return `The true response was: ${actually}.`;
  return `${actually.charAt(0).toUpperCase()}${actually.slice(1)}.`;
}

function actualStep(run: RealityRun): StoryStep | null {
  const divergence = firstDivergence(run);
  const fault = firstFault(run);
  if (!divergence || !fault || divergence.call_seq === null) return null;
  return {
    kind: "actual",
    label: "Actual state",
    detail: actualLine(divergence.actually, fault.fault_injected === "stale_read"),
    link: { to: "call", call: divergence.call_seq },
    linkLabel: `Call ${divergence.call_seq}`,
  };
}

function responseStep(run: RealityRun): StoryStep {
  const noun = targetNoun(run);
  const recovered = run.finding_class === "correct_recovery" && firstFault(run) !== undefined;
  return {
    kind: "response",
    label: recovered ? "Recovery observed" : `What the ${noun} did`,
    detail: `It ${actsAfterFault(run)}.`,
    link: run.agent.tool_events.length ? { to: "call", call: run.agent.tool_events[run.agent.tool_events.length - 1].call_seq } : null,
    linkLabel: run.agent.tool_events.length ? "Every call" : null,
  };
}

function verdictStep(run: RealityRun): StoryStep {
  const broken = run.actual.findings.filter((f) => f.severity === "violation").map((f) => humanize(f.code).toLowerCase());
  const evaluated = run.actual.invariants_evaluated.length;
  const detail =
    run.verdict === "VIOLATION"
      ? `${run.verdict}: ${broken.join(", ")}.`
      : run.verdict === "PASS"
        ? `${run.verdict}: ${evaluated} ${evaluated === 1 ? "rule" : "rules"} checked, none broken.`
        : hasFinding(run, "underreported_completion")
          ? `${run.verdict}: the report and the saved data disagree, so the Oracle did not decide.`
          : `${run.verdict}: the record does not settle this run.`;
  return { kind: "verdict", label: "Oracle outcome", detail, link: { to: "oracle" }, linkLabel: "Findings" };
}

function hypothesisStep(cycle: Cycle): StoryStep | null {
  const hypothesis = cycle.hypothesis;
  if (!hypothesis) return null;
  const question = plainQuestion(cycle)?.replace("In plain terms: w", "W");
  return {
    kind: "hypothesis",
    label: "Hypothesis",
    detail: question ?? hypothesis.behavior,
    link: { to: "cycle", cycle: cycle.key },
    linkLabel: `The model's proposal, ${hypothesis.hypothesis_id}`,
  };
}

function decisionStep(cycle: Cycle): StoryStep {
  return {
    kind: "decision",
    label: "Investigator decision",
    detail: `${cycle.decision.title}.`,
    link: { to: "cycle", cycle: cycle.key },
    linkLabel: "Its recorded step",
  };
}

const present = <T,>(items: (T | null)[]): T[] => items.filter((item): item is T => item !== null);

/**
 * A model-led investigation opens on its hypothesis and closes on its decision. A script run has
 * neither, so it opens on the operation. The Investigator's steps are a model's, never a fixture's.
 */
export function stepsFrom(run: RealityRun, detail: InvestigationDetail, cycle: Cycle | undefined): StoryStep[] {
  const modelLed = isModelEvidence(detail.summary.investigator_evidence) && cycle !== undefined;
  return present([
    modelLed ? hypothesisStep(cycle) : attemptStep(run),
    faultStep(run),
    actualStep(run),
    responseStep(run),
    verdictStep(run),
    modelLed ? decisionStep(cycle) : null,
  ]);
}
