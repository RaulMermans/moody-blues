// The first screen of a result, chosen by rule from typed evidence.
//
// Same contract as story.ts: no model writes this, no agent text is read for meaning, and a sentence
// states acts in recorded order, never motives. Each fact appears here once; the evidence behind it
// sits one level down.
import type { InvestigationSummary, RealityRun, ToolEvent } from "@/lib/evidence-types";
import { isModelEvidence } from "@/lib/evidence-types";
import { humanize } from "@/lib/labels";
import { referenceTest } from "@/lib/test-catalog";

import { FAULT_PLAIN } from "./journey";
import { claimRelation, firstDivergence, missionLine, targetNoun } from "./model";
import { environmentLine, hasFinding, stateLine, storyFrom } from "./story";
import { wordsFor } from "./world";

const times = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function joined(items: string[]): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}


export const firstFault = (run: RealityRun): ToolEvent | undefined =>
  run.agent.tool_events.find((e) => e.fault_injected);

/** What the target did after the first delivered fault, counted from the delivery record. */
export function actsAfterFault(run: RealityRun): string {
  const fault = firstFault(run);
  const after = run.agent.tool_events.filter((e) => e.call_seq > (fault?.call_seq ?? 0));
  const words = wordsFor(run);
  const writes = after.filter((e) => e.tool === words.writeTool).length;
  const reads = after.length - writes;
  const parts: string[] = [];
  if (reads) parts.push(`read the ${words.store} ${times(reads, "time", "times")}`);
  if (writes) {
    parts.push(`made ${times(writes, `more ${words.writeVerb} call`, `more ${words.writeVerb} calls`)}`);
  }
  const claim = run.agent.claim;
  parts.push(claim ? `reported ${claim.status}` : "filed no valid report");
  return joined(parts);
}

/** What the first fault did, in plain words, from the fault's own recorded kind. */
export function faultSentence(event: ToolEvent, run: RealityRun): string {
  const { store, record } = wordsFor(run);
  switch (event.fault_injected) {
    case "phantom_failure":
      return `The ${store} saved the ${record}, but the tool reported an error (${event.error_code ?? "unknown"}).`;
    case "phantom_success":
      return `The tool reported a saved ${record}, but nothing was committed.`;
    case "stale_read":
      return `A read returned an old snapshot of the ${store}.`;
    default:
      return `The tool delivered ${humanize(event.fault_injected).toLowerCase()}.`;
  }
}

function headline(run: RealityRun): string {
  const noun = targetNoun(run);
  const who = `The ${noun}`;
  const delivered = run.faults_delivered;
  const duplicate = hasFinding(run, "duplicate_side_effect");
  const { store } = wordsFor(run);
  switch (storyFrom(run).kind) {
    case "false_completion":
      return duplicate
        ? `${who} reported the task complete, but the ${store} holds a duplicate record.`
        : `${who} reported the task complete, but the ${store} does not agree.`;
    case "reported_violation":
      return duplicate
        ? `${who} reported the task not completed, and the ${store} holds a duplicate record.`
        : `${who} reported the task not completed, and the Oracle recorded a violation.`;
    case "unreported_violation":
      return `${who} filed no valid report, and the Oracle recorded a violation.`;
    case "violation":
      return `${who} reported completion, and the Oracle recorded a violation.`;
    case "recovered": {
      const responses = delivered === 1 ? "a misleading response" : `${delivered} misleading responses`;
      return run.finding_class === "correct_recovery"
        ? `${who} handled ${responses} correctly.`
        : `${who} finished the task after ${responses}.`;
    }
    case "clean":
      return `${who} finished the task with no fault in the way.`;
    case "correct_without_claim":
      return `The task was done, but the ${noun} filed no valid report.`;
    case "passed":
      return "The Oracle found no violation in this run.";
    case "no_claim":
      return `${who} ended without a valid report, so nothing is concluded.`;
    case "under_reported":
      return `The task was done, but the ${noun} reported it not completed.`;
    case "inconclusive":
      return "The Oracle could not reach a verdict on this run.";
  }
}

function support(run: RealityRun): string {
  const noun = targetNoun(run);
  const fault = firstFault(run);
  const lead = fault ? `${faultSentence(fault, run)} The ${noun} then ${actsAfterFault(run)}.` : `The ${noun} ${actsAfterFault(run)}.`;
  return run.verdict === "VIOLATION" ? `${lead} Result: ${stateLine(run)}.` : lead;
}

export interface Tested {
  text: string;
  /** Set when the sentence is not from this record, because a catalog line is not a record. */
  source: string | null;
}

export function testedFrom(run: RealityRun, summary: InvestigationSummary): Tested {
  const task = missionLine(run);
  if (task) return { text: task, source: null };
  const reference = referenceTest(summary.target_model);
  if (reference) return { text: reference.task, source: "from the test catalog, not this record" };
  return { text: "The task text is not in this record.", source: null };
}

/** The condition the run was put under, from its fault configuration. */
export function conditionLine(run: RealityRun): string {
  if (!run.faults.length || !run.faults_delivered) return environmentLine(run);
  const kinds = [...new Set(run.faults.map((f) => f.kind))];
  return `Condition: ${joined(kinds.map((k) => FAULT_PLAIN[k] ?? humanize(k).toLowerCase()))}.`;
}

export function verdictMeaning(run: RealityRun): string {
  const ORACLE = `The Oracle, an independent check of the ${wordsFor(run).store}'s saved data,`;
  if (run.verdict === "PASS") return `${ORACLE} found no broken rule in this run.`;
  if (run.verdict === "INCONCLUSIVE") return `${ORACLE} could not decide this run. Nothing is concluded from it.`;
  const broken = run.actual.findings.filter((f) => f.severity === "violation").map((f) => humanize(f.code).toLowerCase());
  return `${ORACLE} found a broken rule: ${joined(broken)}.`;
}

/** Always shown beside a PASS on a script, because a rehearsal says nothing about any model. */
export function targetNote(run: RealityRun): string | null {
  if (isModelEvidence(run.target_evidence)) {
    return run.verdict === "PASS" ? "One run is one sample. It does not show the agent is safe." : null;
  }
  if (run.target_evidence === "external_scripted") {
    return "No AI model ran here. An external script was tested, which says nothing about model behavior.";
  }
  if (run.external) {
    return "No AI model ran here. A labeled fixture answered this agent's model calls, which says nothing about model behavior.";
  }
  return "No AI model ran here. This is a rehearsal of the pipeline, not evidence of model behavior.";
}

/**
 * How the two rows of a comparison relate. The tool's response and the final report are different
 * evidence: a run can hold a misleading response and an accurate report, and those do not conflict.
 */
export function relationLine(run: RealityRun): string {
  const noun = targetNoun(run);
  const divergence = firstDivergence(run) !== null;
  const { store } = wordsFor(run);
  if (run.verdict === "INCONCLUSIVE") return "The Oracle left this run undecided.";
  if (run.verdict === "VIOLATION") {
    if (hasFinding(run, "false_completion_claim")) return `The ${noun}'s final report does not match the ${store}.`;
    if (claimRelation(run) === "unknown") return `The ${noun} filed no valid report, and the violation stands.`;
    return `The ${noun}'s final report matches the ${store}. The violation still stands, because it is in the saved data.`;
  }
  if (!divergence) return "Nothing delivered to the target differed from what was saved.";
  return `These do not conflict. A tool response was misleading, and the ${noun}'s final report matches the ${store}.`;
}

export interface OutcomeCopy {
  headline: string;
  support: string;
}

export const outcomeFrom = (run: RealityRun): OutcomeCopy => ({ headline: headline(run), support: support(run) });
