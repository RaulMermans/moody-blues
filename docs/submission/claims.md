# Where each claim comes from

Every factual statement in the deck, video and copy traces to one of these.

| Claim | Source |
|---|---|
| Agent claimed `completed`; 2 records committed, 1 required; `VIOLATION` | `evidence/recorded/inv_d0bc87de6010.json`, run `run_cc34d7a6e314` |
| Hypotheses h1-h4 refuted, h5 supported; five model-generated experiments | Same bundle: `hypotheses`, `proposals` |
| The agent's message names both records | Same bundle: run `agent.disclosure` |
| 4 of 4 eligible reruns reproduced; 1 impaired not counted | Same bundle: `case_study` |
| 5 recorded investigations: 2 violations, 2 none, 1 inconclusive | `evidence/recorded/`, each `summary` |
| `NO_DEMONSTRATED_ADVANTAGE`; fixed 2/3, adaptive 1/3, non-adaptive 0/3 | `evidence/recorded/manifest.json`, `docs/evaluations/sprint-06/report.md` |
| 8 of 8 containment attempts blocked on the Vultr VM | `evidence/containment/vultr-report.json` |
| Hosted run: 3 experiments, 3 target runs, 7 faults, all PASS, no violation | `evidence/live/inv_cbd07a262444.json` |
| Recorded runs predate hosting | Bundle start times; `docs/sprints/sprint-08.md` |

## Do not claim

- That adaptive investigation beats fixed testing, or finds more bugs in general.
- That a hypothesis was caused by an earlier observation. The evidence shows it was cited, and the product says so.
- That the agent concealed anything in the signature case.
- That the sandbox is a guarantee, or that the hosted run found a failure. It found none.
- Any market size, customer, revenue or adoption figure. None has been researched.
