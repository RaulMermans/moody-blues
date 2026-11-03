# ADR 0003: Target Agent, tool-calling protocol and fault effects

- **Status:** accepted (Sprint 3, 2026-11-03)
- **Context:** Sprint 3 connects a real tool-using LLM to the World Engine. The Sprint 2
  inference contracts held only text messages. A source review also found that fault
  evidence could claim a commit boundary that a call never reached.

## Decisions

1. **Typed conversation, not a framework.** `ConversationMessage` is a discriminated union
   of text, assistant-tool-call and tool-result messages, validated by
   `validate_tool_protocol`. The provider's ids and raw arguments are kept verbatim. No
   agent framework is used: the loop is about 250 lines we control and test.
2. **One agent, two policies.** Baseline and hardened share model, tools, mission, budget
   and temperature. The hardened prompt is the baseline prompt plus recovery rules, so any
   behavioral difference is attributable to policy.
3. **Structured claim as a tool.** The final claim is a `submit_final_claim` tool call
   validated as `FinalClaim`. Free text is never parsed for success. A text-only reply gets
   one reminder, then the run ends with no claim.
4. **Validate before the gateway.** The allowlist, the JSON-object check and the gateway's
   own Pydantic models run in the agent runtime, so rejected calls never reach the World
   Engine. The gateway still re-validates (defense in depth).
5. **Sequential, exactly-once execution.** Calls in one turn run in order. Each inference
   result is processed once. There are no runtime-level inference retries beyond the SDK's
   bounded retries, which happen before a response exists.
6. **Oracle unchanged; the assessment adds dimensions.** The Oracle still passes a correct
   state with an absent claim. For agent runs, `RunAssessment.outcome` labels that
   `state_correct_claim_missing`, never `success`. Provider failures are attributed to
   infrastructure unless an invariant broke.
7. **Fault effects follow the real outcome.** See
   [world-engine.md → Fault effects](../architecture/world-engine.md#fault-effects-sprint-3-c3-b).
   `phantom_success` without a staged write is not applied (`fault_skipped`).
   `phantom_failure` without a new commit is labeled response-only. Occurrence counting is
   unchanged.

## Consequences

- Faults can no longer distort a *replay* into a fabricated new id. A future
  "response-only success" fault would be a separate, explicitly named kind.
- Live behavioral claims need the live commands (`agent-run`, `agent-eval`). Offline tests
  use labeled provider fixtures and prove runtime correctness only.
- The agent runs in the API host process as trusted code. Running untrusted agents or
  generated code against the world needs the Sprint 4 sandbox-to-world coordinator.
