# Live budget policy

**The spend ledger is an application-side estimate. It is not a provider billing limit.** Vultr
enforces nothing described here. Check real spending in the Vultr console.

## Rules

- Live testing is off by default. `make check` and all test targets make no provider calls.
- Billable batches need explicit opt-in: `make agent-eval CONFIRM=1`,
  `make experiment-live CONFIRM=1`.
- One run at a time. Sprint 4 experiments allow one target run by default.
- Default live run caps: 10 steps, 16 tool calls, 20,000 tokens, 1,024 completion tokens per
  call, 120 s.
- Sprint limit: **$5** (`MOODY_LIVE_SPEND_LIMIT_USD`). Every chargeable command reserves its
  worst case first and is refused (`BLOCKED_BY_BUDGET`, exit 3) if that could cross the limit.

## Investigations (Sprint 5)

- Model calls and target runs share one scope in the same ledger, capped per investigation at
  `MOODY_INVESTIGATOR_MAX_SPEND_USD` ($0.75). Each must also fit the sprint limit. No second ledger
  exists, and a restart cannot reset a scope.
- Every model call reserves its worst case per attempt: prompt at two characters per token, plus
  8,192 completion tokens, all at the output price. A failed or usage-less call keeps that amount,
  so a dropped call costs about $0.15 on the books.
- Live investigation target caps: 10 steps, 16 tool calls, 30,000 tokens, 4,096 completion tokens
  per call, 180 s. That is $0.28 reserved per run.
- A corrupt ledger refuses all new work. Investigations run one at a time, and live commands run the
  free preflight first.
- **SDK retries** (1 by default) can repeat a request. Model calls reserve for them; a target run's
  reservation does not multiply, because it is far above real usage, but a retried request that was
  billed without reporting usage would not appear here.

## Registered evaluations (Sprint 6)

- The sprint's $5 sits on the same ledger: `eval-run` sets the limit to what was settled at registration
  ($2.44414) plus $5, or $7.44414. Nothing is reset. Other commands keep their own limit, so they now
  refuse until a sprint raises `MOODY_LIVE_SPEND_LIMIT_USD`.
- Suites have their own caps through the existing scopes. Caps are never raised during a run.
- Target limits come from the manifest: 14 steps, 24 tool calls, 40,000 tokens, 8,192 per step, 240 s.
  That reserves $0.39 per run.
- A target run with a failed provider request keeps its full reservation, because the request may be
  billed and reports no usage. The ledger is append-only, so a past under-booking is corrected by a
  labeled `adjustment` entry.

## Application-started runs (Sprint 7)

- Reading investigations, frontend builds and every test suite make no provider call.
- A chargeable mission needs all of: the operator token, `MOODY_LIVE_RUNS_ENABLED=true`, provider
  credentials, and a ledger whose remaining amount covers `MOODY_INVESTIGATOR_MAX_SPEND_USD` ($0.75).
  Any miss is refused before a job exists.
- One job at a time, refused rather than queued. Each model call and target run still reserves its worst
  case first, on the same shared ledger, under the same per-investigation scope.
- **The default limit is below what is already settled, so chargeable missions are refused as shipped:**
  $5.00 against $6.50 on the ledger. The application cannot change this. To allow one verification run,
  the owner sets `MOODY_LIVE_SPEND_LIMIT_USD` deliberately, for example to 7.35 for about one
  investigation, for that server process only. Sprint 7's run was done this way, at 7.25.

## Hosted spending (Sprint 8)

- The VM runs with `MOODY_LIVE_RUNS_ENABLED=false`, no provider key, and a $5 limit, so spending is refused
  three ways as deployed. `live-switch.sh` is the only thing that changes this.
- `MOODY_LIVE_LEDGER_FLOOR_USD` is set from the migrated ledger. Settled spend below it means the ledger was
  lost or replaced, and every reservation refuses. A fresh VM cannot restart from zero.
- The ledger moves once. After that the VM's copy is canonical, so live calls from a laptop would split it.
- A limit of $7.30 on $6.50 settled admits exactly one investigation: about $0.80 is left against the $0.75
  required, and a run of about $0.10 leaves too little for a second.

## How the estimate works

| Situation | What is booked |
|---|---|
| Before a run | Worst case: `2 x max_total_tokens + max_completion_tokens`, all at the output price. The token limit is checked between calls, so the last call can overshoot it. |
| Run finished, usage complete | Measured prompt and completion tokens at ceiling prices |
| Usage incomplete | The full reservation |
| Process died | The reservation stays open and counts in full |
| Ledger unreadable | All spending refused |

## Pricing uncertainty

The live catalog has no prices, and no official per-model price for `glm-5.3` was found. So the
ledger uses **assumed ceilings**: $1.40 per million input tokens and $4.40 per million output
tokens. These are the highest published figures found for this model family, not quotes:

| Source | Input / output per 1M | Status |
|---|---|---|
| Vultr docs, general serverless rate (March 2026) | $0.55 / $2.75 | Official, but older than `glm-5.3` |
| TypingMind estimator, `glm-5.3` on Vultr | $0.75 / $3.00 | Third party, unverified |
| Z.ai first-party rate | $1.40 / $4.40 | A different provider; used as the ceiling |

**Raise the ceilings before using a more expensive model.** They are not per-model.

## What it cannot see

- Requests that time out may be billed without reporting usage, and SDK retries can repeat them.
- Spending from other tools or keys.
- Subscription or minimum fees.
- Sprint 3 usage, which predates the ledger and is listed below by hand.

## Cumulative project record

Promotional credit: **$200**. Each sprint sets its own limit, and spending past a sprint limit
needs a human decision. Estimates at ceiling prices:

| Period | Tokens | Estimate |
|---|---|---|
| Sprint 3 evaluation (30 runs) | 266,792 | $0.48 |
| Sprint 3 single run and smoke checks | about 8,000 | $0.02 |
| Sprint 4 (ledger: `make live-budget`) | 61,526 | $0.11 |
| Sprint 5 (ledger: `make live-budget`) | 1,043,673 | $2.33 |
| Sprint 6 (ledger: `make live-budget`) | 1,903,319 | $3.96 |
| Sprint 7 (one verification run) | 53,744 | $0.10 |
| **Total** | **about 3.33 million** | **about $7.00** |

The ledger itself shows $6.50, because Sprint 3's $0.50 predates it.

Update this table when a sprint closes.
