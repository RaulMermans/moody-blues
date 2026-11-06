# Product experience architecture

The journey is **Choose a test → Run the test → See what happened → Explore the evidence**. The decision and its
reasons: [ADR 0011](../adr/0011-result-first-information-architecture.md).

## Map

| Place | Route | Answers |
|---|---|---|
| Landing | `/` | What is this, why does it matter, what can I try now |
| Choose a test | `/operator` | What can run, on what, at what cost. Public catalog; running needs a token |
| Result | `?view=overview`, or no `view` | What was tested, what happened, the verdict, where next, step by step |
| What happened | `?view=reality` | What the target saw against what was true |
| Investigation | `?view=investigator` | Hypotheses, experiments and decisions |
| Evidence | `?view=evidence`, `?view=timeline` | The recorded fields, and the journal in order |

The visible label "Run a test" points at the `/operator` route. Visible words changed; addresses did not.

## Levels

| Level | Holds | Default |
|---|---|---|
| 1 Result | Task, outcome sentence, supporting sentence, verdict and its meaning, one next action | In view |
| 2 Story | Milestones, primary comparison, agent's message, all qualifiers | In view |
| 3 Evidence | Tool calls, JSON, records, discrepancies, findings, hypotheses, hashes, provenance | Folded or one tab away |

## Where the words come from

| Module | Writes |
|---|---|
| `design/model.ts` | `targetNoun`: agent, script or fixture, from `target_evidence` |
| `design/outcome.ts` | Outcome headline and support, task with its source, verdict meaning, relation of report to state |
| `design/sequence.ts` | Milestones. A step with no record is omitted |
| `lib/test-catalog.ts` | Reader's words for each mission, and a rehearsal's task. Held to the server's catalog by a browser test |
| `lib/labels.ts` | `inRehearsal`: shared words as they read when a fixture and a script stood in |

## The story

| Run | Steps |
|---|---|
| Script run | Operation attempted, misleading response, actual state, response, Oracle outcome |
| Model-led run | Hypothesis, misleading response, actual state, response, Oracle outcome, Investigator decision |
| No fault delivered | Fault and actual-state steps are left out |
| No tool calls | Only response and Oracle outcome |

"Recovery observed" appears only where `finding_class` is `correct_recovery`. Counts come from the delivery record, and
no step gives a reason.

## States

| State | Behaviour | Verified by |
|---|---|---|
| PASS, no violation | "handled correctly" only with a recorded `correct_recovery`; a one-sample note follows | Recorded, rules |
| Oracle VIOLATION | Headline from findings; records and causal line stay visible | Recorded |
| INCONCLUSIVE | "could not decide"; nothing reads as success | Recorded |
| PASS in an inconclusive investigation | Scope band leads the screen | Recorded |
| Missing claim | Never success, on any verdict | Recorded, rules |
| Missing task text | Sourced from the catalog and labeled, or "not in this record" | Rules, rehearsal |
| No model participation | Script wording at every level, and a "no AI model ran" note | Real rehearsal |
| Refused experiment | Counted on Result, detailed in Investigation | Recorded |
| Sandbox failure or no target run | "No target run took place", hollow seal, no verdict | Code path only: no committed bundle reaches it |
| Disabled live execution | Card says why; its button is disabled | Real backend |
| Unavailable investigation, unknown id | Failure panel | Real backend |
| Unknown run id | Named as foreign; the primary run stays on Result; What happened refuses | Real backend |

## Not built

Connecting an outside agent is a proposal for a later sprint. No control, route or copy offers it.
