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
| **Total** | **about 336,000** | **about $0.61** |

Update this table when a sprint closes.
