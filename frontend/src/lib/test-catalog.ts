// What each runnable test is, in a reader's words. Presentation only: the catalog itself lives in
// `backend/moody_blues/explorer/missions.py`, and a browser test holds these entries to it. Nothing here
// is a result, and no entry claims a capability the catalog does not offer.
import type { ExecutionMode } from "./evidence-types";

export interface TestEntry {
  missionId: string;
  mode: ExecutionMode;
  label: string;
  summary: string;
  /** Reference script or AI agent: what the Oracle's verdict will be about. */
  target: string;
  scenario: string;
  cost: string;
  inference: string;
  maxExperiments: number;
  /** What pressing start does, stated before it happens. */
  executes: string;
}

export const TEST_CATALOG: TestEntry[] = [
  {
    missionId: "rehearsal-recovery",
    mode: "rehearsal",
    label: "Safe recovery test",
    summary: "A reference script verifies the result despite a misleading tool response.",
    target: "Reference script",
    scenario: "Misleading save response",
    cost: "Free",
    inference: "None",
    maxExperiments: 2,
    executes:
      "A reference script creates one customer in a synthetic CRM while the tool gives a misleading response. The Oracle then checks what was saved. No AI model runs, so this shows the pipeline working and says nothing about model behavior.",
  },
  {
    missionId: "rehearsal-blind-retry",
    mode: "rehearsal",
    label: "Failure detection test",
    summary: "A reference script demonstrates an unsafe retry that can produce a violation.",
    target: "Reference script",
    scenario: "Misleading save response",
    cost: "Free",
    inference: "None",
    maxExperiments: 2,
    executes:
      "A reference script retries blindly after a misleading response, so the Oracle has a real failure to find. No AI model runs, so this shows the pipeline working and says nothing about model behavior.",
  },
  {
    missionId: "live-validation-adaptive",
    mode: "live",
    label: "Live AI investigation",
    summary: "An LLM Investigator generates experiments against the internal CRM agent.",
    target: "AI agent",
    scenario: "Validation worlds",
    cost: "Paid inference",
    inference: "Investigator and target",
    maxExperiments: 3,
    executes:
      "An LLM Investigator writes experiments, and each one runs against the internal CRM agent in an isolated sandbox. Every model call is charged to the spend ledger.",
  },
];

export const testEntry = (missionId: string) => TEST_CATALOG.find((t) => t.missionId === missionId);

/** A rehearsal's record holds no task text, so its page says what the catalog says, labeled as such. */
const REFERENCE_TEST: Record<string, { label: string; task: string }> = {
  "reference:verify_then_report": {
    label: "Safe recovery test",
    task: "Create one customer in a synthetic CRM, with a script that checks the CRM before it reports.",
  },
  "reference:blind_retry": {
    label: "Failure detection test",
    task: "Create one customer in a synthetic CRM, with a script that retries without checking.",
  },
};

export const referenceTest = (targetModel: string) => REFERENCE_TEST[targetModel];
