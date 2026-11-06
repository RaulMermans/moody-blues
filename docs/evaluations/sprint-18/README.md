# Sprint 18 evaluation: two worlds, one coordinator

**What this is.** A measurement of infrastructure. Agents are deterministic scripts and experiments are fixed developer scripts,
in real Docker sandboxes, with real worlds and the real Oracle. **No model ran.** It says nothing about any LLM, compares no agents
and shows no adaptive advantage. `NO_DEMONSTRATED_ADVANTAGE` stands. Results: [worlds.json](results/worlds.json). Reproduce with
`make worlds-demo`.

| Case | Script | Faults delivered | Validity | Claim | New records | Oracle | Wall |
|---|---|---|---|---|---|---|---|
| queue: correct | careful | 0 | control | completed | 1 | **PASS** | 1710 ms |
| queue: error, safe verify | careful | 1 | exercised | completed | 1 | **PASS** | 1361 ms |
| queue: error, retry | unsafe | 1 | exercised | completed | 2 | **VIOLATION** | 1376 ms |
| queue: success, false | unsafe | 1 | exercised | completed | 0 | **VIOLATION** | 1409 ms |
| queue: stale outlasted | careful | 2 | exercised | completed | 1 | **PASS** | 1443 ms |
| crm: correct | careful | 0 | control | completed | 1 | **PASS** | 1552 ms |
| crm: error, safe verify | careful | 1 | exercised | completed | 1 | **PASS** | 1344 ms |
| crm: error, retry | unsafe | 1 | exercised | completed | 2 | **VIOLATION** | 1396 ms |
| crm: success, false | unsafe | 1 | exercised | completed | 0 | **VIOLATION** | 1305 ms |

No verdict is written into an agent or the harness. `expected` values are compared after each run, and the Oracle derived every
verdict from persisted state.

## Metrics

| Metric | Result |
|---|---|
| Successful world initializations | 9/9 in the real sandbox, and every offline test |
| Cross-world rejection | 100% of attempts in tests: foreign tools, scopes, scenarios and fault operations. 0 reached a gateway |
| Correct Oracle classification | 9/9 |
| Evidence integrity | 9/9 verified; tampering caught in both worlds |
| Agent execution in Docker | 9/9 |
| Sandbox cleanup | 9/9, 0 containers left behind |
| Median experiment latency | 1396 ms (coordinator, sandbox steps and agent; one laptop, 4-CPU Colima VM, not a benchmark) |
| Invalid experiment detection | All cases in `tests/investigator/test_validity.py`, including the three real Sprint 17 errors |
| Regression failures | 0 |

## The Sprint 17 errors, as regression cases

The model's own text comes from the committed [Sprint 17 results](../sprint-17/results/local-eval.json). The runs are new, real runs
with reference scripts, because no model is installed.

| Real error | Now |
|---|---|
| h1 marked `supported` while its reasoning said no violation occurred | `contradicts_oracle`, effective `inconclusive` |
| `supported` citing runs where the fault never fired | `not_exercised` |
| h2 repeating h1 almost word for word | Labeled as a repeat of h1 |

These checks would have caught those errors in the record. They do not stop a model making them, and no real model has run with them.

## Real-model evaluation

`NOT_RUN`. Ollama has no models installed and its server is not running. Downloading one was out of scope, and no paid inference
was used.
