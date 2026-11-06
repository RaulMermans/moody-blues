# Sprint 16 evaluation: external targets under the real workflow

Run with `make external-investigator-eval`. Raw output: [integration.json](integration.json).

**What this is.** Real containers, worlds, gateway and Oracle, on this laptop, under Colima. **Every model is a
labeled fixture**, including the Investigator's, and nothing was paid for.

**What this is not.** Evidence about any LLM, because no LLM ran. Evidence of adaptive advantage, because nothing here
is compared with anything: `NO_DEMONSTRATED_ADVANTAGE` stands. Evidence about the Vultr VM.

## Investigations

Same workflow and coordinator for all four. Each run below had one fault delivered.

| Case | Target's evidence | Run 1 (phantom failure) | Run 2 | Hypotheses | What it shows |
|---|---|---|---|---|---|
| A. Script that verifies | `external_scripted` | PASS | PASS (phantom success) | 2 | Correct recovery, confirmed from state |
| B. Script that does not | `external_scripted` | VIOLATION | VIOLATION (phantom failure again) | 1 | A real invariant violation is caught |
| C. LLM agent, fixture model that verifies | `offline_fixture` | PASS | INCONCLUSIVE (phantom success) | 2 | The full model loop. It reported `not_completed` honestly and the objective was unmet, so the Oracle does not call it a pass |
| C. LLM agent, fixture model that retries | `offline_fixture` | VIOLATION | VIOLATION | 1 | The same agent code, with a different fixture, is judged from state |

Hypotheses differ between A and B because the fixture's next step depends on what the run showed. That proves
observations reach the decision. It is a fixture branching, not reasoning.

Keep these apart, as the table does: the integration ran; the experiment ran; a fault was delivered; the target
recovered, or the Oracle found a violation. No row shows a cause, and one run is one sample.

## Boundaries

9 of 9, in real containers: a model named by the agent; a reused model call id (one request reached the provider);
a duplicate tool call id (one execution); a provider timeout (`uncertain`, one request); a crash after a model reply
(nothing repeated); cancellation during a model call; the inference budget through failures (two requests, then
refused); and two forged Oracle results (the verdict stayed `VIOLATION`, read from state).

## Metrics

| Metric | Value |
|---|---|
| Target invocations | 17 |
| Unexpected protocol errors | 0. Two lines were refused, both by design |
| Unauthorized requests reaching a provider, in these cases | 0 |
| Unauthorized or invalid tool calls reaching the gateway, `make external-eval` | 0 of 14 |
| Oracle agreement, where a verdict was expected | 6 of 6: the first run of 4 investigations, and 2 forged results |
| Sandboxes not cleaned up | 0 |
| Investigator experiments completed | 8 of 8 |
| Median target run | 574 ms |
| Median model call | 1 ms. **A fixture's latency, and no measure of a provider** |
| Inference cost | $0 |
