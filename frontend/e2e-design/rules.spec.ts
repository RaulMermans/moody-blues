import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { claimRelation, firstDivergence, recordsFrom, seamFor, sealFromRun } from "@/design/model";
import {
  disclosureLine,
  environmentLine,
  explanationFrom,
  faultTally,
  scopeNote,
  stateLine,
  storyFrom,
} from "@/design/story";
import type { InvestigationSummary, RealityRun, RunList } from "@/lib/evidence-types";

// The presentation rules, read directly against the committed bundles. No browser and no server.
// `derived` cases are labeled fixtures: a real run with named fields changed, to reach states that no
// recorded run holds. They test the rule and say nothing about any agent.

const DIR = join(__dirname, "..", "..", "evidence", "recorded");

interface Bundle {
  summary: InvestigationSummary;
  case_study: Parameters<typeof explanationFrom>[1];
  runs: RealityRun[];
}

const bundles: Bundle[] = readdirSync(DIR)
  .filter((f) => f.startsWith("inv_"))
  .map((f) => JSON.parse(readFileSync(join(DIR, f), "utf-8")) as Bundle);
const allRuns = bundles.flatMap((b) => b.runs);
const find = (id: string) => {
  const run = allRuns.find((r) => r.run_id === id);
  if (!run) throw new Error(id);
  return run;
};
const derived = (run: RealityRun, change: (copy: RealityRun) => void): RealityRun => {
  const copy = structuredClone(run);
  change(copy);
  return copy;
};

const FALSE_COMPLETION = "run_cc34d7a6e314";
const HONEST = "run_e9f3ebda139d";
const UNDER_REPORT = "run_422f9afbb127";
const NO_CLAIM = "run_8145a6bc00d7";
const RECOVERY = "run_40e0756c04f2";

test("the bundles cover every case the sprint must render", () => {
  expect(allRuns.length).toBe(20);
  const kinds = new Set(allRuns.map((r) => storyFrom(r).kind));
  for (const kind of ["false_completion", "reported_violation", "recovered", "no_claim", "under_reported"]) {
    expect(kinds, kind).toContain(kind);
  }
});

test("a headline agrees with the verdict on every recorded run", () => {
  for (const run of allRuns) {
    const story = storyFrom(run);
    const text = `${story.reported} ${story.reality}`;
    if (run.verdict === "VIOLATION") expect(text, run.run_id).toMatch(/duplicate|violation/);
    else expect(text, run.run_id).not.toMatch(/duplicate|violation/i);
    if (run.verdict === "INCONCLUSIVE") expect(story.reality, run.run_id).not.toBe("Reality agrees.");
    if (!run.agent.claim) expect(story.reported, run.run_id).toBe("The agent filed no final report.");
    expect(text, run.run_id).not.toMatch(/believ|thought|knew|lied|decided/i);
  }
});

test("only a violation where report and reality disagree goes out of register", () => {
  for (const run of allRuns) {
    const expected = run.actual.findings.some((f) => f.code === "false_completion_claim");
    expect(storyFrom(run).outOfRegister, run.run_id).toBe(expected);
  }
  expect(storyFrom(find(HONEST)).outOfRegister).toBe(false);
});

test("a seam breaks only for a recorded difference in a VIOLATION", () => {
  for (const run of allRuns) {
    expect(seamFor(run, "equal"), run.run_id).toBe("steady");
    expect(seamFor(run, "differs"), run.run_id).toBe(run.verdict === "VIOLATION" ? "break" : "distortion");
  }
  expect(claimRelation(find(HONEST))).toBe("equal");
  expect(claimRelation(find(FALSE_COMPLETION))).toBe("differs");
  expect(claimRelation(find(UNDER_REPORT))).toBe("differs");
  expect(claimRelation(find(NO_CLAIM))).toBe("unknown");
});

test("a disclosure never calls an accurate status wrong", () => {
  // Regression: the line said "wrong status" for every disclosure, including an honest not_completed.
  expect(disclosureLine(find(FALSE_COMPLETION))).toContain("wrong status, not concealment");
  expect(disclosureLine(find(HONEST))).not.toContain("wrong status");
  expect(disclosureLine(find(HONEST))).toContain("no false claim");
  expect(disclosureLine(find(RECOVERY))).toBeNull();
});

test("an undisclosed record is an id match, and claims nothing about intent", () => {
  const run = derived(find(FALSE_COMPLETION), (r) => {
    r.agent.disclosure!.not_mentioned_in_message = [r.agent.disclosure!.flagged_customer_ids[1]];
  });
  expect(disclosureLine(run)).toContain("does not name 1 of 2");
  expect(disclosureLine(run)).toContain("says nothing about intent");
});

test("the fault tally equals the delivered count on every run", () => {
  for (const run of allRuns) {
    const sum = faultTally(run).reduce((total, t) => total + t.calls.length, 0);
    expect(sum, run.run_id).toBe(run.faults_delivered);
  }
});

test("a selected fault that never arrived is not called delivered", () => {
  const run = derived(find(RECOVERY), (r) => {
    r.faults_delivered = 0;
    r.agent.tool_events.forEach((e) => (e.fault_injected = null));
  });
  expect(environmentLine(run)).toBe("A fault was selected for this run, but none reached the agent.");
  expect(storyFrom(run).kind).toBe("clean");
});

test("a sequence names only calls the record shows, and never a seed row", () => {
  // Regression: seeded rows sit in the change log under call 0, and were read as the agent's writes.
  for (const run of allRuns) {
    const { why } = explanationFrom(run, null, false);
    expect(why, run.run_id).not.toMatch(/\bcalls? 0\b|\b0 and\b|\b0, /i);
    expect(why, run.run_id).toContain("does not show why");
  }
  expect(explanationFrom(find(FALSE_COMPLETION), null, false).why).toContain("Calls 4 and 7 committed writes");
});

test("no explanation claims a cause or a motive", () => {
  for (const run of allRuns) {
    const e = explanationFrom(run, null, false);
    const text = `${e.happened} ${e.why} ${e.matters}`;
    expect(text, run.run_id).not.toMatch(/because the fault|caused|due to|drove|believ|intend|tried to hide/i);
    if (run.verdict === "VIOLATION") {
      expect(e.causal.causalEvidence, run.run_id).toContain("causality stays inconclusive");
    } else {
      expect(e.causal.causalEvidence, run.run_id).toContain("Not applicable");
    }
  }
});

test("a delivered fault without a violation stays two separate facts", () => {
  const { causal } = explanationFrom(find(RECOVERY), null, false);
  expect(causal.faultDelivered).toBe("Yes, 3");
  expect(causal.violationObserved).toBe("No");
});

test("reproduction belongs to the case's primary run only", () => {
  const bundle = bundles.find((b) => b.case_study)!;
  const primary = bundle.summary.case!.primary_run_id;
  for (const run of bundle.runs) {
    const line = explanationFrom(run, bundle.case_study, run.run_id === primary).causal.reproduction;
    if (run.run_id === primary) expect(line).toContain("A rerun is not a control");
    else expect(line, run.run_id).toBeNull();
  }
});

test("a run that reads differently from its investigation says so", () => {
  for (const bundle of bundles) {
    const list: RunList = {
      investigation_id: bundle.summary.investigation_id,
      primary_run_id: null,
      runs: bundle.runs.map((r) => ({ ...r, experiment_id: r.experiment_id })),
    };
    for (const run of bundle.runs) {
      const note = scopeNote(bundle.summary, list, run);
      const wanted =
        bundle.summary.outcome === "violation_verified"
          ? "VIOLATION"
          : bundle.summary.outcome === "inconclusive"
            ? "INCONCLUSIVE"
            : null;
      if (wanted === null || run.verdict === wanted) expect(note, run.run_id).toBeNull();
      else expect(note?.link?.label, run.run_id).toContain(wanted);
    }
  }
});

test("the extra record of a duplicate is a real row, and only that row", () => {
  for (const run of allRuns) {
    const records = recordsFrom(run);
    expect(records.map((r) => r.customer.customer_id).sort(), run.run_id).toEqual(
      run.actual.customers.filter((c) => c.role === "new").map((c) => c.customer_id).sort(),
    );
    for (const record of records.filter((r) => r.extra)) {
      expect(record.customer.flagged_duplicate, run.run_id).toBe(true);
      expect(record.customer.named_in_claim, run.run_id).toBe(false);
    }
  }
  expect(recordsFrom(find(FALSE_COMPLETION)).filter((r) => r.extra)).toHaveLength(1);
  expect(recordsFrom(find(RECOVERY)).filter((r) => r.extra)).toHaveLength(0);
});

test("the first divergence is the earliest located discrepancy", () => {
  expect(firstDivergence(find(FALSE_COMPLETION))?.call_seq).toBe(1);
  expect(firstDivergence(find(HONEST))?.call_seq).toBe(2);
  const none = derived(find(RECOVERY), (r) => {
    r.discrepancies = [];
  });
  expect(firstDivergence(none)).toBeNull();
});

test.describe("derived fixtures: states no recorded run reaches", () => {
  test("a correct state with no claim is never success", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.run_outcome = "state_correct_claim_missing";
      r.agent.claim = null;
      r.agent.termination = "no_final_claim";
    });
    expect(storyFrom(run).kind).toBe("correct_without_claim");
    expect(storyFrom(run).reported).toBe("The agent filed no final report.");
    const seal = sealFromRun(run);
    expect(seal.kind === "verdict" && seal.qualifier).toContain("Not a success");
  });

  test("a violation with no claim is not a false completion", () => {
    const run = derived(find(HONEST), (r) => {
      r.agent.claim = null;
      r.agent.termination = "max_steps";
    });
    expect(storyFrom(run).kind).toBe("unreported_violation");
    expect(storyFrom(run).outOfRegister).toBe(false);
    expect(explanationFrom(run, null, false).happened).toContain("no valid final claim");
  });

  test("a violation that is not a duplicate does not claim one", () => {
    const run = derived(find(FALSE_COMPLETION), (r) => {
      r.actual.findings = r.actual.findings.filter((f) => f.code !== "duplicate_side_effect");
    });
    expect(storyFrom(run).reality).toBe("The Oracle verified a violation.");
  });

  test("an impaired run carries its qualifier on the seal", () => {
    const run = derived(find(FALSE_COMPLETION), (r) => {
      r.impairments = ["token_budget"];
    });
    const seal = sealFromRun(run);
    expect(seal.kind === "verdict" && seal.qualifier).toContain("Impaired run");
  });

  test("a status outside the contract is quoted, not interpreted", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.agent.claim!.status = "partial";
    });
    expect(storyFrom(run).reported).toBe("The agent reported the status partial.");
  });

  test("an unknown outcome gets the narrow description", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.run_outcome = null;
    });
    expect(storyFrom(run).kind).toBe("passed");
    expect(storyFrom(run).reality).toBe("The Oracle found no violation.");
  });

  test("a missing mission and an empty run still produce plain statements", () => {
    const run = derived(find(NO_CLAIM), (r) => {
      r.agent.mission = null;
      r.agent.tool_events = [];
      r.faults_delivered = 0;
      r.faults = [];
    });
    expect(stateLine(run)).toBe("0 new records committed");
    expect(environmentLine(run)).toBe("No fault was selected for this run.");
    expect(explanationFrom(run, null, false).why).toContain("No fault reached the agent");
  });
});
