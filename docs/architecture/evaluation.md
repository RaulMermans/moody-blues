# Registered evaluation

_Sprint 6. Covers what is implemented. Decisions: [ADR 0006](../adr/0006-registered-evaluation.md).
Method: [methodology.md](../evaluations/methodology.md)._

`backend/moody_blues/evaluation/` measures the system. It adds no orchestration: experiments still
run through the coordinator and sandbox, investigations through `InvestigationWorkflow`, and verdicts
come only from the Oracle.

| Module | Owns |
|---|---|
| `manifest.py` | The registration as data: suites, limits, budgets, fingerprints. Derives the seeded plan. Refuses a registration that is changed, uncommitted or out of step with the code |
| `trials.py` | One target run as a `TrialRecord`: world truth, eligibility and behavior, kept apart. `summarize` gives every denominator |
| `attribution.py` | `fault_delivered`, `violation_observed`, and the controlled contrast behind `causal_evidence_supports_fault` or `causality_inconclusive` |
| `adaptation.py` | Paired real seeds, blind control, what each follow-up ran, and scoring at four levels |
| `suites.py` | Runs the frozen plan: order, bounded replacement, staged extension, recovery |
| `journal.py` | Append-only, hash-chained record of a suite |
| `report.py` | Recomputes results into JSON, Markdown and CSV, and applies the registered conclusion rule |
| `audit.py` | Reclassifies existing evidence; reads only |
| `stats.py` | Exact intervals on raw counts. No significance tests |
| `commands.py` | `eval-freeze`, `eval-verify`, `eval-run`, `eval-report`, `evidence-audit` |

## Flow

```
eval-freeze -> manifest.json + trial-plan.json   (committed before any scored trial)
eval-run    -> checks commit, plan and fingerprints -> frozen plan -> .artifacts/sprint-06/<suite>
eval-report -> journals -> docs/evaluations/sprint-06/results/{results.json,results.md,trials.csv}
```

## Keeping the four things apart

| Question | Answered by | Never answered by |
|---|---|---|
| What is true of the world? | Oracle verdict | Eligibility, claims |
| May this run enter a rate? | `eligible`, read without the verdict | The verdict |
| Did the Investigator claim it? | `claim_checks` | Anything else: claims create no finding |
| Did the fault raise the chance of failure? | A registered contrast of eligible runs | One run, temporal order, `fault_attributable` |

## Trust boundaries

Unchanged. Nothing here reaches a sandbox or a prompt except through existing paths. Manifest contents
such as the known failure, rubric and thresholds stay out of every prompt
(`test_nothing_about_the_benchmark_reaches_a_prompt`). Reserved worlds have neutral ids and no
descriptions. `tests/security/test_evaluation_boundaries.py` runs the probes and a hostile program in
real containers.
