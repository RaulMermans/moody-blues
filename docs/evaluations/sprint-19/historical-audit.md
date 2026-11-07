# What earlier evaluations can and cannot say about adaptive advantage

Read from committed results, with nothing changed. Sprint 6's conclusion, `NO_DEMONSTRATED_ADVANTAGE`, stands, and nothing from these
studies is combined with Sprint 19.

| Study | Model | Strategies | Units | Runs (eligible) | Violations | What it can say |
|---|---|---|---|---|---|---|
| Sprint 5 ([report](../sprint-05-investigator.md)) | `glm-5.3`, both roles | Fixed, one-shot, adaptive | 17 investigations, 36 proposals, 25 executed | 52 live target runs (47 complete after reclassification; 4 impaired by our limits, 1 by infrastructure) | 7 world-state violations, 5 eligible, 2 impaired | One intermittent failure was found. The strategies never tested the same condition, so no comparison |
| Sprint 6 ([report](../sprint-06/report.md)) | `glm-5.3`, both roles | Fixed, non-adaptive LLM, adaptive | 9 investigations, 3 per strategy, on used-up worlds | 53 (52) in strategies; 119 (116) live runs overall | Discoveries: fixed 2 of 3, adaptive 1 of 3, non-adaptive 0 of 3 | Registered rule: `NO_DEMONSTRATED_ADVANTAGE`. Nine investigations cannot show superiority either way |
| Sprint 6 adaptation | `glm-5.3`, targets are scripts | Paired answers | 3 reserved cases, 56 answers | 56 (56) | n/a | Level 1 pass; levels 3 and 4 failed. The model responds to outcomes, but not measurably beyond a blind control |
| Sprint 17 ([report](../sprint-17/README.md)) | `qwen3:4b-instruct` | Adaptive only | 2 investigations | 10 target runs | 0 | Integration only. Compares nothing. It found three reasoning defects |
| Sprint 18 ([report](../sprint-18/README.md)) | None; fixture | None | 4 cases per world | Scripts | 2 by design | World correctness. Says nothing about models |

## Why this does not show adaptive advantage

- **Tiny unit counts.** The only registered comparison has three investigations per strategy, with a lead of −1 for adaptive.
- **Coverage was not equal in Sprint 5.** The strategies did not share a condition space, which Sprint 6 corrected.
- **Fixed's grid had a known bias.** It was written after the failure was known.
- **Worlds were used up.** `w-e*` results are regression evidence.
- **The transition metric could not separate strategies.** Any schedule scores well on it, as the Sprint 6 report says.
- **Repeated answers are not samples.** That study reports them as repetitions.
- **Target stochasticity and strategy are confounded.** With a model as target, one run is one draw, so a condition can look quiet by chance.
- **Invalid hypotheses were not separated then.** A fault that never fired could look like a test; Sprint 17 caught one, and Sprint 18's
  checks came later. Sprint 6's undelivered-fault counts are therefore not comparable with Sprint 19's.

## What a working Investigator is not

Sprints 16 to 18 show the workflow runs, with a real model, in real containers. That is an integration result. A completed investigation
says nothing about discovering more than a simpler strategy would.

## Why Sprint 19 is a separate study

Different model, worlds, action space and target type. Combining them would be meaningless, so no historical trial enters the benchmark.
