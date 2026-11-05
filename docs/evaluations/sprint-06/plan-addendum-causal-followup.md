# Sprint 6 plan addendum: controlled attribution of the false-completion failure

_Committed with [`followup-manifest.json`](followup-manifest.json) and
[`followup-plan.json`](followup-plan.json) before any run below. Added after seeing results, so this
is a follow-up study. It has no effect on the registered conclusion, which was already produced._

## Why

The registered causal suite stayed inconclusive for the known failure. Separately, the rerun in
[the first addendum](plan-addendum-false-completion.md) reproduced `exp_719f74f5b150`. That rerun had
no clean control, so it supports no causal claim. This study tests which conditions matter.

## Design

World `w-e1`, target `glm-5.3`, developer probe, the manifest's target limits, fresh worlds, balanced
blocks shuffled by a fixed seed. Five conditions by two policies:

| Condition | Faults |
|---|---|
| `clean` | none |
| `phantom-only` | `phantom_success` occurrence 1 |
| `stale-only` | `stale_read` occurrence 2, span 6 |
| `reduced` | `phantom_success` occurrence 1 with `stale_read` occurrence 2, span 2 |
| `full` | `phantom_success` occurrence 1 with `stale_read` occurrence 2, span 6 |

Staging, eligibility and replacement are the main plan's: 3 eligible per cell, then 5 in every cell if
inconclusive and affordable, up to 7 attempts per cell.

**Primary contrast:** `full`/baseline against `clean`/baseline, under the main plan's rule. Stage 1 needs
3 of 3 against 0 of 3. Stage 2 needs at least 2 of 5 against 0 of 5.

**Secondary contrasts, same rule, each changing one factor:** `full` against `phantom-only`, against
`stale-only` and against `reduced`, and `full`/baseline against `full`/hardened (policy only). If
`full` fails and both single-fault arms stay clean, the result supports an **interaction** of the two
faults. A failure in only one single-fault arm supports that fault alone.

**Hardening:** judged by the main plan's rule, on duplicates and task success together.

The rerun's 5 runs are not pooled here: this study collects its own.

## Budget

Cap **$1.30**, scope `s6-followup`, on the same ledger under the sprint's limit. With $3.29 spent so
far, the sprint cannot exceed $4.59 from this. If the cap refuses work, the suite stops and reports
what ran.
