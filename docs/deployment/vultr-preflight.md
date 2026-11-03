# Vultr preflight

How to take the Vultr integration from *configured* to *verified*. Every step in this
document that costs money is marked **[chargeable]**, and each one needs explicit human
approval.

## Current state (2026-11-03)

| Item | Status |
|---|---|
| Adapter implemented and offline contract tests passing | PASS |
| Vultr account credits redeemed | NOT_RUN (needs a human) |
| Inference subscription / API key | BLOCKED_BY_CREDENTIALS |
| `make vultr-models` (live catalog) | BLOCKED_BY_CREDENTIALS |
| `make vultr-smoke`: basic inference | BLOCKED_BY_CREDENTIALS |
| `make vultr-smoke`: tool calling | BLOCKED_BY_CREDENTIALS |
| Vultr VM deployment | Out of scope for Sprint 1 |

## Steps

1. **Redeem hackathon credits** in the Vultr console. [human; billing]
2. **Enable Serverless Inference** and create an API key. [chargeable subscription]
3. Put the key in a local `.env`. Never paste it into chat, code, issues or commits:
   ```bash
   cp .env.example .env
   # edit .env: MOODY_VULTR_API_KEY=<your key>
   ```
4. `make doctor` should show `vultr-config PASS ... NOT live-verified`.
5. **List models** [live]: `make vultr-models`. Confirm that `configured_model_listed` is
   `true`. If it isn't, set `MOODY_VULTR_MODEL` to a listed model.
6. **Run the smoke checks** [chargeable, about two short completions]: `make vultr-smoke`.
   - `basic_inference`: expects a reply containing "pong".
   - `tool_calling`: offers an `add_numbers(a, b)` tool with `tool_choice=required`, validates
     the arguments with Pydantic, and expects `{17, 25}`.
   - The evidence, including the requested and reported model and token usage, is written to
     `.artifacts/vultr-smoke.json`.
7. Record the result in `docs/sprints/` and update the table above.

## Model selection

`kimi-k2-instruct` is the default, because Vultr's tool-calling guide documents it as the
tool-calling-capable model
(<https://docs.vultr.com/how-to-use-tool-calling-with-vultr-serverless-inference>). The live
catalog is **unverified** until step 5 has been run.

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
