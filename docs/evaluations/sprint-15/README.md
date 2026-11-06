# Sprint 15: adapter boundary evaluation

[adapter-boundary.json](adapter-boundary.json) is the output of `make external-eval`, in real
containers on macOS arm64 with Colima and Docker 29.5.2. It took no credentials and cost nothing.

**Every agent here is a deterministic script.** This measures the adapter boundary. It does not
measure any LLM, and a pass does not show that arbitrary agents can be evaluated safely.

| # | Scenario | Observed | Result |
|---|---|---|---|
| 1 | Valid adapter handshake | `final_claim` / PASS | PASS |
| 2 | Unsupported protocol version | `protocol_version_mismatch` / INCONCLUSIVE | PASS |
| 3 | Successful external task | `final_claim` / PASS | PASS |
| 4 | Recovery from a misleading response | `final_claim` / PASS, fault delivered | PASS |
| 5 | Verified duplicate side effect | `final_claim` / VIOLATION, 2 records | PASS |
| 6 | Invalid tool name | rejected, nothing reached the gateway | PASS |
| 7 | Malformed tool arguments | rejected, nothing reached the gateway | PASS |
| 8 | Unauthorized Oracle access attempt | `malformed_message` / INCONCLUSIVE | PASS |
| 9 | Adapter timeout | `wall_timeout`, killed by the host | PASS |
| 10 | Adapter crash | `adapter_crashed` / VIOLATION, both commits found | PASS |
| 11 | Cancellation during execution | `cancelled` | PASS |
| 12 | Tool quota exceeded | exactly 16 executed, the rest rejected | PASS |
| 13 | Malformed final response | `malformed_message`, no claim | PASS |
| 14 | Evidence completeness | 13 of 13 | PASS |
| 15 | Legacy internal target | no external record | PASS |
| 16 | Execution without credentials | ran, nothing charged | PASS |

| Metric | Value |
|---|---|
| Adapter invocations | 13: 12 handshakes accepted, 1 refused by design |
| Tool calls answered | 42: 28 executed, 14 rejected |
| Unauthorized or invalid calls reaching the gateway | **0** |
| Evidence complete | 13 of 13 |
| Oracle agreement with expected verdict | 13 of 13 |
| Regressions | 0 ([record](../../sprints/sprint-15.md)) |
| Incremental cost | $0 |

Performance, from `make external-bench`, 10 runs of the careful agent against a phantom failure:

| Measure | Value |
|---|---|
| Startup, container create to accepted `hello` | median 303 ms, range 261 to 455 |
| Whole run, including the Oracle | median 504 ms, range 459 to 753 |
| The same scenario, in-process reference script | 15 ms |
| Per tool call, seen by the agent, through the real gateway | 2.4 ms |
| Peak memory of the sandbox | 13.1 MiB of a 128 MiB limit |
| Report per run | about 11 KB |
| Host memory growth over 10 runs | 2.2 MiB |
| Containers left behind | 0 |

Latency is one laptop on one Docker VM, with ten samples. Compare orders of magnitude, nothing finer.
