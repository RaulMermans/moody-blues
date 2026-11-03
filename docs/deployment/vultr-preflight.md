# Vultr preflight

How to take the Vultr integration from *configured* to *verified*. Every step in this
document that costs money is marked **[chargeable]**, and each one needs explicit human
approval.

## Current state (2026-11-03, Sprint 3)

| Item | Status |
|---|---|
| Adapter implemented and offline contract tests passing (incl. multi-turn tool calls) | PASS |
| `MOODY_VULTR_API_KEY` present in `.env` | yes |
| Key accepted by `POST /chat/completions` | **FAIL: HTTP 401 `Invalid API key`** → BLOCKED_BY_CREDENTIALS |
| `make vultr-models` (live catalog) | Returns 35 models, but `GET /models` is **unauthenticated**, so this proves nothing about the key |
| `MOODY_VULTR_MODEL=kimi-k2-instruct` in the catalog | **No**: choose a listed model |
| `make vultr-smoke` (basic, tool calling, tool round trip) | BLOCKED_BY_CREDENTIALS |
| `make agent-run` / `make agent-eval` | BLOCKED_BY_CREDENTIALS |
| Vultr VM deployment | Out of scope |

**Likely cause of the 401 (unconfirmed):** the configured key is 36 upper-case alphanumeric
characters, which is the format of a Vultr *account* API key (my.vultr.com → Account → API).
Serverless Inference uses its own key, shown on the Serverless Inference subscription page.
Put that key in `.env` and rerun step 6.

## Steps

1. **Redeem hackathon credits** in the Vultr console. [human; billing]
2. **Enable Serverless Inference** and create an API key. [chargeable subscription]
3. Put the key in a local `.env`. Never paste it into chat, code, issues or commits:
   ```bash
   cp .env.example .env
   # edit .env: MOODY_VULTR_API_KEY=<your key>
   ```
4. `make doctor` should show `vultr-config PASS ... NOT live-verified`.
5. **List models** [live, free]: `make vultr-models`. Confirm that `configured_model_listed`
   is `true`. If it isn't, set `MOODY_VULTR_MODEL` to a listed model. This endpoint does not
   check the key; only step 6 does.
6. **Run the smoke checks** [chargeable, about two short completions]: `make vultr-smoke`.
   - `basic_inference`: expects a reply containing "pong".
   - `tool_calling`: offers an `add_numbers(a, b)` tool with `tool_choice=required`, validates
     the arguments with Pydantic, and expects `{17, 25}`.
   - `tool_round_trip`: sends the tool result back under the original call id
     (`role=tool`) and expects the model to answer 42. This is the live check of the
     multi-turn protocol.
   - The evidence, including the requested and reported model and token usage, is written to
     `.artifacts/vultr-smoke.json`.
7. **Agent runs** [chargeable, bounded]: `make agent-run SCENARIO=normal-success
   CONFIG=baseline MODEL=<id>`, then `make agent-eval TRIALS=3 MODEL=<id>`. The defaults cap
   each run at 10 inference calls and 60k tokens, and the evaluation at 400k tokens.
   Optional: set `MOODY_VULTR_PRICE_PER_MILLION_TOKENS_USD` to get cost estimates.
8. Record the result in `docs/sprints/` and update the table above.

## Model selection

`kimi-k2-instruct` is still the code default, from Vultr's tool-calling guide
(<https://docs.vultr.com/how-to-use-tool-calling-with-vultr-serverless-inference>). It is
**not** in the live catalog as of 2026-11-03. Chat-capable candidates in the catalog include
`glm-5.3`, `glm-5.2`, `qwen3.8-27b`, `deepseek-v4.1-flash-1017`, `minimax-m3.1-flash` and
`mimo-v2.6-pro`. None has been verified for tool calling, because the key is rejected. The
default is left unchanged rather than replaced by an unverified guess; `agent-run` and
`agent-eval` refuse a model missing from the catalog before making any call.

## CI

`.github/workflows/vultr-live.yml` is a manual workflow (`workflow_dispatch`) that uses the
`vultr-live` environment and the `MOODY_VULTR_API_KEY` repository secret. Without the secret
it fails; it never passes silently. Ordinary CI never calls Vultr.

## Troubleshooting

| Category | Meaning |
|---|---|
| `provider_auth` | Bad or revoked key (401/403). Not retried. |
| `provider_model_not_found` | 404. The model ID is not in your catalog. Run `make vultr-models`. |
| `provider_rate_limited` | 429. Retried up to `MOODY_VULTR_MAX_RETRIES`. |
| `provider_timeout` / `provider_connection` | Network problem. Retried. |
| `provider_bad_request` | Request rejected. For example, the model doesn't support `tools`. |
