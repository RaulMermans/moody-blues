import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  assessmentCheck,
  type Cycle,
  cyclesFrom,
  cycleVerdicts,
  eventTitle,
  explainEvent,
  holdsRun,
  isMilestone,
  journeyLine,
  openCycle,
  plainQuestion,
  timelineNodes,
  traceLine,
} from "@/design/journey";
import { claimRelation, firstDivergence, recordsFrom, seamFor, sealFromRun, targetNoun } from "@/design/model";
import { conditionLine, outcomeFrom, relationLine, targetNote, testedFrom, verdictMeaning } from "@/design/outcome";
import { stepsFrom } from "@/design/sequence";
import {
  disclosureLine,
  environmentLine,
  explanationFrom,
  faultTally,
  scopeNote,
  stateLine,
  storyFrom,
} from "@/design/story";
import type {
  ExperimentView,
  InvestigationDetail,
  InvestigationSummary,
  RealityRun,
  RunList,
  TimelineEntry,
} from "@/lib/evidence-types";

// The presentation rules, read directly against the committed bundles. No browser and no server.
// `derived` cases are labeled fixtures: a real run with named fields changed, to reach states that no
// recorded run holds. They test the rule and say nothing about any agent.

const DIR = join(__dirname, "..", "..", "evidence", "recorded");

interface Bundle {
  summary: InvestigationSummary;
  case_study: Parameters<typeof explanationFrom>[1];
  runs: RealityRun[];
  experiments: ExperimentView[];
  timeline: TimelineEntry[];
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
    expect(records.map((r) => r.record.id).sort(), run.run_id).toEqual(
      run.actual.customers.filter((c) => c.role === "new").map((c) => c.customer_id).sort(),
    );
    for (const record of records.filter((r) => r.extra)) {
      expect(record.record.flagged_duplicate, run.run_id).toBe(true);
      expect(record.record.named_in_claim, run.run_id).toBe(false);
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

// Sprint 14. `derived` runs reach the rehearsal and empty states no committed bundle holds. Rehearsal
// records are not committed, so these fixtures take a real run and set the fields a script's run has.
const scripted = (run: RealityRun) => {
  run.target_evidence = "reference_executor";
  run.reported_models = [];
  run.run_outcome = null;
  run.agent.mission = null;
  run.agent.recovery_pattern = null;
};
const scriptSummary = { target_model: "reference:verify_then_report" } as InvestigationSummary;

test.describe("the first screen's rules", () => {
  test("a script is a script in every sentence", () => {
    const run = derived(find(RECOVERY), scripted);
    expect(targetNoun(run)).toBe("script");
    const copy = outcomeFrom(run);
    for (const text of [copy.headline, copy.support, storyFrom(run).reported, relationLine(run)]) {
      expect(text).not.toMatch(/\bagent\b/i);
    }
    expect(copy.headline).toContain("The script");
  });

  test("a script's PASS says no model ran; a model's says one run is one sample", () => {
    expect(targetNote(derived(find(RECOVERY), scripted))).toContain("No AI model ran here");
    expect(targetNote(find(RECOVERY))).toContain("does not show the agent is safe");
  });

  test("a task that is not in the record is sourced or admitted, never invented", () => {
    const run = derived(find(RECOVERY), scripted);
    const catalog = testedFrom(run, scriptSummary);
    expect(catalog.source).toContain("not this record");
    const unknown = testedFrom(run, { target_model: "reference:unknown" } as InvestigationSummary);
    expect(unknown.text).toBe("The task text is not in this record.");
  });

  test("a recorded task needs no qualifier", () => {
    expect(testedFrom(find(RECOVERY), scriptSummary).source).toBeNull();
  });

  test("a live run with no recorded outcome keeps the narrow copy", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.run_outcome = null;
    });
    expect(outcomeFrom(run).headline).toBe("The Oracle found no violation in this run.");
  });

  test("a missing claim is never success, on any verdict", () => {
    const pass = derived(find(RECOVERY), (r) => {
      r.agent.claim = null;
      r.run_outcome = "state_correct_claim_missing";
    });
    expect(outcomeFrom(pass).headline).toBe("The task was done, but the agent filed no valid report.");
    expect(outcomeFrom(find(NO_CLAIM)).headline).toContain("without a valid report");
    expect(outcomeFrom(find(NO_CLAIM)).headline).not.toMatch(/correct|success/i);
  });

  test("only a false completion claim may say the report and the CRM disagree", () => {
    expect(relationLine(find(FALSE_COMPLETION))).toContain("does not match the CRM");
    expect(relationLine(find(HONEST))).toContain("matches the CRM");
    expect(relationLine(find(HONEST))).not.toContain("does not match");
  });

  test("the verdict's meaning names only what the Oracle recorded", () => {
    expect(verdictMeaning(find(FALSE_COMPLETION))).toContain("duplicate side effect and false completion claim");
    expect(verdictMeaning(find(RECOVERY))).toContain("found no broken rule");
    expect(verdictMeaning(find(NO_CLAIM))).toContain("could not decide");
  });

  test("a fault that never arrived is not a condition of the run", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.faults_delivered = 0;
      r.agent.tool_events = r.agent.tool_events.map((e) => ({ ...e, fault_injected: null }));
    });
    expect(conditionLine(run)).toContain("none reached the agent");
  });
});

test.describe("the story's rules", () => {
  const detailOf = (evidence: InvestigationSummary["investigator_evidence"]) =>
    ({ summary: { investigator_evidence: evidence } }) as unknown as InvestigationDetail;
  const kinds = (run: RealityRun, evidence: InvestigationSummary["investigator_evidence"], cycle?: Cycle) =>
    stepsFrom(run, detailOf(evidence), cycle).map((s) => s.kind);

  test("a script's story has no Investigator steps, whatever the fixture recorded", () => {
    const cycle = { key: "h1", hypothesis: null, proposals: [], trials: [], decision: { title: "Concluded" } } as unknown as Cycle;
    const run = derived(find(RECOVERY), scripted);
    expect(kinds(run, "offline_fixture", cycle)).toEqual(["attempt", "fault", "actual", "response", "verdict"]);
  });

  test("a run with no fault has no fault step and no invented truth", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.faults_delivered = 0;
      r.discrepancies = [];
      r.agent.tool_events = r.agent.tool_events.map((e) => ({ ...e, fault_injected: null }));
    });
    expect(kinds(run, "offline_fixture")).toEqual(["attempt", "response", "verdict"]);
  });

  test("a run with no calls says so and links nowhere", () => {
    const run = derived(find(NO_CLAIM), (r) => {
      r.agent.tool_events = [];
      r.faults_delivered = 0;
      r.discrepancies = [];
    });
    const steps = stepsFrom(run, detailOf("offline_fixture"), undefined);
    expect(steps.map((s) => s.kind)).toEqual(["response", "verdict"]);
    expect(steps[0].link).toBeNull();
    expect(steps[0].detail).toContain("no valid report");
  });

  test("recovery is named only where the record classifies it", () => {
    const run = derived(find(RECOVERY), (r) => {
      r.finding_class = null;
    });
    const response = stepsFrom(run, detailOf("offline_fixture"), undefined).find((s) => s.kind === "response");
    expect(response?.label).toBe("What the agent did");
  });
});

// The journey: Investigator cycles and Timeline milestones, read against all five bundles.
const journeyOf = (bundle: Bundle, change?: (copy: Bundle) => void): Cycle[] => {
  const copy = structuredClone(bundle);
  change?.(copy);
  const list: RunList = {
    investigation_id: copy.summary.investigation_id,
    primary_run_id: copy.runs[0]?.run_id ?? null,
    runs: copy.runs.map((r) => ({
      run_id: r.run_id,
      experiment_id: r.experiment_id,
      world_ref: r.world_ref,
      config: r.config,
      verdict: r.verdict,
      run_outcome: r.run_outcome,
      faults_delivered: r.faults_delivered,
    })),
  };
  return cyclesFrom(copy as unknown as InvestigationDetail, copy.experiments, copy.runs, list);
};
const detailOf = (bundle: Bundle) => bundle as unknown as InvestigationDetail;
const bundleOf = (id: string) => bundles.find((b) => b.summary.investigation_id === id)!;
const FALSE_CASE = bundleOf("inv_d0bc87de6010");
const HONEST_CASE = bundleOf("inv_4e32358d2ff9");
const PLANNED_CASE = bundleOf("inv_8058b370bc59");
const REFUSED_CASE = bundleOf("inv_5c9f95de6c09");

// What a page may not attribute to anyone. The record holds actions, not motives.
const MOTIVE = /believ|thought|knew|lied|decided|because|realis|realiz|tried to|wanted|in order to/i;

test.describe("investigator cycles", () => {
  test("every run belongs to exactly one cycle, in its recorded numbering", () => {
    for (const bundle of bundles) {
      const seen = journeyOf(bundle).flatMap((c) => c.trials.map((t) => t.run?.run_id));
      expect(seen.sort()).toEqual(bundle.runs.map((r) => r.run_id).sort());
      for (const cycle of journeyOf(bundle)) {
        for (const trial of cycle.trials) {
          expect(bundle.runs[trial.runNumber! - 1].run_id).toBe(trial.run!.run_id);
        }
      }
    }
  });

  test("every hypothesis and proposal is kept, in recorded order", () => {
    for (const bundle of bundles) {
      const detail = detailOf(bundle);
      const cycles = journeyOf(bundle);
      expect(cycles.flatMap((c) => (c.hypothesis ? [c.hypothesis.hypothesis_id] : []))).toEqual(
        detail.hypotheses.map((h) => h.hypothesis_id),
      );
      expect(cycles.flatMap((c) => c.proposals.map((p) => p.proposal_id)).sort()).toEqual(
        detail.proposals.map((p) => p.proposal_id).sort(),
      );
    }
  });

  test("a stated reason is the model's own recorded text, and its citations are real", () => {
    let reasons = 0;
    for (const bundle of bundles) {
      const detail = detailOf(bundle);
      const observations = new Set(detail.observations.map((o) => o.observation_id));
      journeyOf(bundle).forEach((cycle, i, cycles) => {
        const { reason } = cycle.decision;
        if (!reason) return;
        reasons += 1;
        expect(reason.text).toBe(cycles[i + 1].hypothesis?.motivation);
        for (const cite of reason.cites) expect(observations.has(cite), cite).toBe(true);
      });
    }
    expect(reasons).toBeGreaterThan(5);
  });

  test("a result never chose an experiment that was written before it", () => {
    const cycles = journeyOf(PLANNED_CASE);
    for (const cycle of cycles.slice(0, -1)) {
      expect(cycle.decision.kind).toBe("planned");
      expect(cycle.decision.reason).toBeNull();
      expect(cycle.decision.sequence).toContain("did not choose it");
    }
    expect(cycles[cycles.length - 1].decision.kind).toBe("plan_finished");
  });

  test("only the record's own link makes a revision", () => {
    for (const bundle of bundles) {
      journeyOf(bundle).forEach((cycle, i, cycles) => {
        if (cycle.decision.kind === "revised") expect(cycles[i + 1].hypothesis?.revises).toBeTruthy();
        if (cycle.decision.kind === "new_hypothesis") expect(cycles[i + 1].hypothesis?.revises).toBeNull();
      });
    }
  });

  test("refused programs stop the story where the record stops", () => {
    const cycles = journeyOf(REFUSED_CASE);
    const refused = cycles[cycles.length - 1];
    expect(refused.hypothesis).toBeNull();
    expect(refused.proposals).toHaveLength(2);
    expect(refused.trials).toHaveLength(0);
    expect(refused.decision.kind).toBe("generation_failed");
    expect(cycles[cycles.length - 2].decision.kind).toBe("next_refused");
    expect(journeyLine(detailOf(REFUSED_CASE))).toContain("2 generated programs refused");
  });

  test("a conclusion is named as the model's, and a rerun is not hidden", () => {
    const cycles = journeyOf(HONEST_CASE);
    const last = cycles[cycles.length - 1];
    expect(last.decision.kind).toBe("concluded");
    expect(last.trials.filter((t) => t.rerun)).toHaveLength(1);
    expect(last.decision.sequence).toContain("A rerun of the same program");
    // A rerun's verdict is a different run's: it does not restate the cycle's result.
    expect(cycleVerdicts(last)).toEqual(["VIOLATION"]);
  });

  test("stopping for budget or failure is stated, not smoothed over", () => {
    const stopped = (outcome: InvestigationSummary["outcome"]) =>
      journeyOf(FALSE_CASE, (b) => {
        b.summary.outcome = outcome;
        b.summary.termination = null;
      }).at(-1)!.decision;
    expect(stopped("budget_exhausted").kind).toBe("budget");
    expect(stopped("failed").kind).toBe("failed");
    expect(stopped("cancelled").title).toBe("Cancelled");
  });

  test("a supported hypothesis is not a verified one", () => {
    const cycles = journeyOf(FALSE_CASE);
    const supported = cycles.find((c) => c.hypothesis?.status === "supported")!;
    expect(assessmentCheck(supported)).toBe("The Oracle recorded a VIOLATION in this experiment.");
    // Derived: the same assessment with no VIOLATION behind it.
    const unbacked = journeyOf(FALSE_CASE, (b) => {
      b.runs.forEach((r) => (r.verdict = "PASS"));
    }).find((c) => c.hypothesis?.status === "supported")!;
    expect(assessmentCheck(unbacked)).toContain("The Oracle recorded no VIOLATION");
    for (const cycle of cycles.filter((c) => c.hypothesis?.status === "refuted")) {
      expect(assessmentCheck(cycle)).toBeNull();
    }
  });

  test("a reader lands on the cycle that mattered", () => {
    const cycles = journeyOf(FALSE_CASE);
    expect(openCycle(cycles, undefined, undefined)).toBe("h5");
    expect(openCycle(cycles, "h2", undefined)).toBe("h2");
    expect(openCycle(cycles, undefined, "run_d48284d5a019")).toBe("h1");
    expect(openCycle(cycles, "nonsense", undefined)).toBe("h5");
    expect(openCycle(journeyOf(REFUSED_CASE), undefined, undefined)).toBe("h2");
    expect(openCycle([], undefined, undefined)).toBeNull();
  });

  test("an investigation with no record of steps yields no invented ones", () => {
    const cycles = journeyOf(FALSE_CASE, (b) => {
      const detail = b as unknown as InvestigationDetail;
      detail.hypotheses = [];
      detail.proposals = [];
      b.experiments = [];
      b.runs = [];
    });
    expect(cycles).toEqual([]);
  });

  test("the plain question comes from the configured faults and needs a known fault", () => {
    const cycles = journeyOf(FALSE_CASE);
    expect(plainQuestion(cycles[0])).toContain("reports success although it rolled back");
    const unknown = journeyOf(FALSE_CASE, (b) => {
      b.runs.forEach((r) => r.faults.forEach((f) => (f.kind = "new_fault")));
    });
    expect(plainQuestion(unknown[0])).toBeNull();
  });

  test("no rule attributes a motive", () => {
    for (const bundle of bundles) {
      for (const cycle of journeyOf(bundle)) {
        const text = [plainQuestion(cycle), cycle.decision.title, cycle.decision.sequence, assessmentCheck(cycle)];
        expect(text.join(" "), cycle.key).not.toMatch(MOTIVE);
      }
      for (const entry of bundle.timeline) {
        expect(explainEvent(entry, false), entry.stage).not.toMatch(MOTIVE);
      }
    }
  });
});

test.describe("timeline milestones", () => {
  test("folding keeps every record, in recorded order", () => {
    for (const bundle of bundles) {
      const flat = timelineNodes(bundle.timeline).flatMap((n) => (n.kind === "step" ? [n.entry] : n.entries));
      expect(flat.map((e) => e.seq)).toEqual(bundle.timeline.map((e) => e.seq));
    }
  });

  test("a delivered fault is detail, and every verdict and conclusion is a milestone", () => {
    for (const entry of bundles.flatMap((b) => b.timeline)) {
      if (entry.stage === "fault_delivered") expect(isMilestone(entry)).toBe(false);
      if (["oracle_verdict", "conclusion", "investigation_finished", "experiment_rejected"].includes(entry.stage)) {
        expect(isMilestone(entry), entry.stage).toBe(true);
      }
    }
  });

  test("a run's folded row counts what is inside it", () => {
    for (const bundle of bundles) {
      for (const node of timelineNodes(bundle.timeline)) {
        if (node.kind !== "group" || !holdsRun(node.entries)) continue;
        const calls = node.entries.filter((e) => e.stage === "tool_interaction").length;
        const faults = node.entries.filter((e) => e.stage === "fault_delivered").length;
        const finished = node.entries.find((e) => e.stage === "target_run_finished")!;
        expect(faults).toBe(finished.facts.faults_delivered);
        expect(calls).toBe(finished.facts.tool_calls);
        const line = traceLine(node.entries);
        expect(line).toContain(`${calls} tool call`);
        expect(line).toContain(`${faults} fault`);
        expect(line).toContain(
          finished.facts.claim_status ? `reported ${String(finished.facts.claim_status)}` : "filed no final claim",
        );
      }
    }
  });

  test("a fault's explanation never calls it a failure", () => {
    const fault = FALSE_CASE.timeline.find((e) => e.stage === "fault_delivered")!;
    expect(explainEvent(fault, false)).toContain("not by itself a failure");
    expect(eventTitle(fault)).toBe(fault.title);
  });

  test("a verdict's explanation claims the state, not the cause", () => {
    const verdict = FALSE_CASE.timeline.find((e) => e.stage === "oracle_verdict")!;
    expect(explainEvent(verdict, false)).toContain("not why it came about");
  });

  test("a fixture is never described as a model", () => {
    for (const entry of FALSE_CASE.timeline.filter((e) => e.authorship === "investigator_model")) {
      expect(explainEvent(entry, true)).not.toMatch(/\bmodel\b/);
    }
  });
});
