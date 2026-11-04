# Vultr preflight

How to take the Vultr integration from *configured* to *verified*. Every step in this
document that costs money is marked **[chargeable]**, and each one needs explicit human
approval.

Spending rules: [live-budget.md](live-budget.md).

## Current state (2026-11-03, Sprint 3; re-verified in Sprint 4)

| Item | Status |
|---|---|
| Adapter implemented and offline contract tests passing (incl. multi-turn tool calls) | PASS |
| `MOODY_VULTR_API_KEY` present in `.env` | yes |
| Key accepted by `POST /chat/completions` | **PASS** after the key was replaced (2026-11-03). The earlier key got HTTP 401. |
| `make vultr-models` (live catalog) | Returns 35 models, but `GET /models` is **unauthenticated**, so this proves nothing about the key |
| `MOODY_VULTR_MODEL=kimi-k2-instruct` in the catalog | **No**: choose a listed model |
| `make vultr-smoke` on `glm-5.3` (basic, tool calling, tool round trip) | **PASS** ×3. Reported model `glm-5.3`; latency 0.6–1.1 s; 69 / 249 / 258 tokens. |
| `make agent-run` / `make agent-eval` on `glm-5.3` | **PASS**: 1 + 30 live runs, all Oracle-verified successes, 266,792 eval tokens |
| Vultr VM deployment | Out of scope |

The 401 was resolved by replacing the key in `.env`. The diagnosis guide below is kept
for future 401s.

`glm-5.3` is a **reasoning model**: it spends completion tokens on hidden reasoning before
any text. With `max_tokens=16`, `basic_inference` came back empty (`finish_reason: length`).
The check now allows 256 tokens and still requires "pong".

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
`mimo-v2.6-pro`. `glm-5.3` is verified live for single tool calls and the multi-turn round trip; the others are unverified. The
default is left unchanged rather than replaced by an unverified guess; `agent-run` and
`agent-eval` refuse a model missing from the catalog before making any call.

## CI

`.github/workflows/vultr-live.yml` is a manual workflow (`workflow_dispatch`) that uses the
`vultr-live` environment and the `MOODY_VULTR_API_KEY` repository secret. Without the secret
it fails; it never passes silently. Ordinary CI never calls Vultr.

## Diagnosing a 401 `Invalid API key`

### How MOODY BLUES sends the key

These details match Vultr's documentation (see Sources below):

| | Value |
|---|---|
| Base URL | `https://api.vultrinference.com/v1` (`MOODY_VULTR_BASE_URL`) |
| Endpoint | `POST /chat/completions` |
| Header | `Authorization: Bearer <MOODY_VULTR_API_KEY>` (sent by the OpenAI SDK) |
| Key source | `MOODY_VULTR_API_KEY` from the shell environment, which takes precedence, or from `.env` |

`GET /v1/models` answers 200 even with no key, so `make vultr-models` cannot tell a good key
from a bad one (KI-16). Only a completion call checks the key.

### Already ruled out (2026-11-03)

- The URL, path and header format match Vultr's docs.
- No shell variable overrides `.env`, and `.env` holds exactly one `MOODY_VULTR_API_KEY=` line.
- The value has no surrounding quotes, spaces or line-ending characters (36 alphanumerics).
- The failure does not depend on the model: `glm-5.3`, `qwen3.8-27b` and
  `deepseek-v4.1-flash-1017` all return the same 401.

### What is still possible

Vultr has **two kinds of key**, and both are long upper-case strings:

| Key | Where it comes from | Works against |
|---|---|---|
| Account API key | my.vultr.com → *Account* → *API* | `api.vultr.com/v2/...` (the platform API) |
| Serverless Inference key | my.vultr.com → *Products* → *Serverless Inference* → your subscription → API key | `api.vultrinference.com/v1/...` |

Other causes to check: the inference subscription is not active yet, was paused or expired;
the inference key was regenerated after you copied it; or the key belongs to a different
subscription or account.

### Check it yourself, without sharing the key

Run these in your own terminal. Neither prints the key. A 401 is not billed, and
`max_tokens: 1` keeps any successful call to a fraction of a cent.

```bash
# 1. Does the inference endpoint accept the key? Expect HTTP 200; 401 means it is rejected.
export MOODY_VULTR_API_KEY="$(grep '^MOODY_VULTR_API_KEY=' .env | cut -d= -f2-)"
curl -s -o /dev/null -w "inference: HTTP %{http_code}\n" \
  https://api.vultrinference.com/v1/chat/completions \
  -H "Authorization: Bearer $MOODY_VULTR_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"glm-5.3","messages":[{"role":"user","content":"hi"}],"max_tokens":1}'

# 2. Is it an account key instead? Expect 200 for an account key, 401 for an inference key.
curl -s -o /dev/null -w "account API: HTTP %{http_code}\n" \
  https://api.vultr.com/v2/account -H "Authorization: Bearer $MOODY_VULTR_API_KEY"
```

| Result of 1 | Result of 2 | Meaning | Next step |
|---|---|---|---|
| 200 | any | The key works; the earlier failure was transient or environment-specific | `make vultr-smoke` |
| 401 | 200 | It is an account key | Copy the key from the Serverless Inference subscription page into `.env` |
| 401 | 401 | It is neither a valid account key nor an accepted inference key | In the console, check that the subscription is active, regenerate its key, and paste it in again |

After any change, run `MOODY_VULTR_MODEL=glm-5.3 make vultr-smoke`. All three checks
should report `PASS`.

Sources: [Vultr tool-calling guide](https://docs.vultr.com/how-to-use-tool-calling-with-vultr-serverless-inference),
[Vultr Serverless Inference in Node.js](https://docs.vultr.com/how-to-use-vultr-serverless-inference-in-nodejs).

## Troubleshooting

| Category | Meaning |
|---|---|
| `provider_auth` | Bad or revoked key (401/403). Not retried. |
| `provider_model_not_found` | 404. The model ID is not in your catalog. Run `make vultr-models`. |
| `provider_rate_limited` | 429. Retried up to `MOODY_VULTR_MAX_RETRIES`. |
| `provider_timeout` / `provider_connection` | Network problem. Retried. |
| `provider_bad_request` | Request rejected. For example, the model doesn't support `tools`. |
