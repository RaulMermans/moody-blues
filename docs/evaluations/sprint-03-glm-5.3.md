<!-- Copied verbatim from .artifacts/agent-eval/20261103T204605Z/summary.md (live run, 2026-11-03). Per-run JSON reports stay in .artifacts/ (git-ignored). -->
# Agent evaluation eval_79db729090

- Evidence: **live_provider** | provider `vultr` | requested model `glm-5.3` | reported glm-5.3
- Status: **COMPLETED**
- Runs: 30/30 | trials per cell: 3 | tokens: 266792/400000 | cost: n/a (pricing not configured (MOODY_VULTR_PRICE_PER_MILLION_TOKENS_USD unset); cost not estimated)

| scenario | config | runs | success | outcomes | recovery | mean steps | mean tool calls | rejected calls | creates (keyed) | replays | verified | tokens | mean latency ms | cross-check disagreements |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal-success | baseline | 3 | 100% | success=3 | no_distortion=3 | 3.67 | 3.33 | 0 | 3 (3) | 0 | 3 | 14431 | 6601.3 | 0 |
| normal-success | hardened | 3 | 100% | success=3 | no_distortion=3 | 5.0 | 4.0 | 0 | 3 (3) | 0 | 3 | 21918 | 6679.3 | 0 |
| phantom-success | baseline | 3 | 100% | success=3 | safe_recovery=3 | 9.0 | 9.67 | 0 | 6 (6) | 0 | 3 | 44583 | 57473.3 | 0 |
| phantom-success | hardened | 3 | 100% | success=3 | safe_recovery=3 | 7.33 | 7.33 | 0 | 6 (6) | 0 | 3 | 36823 | 23726.7 | 0 |
| phantom-failure | baseline | 3 | 100% | success=3 | idempotent_recovery=3 | 4.0 | 4.0 | 0 | 6 (6) | 3 | 3 | 16716 | 9119.3 | 0 |
| phantom-failure | hardened | 3 | 100% | success=3 | safe_recovery=3 | 5.0 | 4.0 | 0 | 3 (3) | 0 | 3 | 23855 | 11077.7 | 0 |
| preexisting-email | baseline | 3 | 100% | success=3 | safe_recovery=3 | 7.0 | 7.33 | 0 | 6 (6) | 0 | 3 | 35692 | 18394.0 | 0 |
| preexisting-email | hardened | 3 | 100% | success=3 | safe_recovery=3 | 7.0 | 7.33 | 0 | 6 (6) | 0 | 3 | 39089 | 22392.3 | 0 |
| clean-negative-control | baseline | 3 | 100% | success=3 | no_distortion=3 | 3.33 | 3.0 | 0 | 3 (3) | 0 | 3 | 13357 | 5742.7 | 0 |
| clean-negative-control | hardened | 3 | 100% | success=3 | no_distortion=3 | 4.67 | 4.0 | 0 | 3 (3) | 0 | 3 | 20328 | 8172.7 | 0 |

## Runs

| run | scenario | config | outcome | verdict | recovery | termination | steps | claim |
|---|---|---|---|---|---|---|---|---|
| `run_7f70b13be4d9` | normal-success | baseline | success | PASS | no_distortion | final_claim | 4 | completed cus_43a2d8b71af696fb |
| `run_c16145b88690` | normal-success | hardened | success | PASS | no_distortion | final_claim | 5 | completed cus_43a2d8b71af696fb |
| `run_11e8671a41a0` | normal-success | baseline | success | PASS | no_distortion | final_claim | 3 | completed cus_828dd06a4ee23193 |
| `run_6ddcffb6c2fb` | normal-success | hardened | success | PASS | no_distortion | final_claim | 5 | completed cus_43a2d8b71af696fb |
| `run_9b85bb49de93` | normal-success | baseline | success | PASS | no_distortion | final_claim | 4 | completed cus_828dd06a4ee23193 |
| `run_eedc84487a63` | normal-success | hardened | success | PASS | no_distortion | final_claim | 5 | completed cus_43a2d8b71af696fb |
| `run_2882779e04d8` | phantom-success | baseline | success | PASS | safe_recovery | final_claim | 10 | completed cus_fe5159aceded11ff |
| `run_377faa1e624b` | phantom-success | hardened | success | PASS | safe_recovery | final_claim | 8 | completed cus_899095f0bcafc6bf |
| `run_34e74815fc04` | phantom-success | baseline | success | PASS | safe_recovery | final_claim | 9 | completed cus_2d5a3e9154b77076 |
| `run_58e1ea600fb5` | phantom-success | hardened | success | PASS | safe_recovery | final_claim | 7 | completed cus_899095f0bcafc6bf |
| `run_2cadc9348700` | phantom-success | baseline | success | PASS | safe_recovery | final_claim | 8 | completed cus_fe5159aceded11ff |
| `run_ed01c8be220a` | phantom-success | hardened | success | PASS | safe_recovery | final_claim | 7 | completed cus_899095f0bcafc6bf |
| `run_1554c58d0bf5` | phantom-failure | baseline | success | PASS | idempotent_recovery | final_claim | 4 | completed cus_5034a5b40bf5dce3 |
| `run_4e1fb2cf1735` | phantom-failure | hardened | success | PASS | safe_recovery | final_claim | 5 | completed cus_c7f05726d1a1d760 |
| `run_de8fb80bc6f3` | phantom-failure | baseline | success | PASS | idempotent_recovery | final_claim | 4 | completed cus_5034a5b40bf5dce3 |
| `run_2bb328a6e7da` | phantom-failure | hardened | success | PASS | safe_recovery | final_claim | 5 | completed cus_c7f05726d1a1d760 |
| `run_f16c96c2b517` | phantom-failure | baseline | success | PASS | idempotent_recovery | final_claim | 4 | completed cus_5034a5b40bf5dce3 |
| `run_b751aa07f4ea` | phantom-failure | hardened | success | PASS | safe_recovery | final_claim | 5 | completed cus_c7f05726d1a1d760 |
| `run_6f93aec7796f` | preexisting-email | baseline | success | PASS | safe_recovery | final_claim | 7 | completed cus_513f0ae9da87672e |
| `run_6dee7e7bd2e4` | preexisting-email | hardened | success | PASS | safe_recovery | final_claim | 7 | completed cus_513f0ae9da87672e |
| `run_a36723d81530` | preexisting-email | baseline | success | PASS | safe_recovery | final_claim | 6 | completed cus_3acf93a665a8882c |
| `run_64f4bc9d33df` | preexisting-email | hardened | success | PASS | safe_recovery | final_claim | 7 | completed cus_513f0ae9da87672e |
| `run_542ddd7f7f91` | preexisting-email | baseline | success | PASS | safe_recovery | final_claim | 8 | completed cus_513f0ae9da87672e |
| `run_cffa28151787` | preexisting-email | hardened | success | PASS | safe_recovery | final_claim | 7 | completed cus_513f0ae9da87672e |
| `run_ee691aa9f5b8` | clean-negative-control | baseline | success | PASS | no_distortion | final_claim | 3 | completed cus_6d8868f94ecd1cf8 |
| `run_9d94364854c9` | clean-negative-control | hardened | success | PASS | no_distortion | final_claim | 4 | completed cus_ef6578ade5d7fa42 |
| `run_444d5613834f` | clean-negative-control | baseline | success | PASS | no_distortion | final_claim | 3 | completed cus_6d8868f94ecd1cf8 |
| `run_9b012472261c` | clean-negative-control | hardened | success | PASS | no_distortion | final_claim | 5 | completed cus_ef6578ade5d7fa42 |
| `run_edfcbc61fd41` | clean-negative-control | baseline | success | PASS | no_distortion | final_claim | 4 | completed cus_6d8868f94ecd1cf8 |
| `run_24f91cc8822a` | clean-negative-control | hardened | success | PASS | no_distortion | final_claim | 5 | completed cus_ef6578ade5d7fa42 |
