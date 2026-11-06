# Reality Comparison: UX specification

The primary screen of an investigation: `/investigations/{id}?view=reality&run={run}`.

## The north star

| Level | Time | The reader learns | Where |
|---|---|---|---|
| Understand | ~10 s | The task, the report, the outcome, the verdict | Headline and strip, in the first screen on every run at 390, 768 and 1440 px |
| Explore | ~30 s | The distortion, what the agent did, where outcomes diverged, why it matters | Notes, comparison rows, explanation |
| Investigate | As needed | Tool calls, responses, committed state, traces, fault events, timestamps, ids, verdict, run outcome | Ledger, records, Timeline, Investigator, Raw evidence |

The times are design targets. They were not measured with users.

## Page order

1. **Context:** breadcrumb, investigation outcome, case label, recorded/live label, tabs.
2. **Summary:** run position, target label, headline, then Task, Agent reported, Actual outcome, Oracle verdict.
3. **Notes:** Disclosure, Environment and Scope, each only where it applies.
4. **Run picker:** every run, with its verdict as a glyph and a word.
5. **Comparison:** three paired rows (below).
6. **The evidence, explained:** three questions and the causal facts.
7. **Every tool call:** a ledger. A whole row is one disclosure, and it holds arguments, response, the agent's note and a timeline link.
8. **Discrepancies, records, Go deeper, About, Evidence and limits.**

Model names, internal ids, fault configuration and costs are off the first screen. They are in About and Raw evidence.

## The comparison rows

Rows, not two columns of content: a phone and a screen reader meet both sides of one event together.

| Row | Agent-reported side | Authoritative side | Glyph |
|---|---|---|---|
| Outcome | Filed status, the id in the structured claim, create attempts | Count of new records, one slab per real row, seeded rows counted | From `claim_versus_state` |
| First divergence | What the earliest located discrepancy delivered | What was true at that call | Always `≠` |
| Statement | The agent's whole message, always visible | Verdict, run outcome, finding class, findings, invariant counts, diagnostics | As Outcome |

Below 720 px rows stack, the seam turns horizontal, and each side's label names its reality.

## Copy rules

All copy comes from `frontend/src/design/story.ts`. It is written by rule from typed fields. No model writes it
and no agent text is read for meaning.

| Story | Condition | Headline |
|---|---|---|
| `false_completion` | `VIOLATION` with `false_completion_claim` | The agent reported completion. Reality recorded a duplicate. |
| `reported_violation` | `VIOLATION`, a claim that is not `completed` | The agent reported the task not completed. Reality recorded a duplicate. |
| `unreported_violation` | `VIOLATION`, no claim | The agent filed no final report. Reality recorded a duplicate. |
| `violation` | `VIOLATION`, otherwise | The agent reported completion. Reality recorded a duplicate. |
| `recovered` | `PASS`, `success`, faults delivered | The agent reported completion. Reality agrees. |
| `clean` | `PASS`, `success`, no fault delivered | The agent reported completion. Reality agrees. |
| `correct_without_claim` | `PASS`, `state_correct_claim_missing` | The agent filed no final report. Reality shows the task done. |
| `passed` | `PASS`, any other outcome | Reported sentence, then: The Oracle found no violation. |
| `no_claim` | `INCONCLUSIVE`, no claim | The agent filed no final report. Reality recorded no new customer. |
| `under_reported` | `INCONCLUSIVE`, `underreported_completion` | The agent reported the task not completed. Reality shows the task done. |
| `inconclusive` | `INCONCLUSIVE`, otherwise | Reported sentence, then: The Oracle could not conclude. |

Without a `duplicate_side_effect` finding, a violation's second sentence narrows to "The Oracle verified a
violation." A status outside the contract is quoted and never interpreted.

### What the copy may not do

- Say why an agent did something. The record holds actions, not motives.
- Call a status wrong without the Oracle's `false_completion_claim`.
- Describe a missing claim as a false completion, or as a success.
- Count a selected fault as delivered, or a seeded row as the agent's write.
- Call a run safe. A PASS covers that run.

When no rule fits, the sentence gets narrower, and the ledger and Timeline remain one step away.

## Causality

Four facts stay separate: **fault delivered**, **violation observed**, **causal evidence**, and whether
causality stands. The "Why did it happen?" answer gives the recorded order and says it does not show why.

The page says "None in this record" for causal evidence, with a link to what a verdict does not show. That wording
is exact and deliberate. The Sprint 6
follow-up study does hold a clean contrast for this failure (`full/baseline` against `clean/baseline`, 3/3 and 0/3,
`causal_evidence_supports_fault`), but that result is not in the investigation bundle, and the UI never holds
a result. Showing it needs the export to carry it, which is backend work:
[proposal](investigation-experience.md#causal-evidence). Reproduction ("4 of 4 eligible reruns")
is shown on the primary run only, and it is labeled as not being a control.

## Navigation

| From | To | Mechanism |
|---|---|---|
| Any tab | Any tab, same run | `run` stays in every tab link |
| Scope note | The run that gave the investigation its outcome | `?view=reality&run=` |
| Record slab | The call that committed it | `#call-N` |
| First divergence | That call in the ledger | `#call-N` |
| Ledger row | Its journal record, and the fault event on it | `?view=timeline&show=all&run=&call=N#trace` |
| Timeline step | The same call in the comparison | `#call-N` |
| Go deeper | The hypothesis behind this run | `?view=investigator&run=#h5` |
| Go deeper | Run fields, fault configuration, findings, task text | `?view=evidence&run=` |

Every state is a URL, so history and deep links work. Content streams in after first paint, so `HashFocus`
repeats the browser's scroll once the anchor exists, and opens the row it lands on. Tabs stay in view on scroll.
There is no synchronized scrolling.

## Failure states

A missing run or a refused record shows no headline and no verdict, only the failure and the case title. An
investigation with no target run shows a hollow seal.
