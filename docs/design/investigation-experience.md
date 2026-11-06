# Investigation experience

How a reader moves through an investigation: the views, the Investigator, the Timeline, the landing, and the
rules for the words on them. The Reality Comparison has its own specification:
[reality-comparison.md](reality-comparison.md).

The order of the experience is **Understand → Explore → Investigate → Verify**. A reader should know what was tested,
what happened, why the next experiment was chosen and what the Oracle verified, without reading JSON.

## Views

| View | Answers | URL |
|---|---|---|
| Overview | The whole case on one page: task, result, what is and is not established, the path taken | `?view=overview` |
| Reality Comparison | What was reported against what was recorded. The default, and the demo's first screen | no `view`, or `?view=reality` |
| Timeline | What happened, in recorded order | `?view=timeline` |
| Investigator | Why each step followed the last | `?view=investigator` |
| Raw evidence | The recorded fields | `?view=evidence` |

**The default stays the Comparison.** The landing's call to action promises a verified failure, and that screen
delivers it. Overview is a tab, not a gate in front of it.

### What stays stable

| Parameter | Meaning |
|---|---|
| `run=` | The run being followed. Every tab keeps it, and a line under the tabs names it, with a way to clear it |
| `cycle=` + `#h3` | Opens that cycle in the Investigator |
| `event=` + `#event-98` | Selects that event on the Timeline, even one folded away |
| `show=all` | Every journal record, flat |
| `call=` + `#trace` | One call's records, from the Comparison |

All of these are links, so back and forward need no code. The investigation's id sits in the header of every view.

### Phone tabs

Five tabs fit one row at 390 px by shortening two visible labels: "Reality" and "Evidence". The accessible name stays
the full one. On a narrower phone they wrap to a second row (tested at 320 px). A scrollable bar was rejected because it hides a section
behind a gesture, which was the defect. A select menu was rejected because it hides all of them behind a tap.

### About, Evidence and limits

Open on Overview and the Comparison. On the other three views they fold into one row, because they repeated the same long
block under every tab.

## Investigator

One **cycle** per recorded hypothesis, collapsed to a row: id, behavior, the Oracle's verdict, and the model's own
reading beside it. Together the rows are a ladder of the investigation. One cycle opens by default: the one asked for,
else the followed run's, else the first VIOLATION, else the first INCONCLUSIVE, else the last.

Each cycle has four ruled rows, in the Comparison's rhythm.

| Stage | Source label | Shows | Behind a fold |
|---|---|---|---|
| Hypothesis | Model's proposal, not a finding | A plain question built from the configured faults, and the suspected failure | Behavior, mechanism, discriminator, motivation |
| Experiment | What was set up and run | Program label, adaptation, that Python was generated and run, sandbox steps, network state, world, policy, configured faults | The generated code |
| Observation | What was recorded | One sentence, reported status, actual outcome, faults delivered, discrepancies, Oracle seal, evidence ids, a link to compare | |
| Decision | What happened next | What the record shows, the model's assessment and what it cited, the model's stated reason for the next step, a link to it | |

### How a decision is chosen

`design/journey.ts` picks one, from named fields only.

| Record | Title | Reason shown |
|---|---|---|
| Next proposal's adaptation is `planned_without_results` or `predetermined_program` | Ran the next planned experiment | **None.** The page says this result did not choose the next experiment |
| Next hypothesis has `revises` | Revised the hypothesis | Its `motivation`, with its citations |
| Next hypothesis has no `revises` | Proposed a new hypothesis | Its `motivation`, with its citations |
| Next run's policy became `hardened` | Investigated the hardened policy | Its `motivation`, with its citations |
| Every next proposal was refused | Next program refused | None |
| Last cycle, `model_concluded` | Concluded: … | None; the conclusion is its own section |
| Last cycle, `plan_finished` | Plan finished | None |
| Last cycle, `generation_failed` | Stopped: no runnable program | None |
| Outcome `budget_exhausted`, `failed`, `cancelled` | Stated as such | None |

A reason is always the model's recorded text, labeled as the model's, and a citation carries the note that it is not
proof of cause. This matters beyond wording: the Sprint 6 benchmark did not demonstrate adaptive value.

Refused programs show no adaptation tag. The contract files them under `first_experiment`, which reads as false on a
program that followed two others.

## Timeline

A vertical rail of **milestones**: start, hypothesis, experiment, each run, Oracle verdict, assessment, conclusion and
final outcome. Records between milestones fold where they stand, and nothing moves. A run is one row, such as
"Agent run: 15 tool calls, 6 faults delivered, reported completed", counted from the records inside it.

| Category | Stages | Default |
|---|---|---|
| Hypothesis | `hypothesis_created`, `hypothesis_revised` | Milestone |
| Experiment | `experiment_generated`, `experiment_rejected` | Milestone |
| Oracle | `oracle_verdict` | Milestone, solid dot |
| Decision | `hypothesis_assessed`, `conclusion` | Milestone |
| Start, Final outcome | `investigation_created`, `investigation_finished` | Milestone |
| Target agent, Tool call, Fault | `target_run_started`, `tool_interaction`, `fault_delivered`, `target_run_finished` | Inside the run's row |
| Sandbox, Model call, Observation | `sandbox_execution`, `model_call`, `observation` | In the run's row if inside it, otherwise behind "Show all" |

An event outside this table is treated as a milestone, so a new stage cannot vanish.

**Recovery** is not a journal stage. It appears as trusted code's classification on the verdict row, "Correct recovery".

Opening an event highlights it and gives one explanation, who recorded it and how far to trust that, its journal
record and hash, its recorded facts as labeled values, and links to the Comparison, the Investigator and itself.

**Marks.** `≠` and a coral dot appear only on a verdict of VIOLATION. A fault stays quiet, because a delivered fault is
not a failure. Sprint 11 suggested `≠` per `call_seq`; that was left out, because it would need every run loaded into
the Timeline for a mark that the Comparison already draws.

**One-shot investigations** show every hypothesis first, then every run, because that is the order they happened in.
Grouping them into cycles here would have told a tidier and false story. Cycles live in the Investigator, where each
decision says this.

## Landing

Hero, then a real case, then How it works, then the list. The hero's copy and actions were already right and did not
change.

The preview is the live `VerdictStrip` of the lead case, read from the evidence API, so it cannot drift from the record.
It is the same component as the Comparison's. With no recorded violation it does not appear.

How it works has four stages, Hypothesize, Experiment, Observe and Verify, down from five and now in the order of the
Investigator. It is static, so its hero link works when the evidence service does not. Below it, "What a verdict does
not show" is where the causal links land.

## Words

Five kinds of statement stay apart, and each is labeled where it appears.

| Kind | Source | Labeled |
|---|---|---|
| Hypothesis | The model | "Model's proposal, not a finding" |
| Observation | Records | "What was recorded" |
| Model interpretation | The model | "The model's assessment", "An interpretation" |
| Oracle verdict | The Oracle | The seal, and only the seal |
| Causal assessment | A registered contrast | "None in this record" unless one exists |

`design/journey.ts` follows `design/story.ts`: no model writes it, no agent text is read for meaning, and no sentence
gives a motive. `rules.spec.ts` runs a pattern for motive words over every generated sentence on all five bundles.
Text the model wrote appears verbatim and under its label, so a recorded hypothesis can still say "believing".

The model's `supported` is not a verified finding. Beside it the page states what the Oracle recorded, including when
the Oracle recorded no VIOLATION.

### Causal evidence

The page keeps "None in this record", which is accurate, and adds a link to what a verdict does not show.

The Sprint 6 follow-up study does hold a contrast for this failure. It stays off the page because no export carries it,
and hardcoding it would put a result in the UI with no provenance. If it is wanted, the smallest honest change is:

```jsonc
// export_version 2, optional on the bundle, absent on every other case
"causal_assessment": {
  "manifest_id": "...",          // the registered study
  "results_sha256": "...",       // pins the result, like study_context()
  "contrast": "full/baseline vs clean/baseline",
  "treated": { "eligible": 3, "violations": 3 },
  "control": { "eligible": 3, "violations": 0 },
  "status": "causal_evidence_supports_fault"
}
```

This was **not implemented**. It needs a contract bump, a re-export of the recorded bundles and new manifest hashes, and
the page is accurate without it. It should wait until the release is over. The figures above are shape only and must
come from the results file.

## First-reader test

No test with a real person has been run. To run one, give a first-time reader the Comparison of the false completion
case, ask these, and write down the answers and any misunderstanding verbatim:

1. What is MOODY BLUES testing?
2. What did the agent report?
3. What actually happened?
4. Why was the next experiment selected?
5. What did the Oracle verify?

Question 4 is the risk. A correct answer says the model's stated reason came from earlier results, not that the
results proved anything. A simulated reader is not evidence and must not be reported as one.

## Sprint 13 refinements

- **Overview:** who and when, then the case, the result and a primary next step, then how it got there. The run shown is the
  ladder's emphasised row. About and limits fold here as on every view but the Comparison, and the recorded-mode note stays
  on screen.
- **Investigator:** titles clamp to two lines while a cycle is closed. Long model text clamps to three lines with a control.
  The stated reason for the next step is never clamped, because it answers the question readers find hardest. Each hypothesis
  that has a recorded reason links back to the Decision holding it, since the reason is stored with the step before.
- **Stage sources** now say whose words follow: Observation is recorded evidence, Decision is the record then the model.
- **Timeline:** unchanged by measurement. See [timeline-performance.md](timeline-performance.md).
- **Landing:** order was already right. The list lost its box and its doubled tag, and System status became one quiet row of
  plain words at the foot.
- **Containment:** moved onto the shared width, headings and rules. Same content.

