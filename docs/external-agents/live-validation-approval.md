# Live validation: approval request

**Status: not approved, not run.** `EXTERNAL_LLM_LIVE_VALIDATION = NOT_RUN`.

Nothing below runs until the owner approves it in writing, with the values filled in. After approval, run at most
what was approved.

## Proposed scope

| Item | Option 1, recommended | Option 2 |
|---|---|---|
| What it proves | A real LLM drives an external agent through the boundary | Also: a real Investigator chooses experiments against an external target |
| Provider and model | Vultr Inference, `glm-5.3` | Same, for both |
| Environment | This laptop, Colima. Not the VM: it has no key, and the public site is not touched | Same |
| World | `normal-success`, synthetic and disposable, with phantom faults | Same |
| Tools | `get_customer`, `search_customers`, `create_customer` | Same |
| Experiments | 2 | 2 |
| Expected model calls | 6 to 10 | 8 to 13 |
| **Hard maximum calls** | **16** (8 per run) | **19** (plus 3 for the Investigator) |
| Tokens | 30,000 per run, 4,096 out per call, 48,000-byte prompts | Investigator: 8,192 out per call |
| Reserved worst case, at assumed ceiling prices | $0.28 per run | $0.14 per Investigator call |
| **Spend limit asked for** | **$0.60** | **$1.00** |
| Maximum wall clock | 95 s per run, 7 minutes in all | Same |

Expected real spend is a few cents, but that is an estimate. These figures use assumed ceiling prices. They are not
provider prices, and the ledger is not a provider limit: check the Vultr console afterwards.

## Decisions needed first

1. **The ledger limit.** The local ledger shows $6.50 settled against the $5.00 default, so every live command
   is refused as shipped. Set `MOODY_LIVE_SPEND_LIMIT_USD` for this one process, to settled plus the approved limit.
2. **Which ledger.** The VM's copy is canonical, and a laptop run splits it. Accept that and record it, or set
   `MOODY_LIVE_LEDGER_FLOOR_USD` to the VM's figure.
3. **The key.** Rotation of `MOODY_VULTR_API_KEY` is unconfirmed. The key stays on the host, and never enters a sandbox.

## How it would run

```bash
export MOODY_ARTIFACTS_DIR=$(mktemp -d)
export MOODY_LIVE_SPEND_LIMIT_USD=<settled + limit>
make vultr-models                     # free: the model must be in the catalog
make external-investigate TARGET=external_llm MANIFEST=examples/external-agent/llm.agent.toml \
  LIVE=1 CONFIRM=1 SPEND=0.60
```

Option 2 adds `LIVE_INVESTIGATOR=1` and `SPEND=1.00`. Refused unless every one of these is present.

## Outcomes that count

PASS, VIOLATION, INCONCLUSIVE and a bounded failure are all acceptable, if verified. No violation is promised. The
agent has only met a fixture, so expect to fix something, such as the reply format.

## Cleanup and rollback

The world and evidence live under the scratch directory. Nothing is deployed, and nothing public changes. Unset
the limit afterwards. If the run is interrupted, nothing is repeated: `make experiment-recover` closes it as
`uncertain`, and the reservation stays on the ledger. Copy the evidence into the repository only by a deliberate
step, labeled live.
