# ADR 0004: Isolated experiment runtime and trusted coordinator

- **Status:** accepted (Sprint 4, 2026-11-03)
- **Context:** Experiment code will eventually be written by a model, so it must be treated as
  hostile. It needs to influence and observe an agent run, while the sandbox has no network and
  the agent needs credentials, a database and the Oracle.

## Decisions

1. **Stepwise disposable containers, not a persistent channel.** Each step is a new container
   that prints one action and exits. *Rejected:* bridge networking (gives untrusted code a
   route to services); a mounted socket or volume (a host path into the sandbox, which
   AGENTS.md forbids); persistent stdio (lower latency, but a live channel means framing,
   backpressure and partial reads). The cost is about 150 ms per step, which is small next to
   a model call, and state must round-trip through `StepInput`.
2. **A step has no effects, by construction.** Actions are judged only after exit. This is what
   makes a sandbox retry safe and limits the uncertainty after a crash to target runs.
3. **Rejection is terminal in Sprint 4.** Simple and deterministic, and it gives no oracle for
   probing the validator. Sprint 5 may want bounded feedback; that should be a deliberate change.
4. **No free text towards the model.** Faults are chosen from a table, since their text reaches
   the agent verbatim.
5. **Target runs are never retried.** There is no setting. After an ambiguous failure the
   experiment ends `uncertain`.
6. **Write-ahead journal, evidence before completion.** An in-process coordinator is enough for
   now; durability comes from fsynced intent records, not a queue. The hash chain has no key:
   it detects edits and does not resist a local attacker.
7. **`TargetPort`, chosen by trusted code.** `AgentTarget` reuses `run_agent_scenario`
   unchanged. `ReferenceTarget` exists so mechanics can be shown without a model, labeled so
   they cannot pass as model behavior. A live target cannot be built without a ledger.
8. **Output comes from an attached stream.** See the rotation defect in the Sprint 4 record.
9. **Reserve-then-settle spending at assumed ceiling prices.** See
   [live-budget.md](../deployment/live-budget.md). Open reservations count in full.

## Consequences

- An Investigator can later supply the code without changing the boundary.
- `SandboxRunner.run` gains `cancel`; `ExecutionStatus` gains `CANCELLED`.
- `agent-eval` now needs `--confirm-billable`, and every live command goes through the ledger.
- The agent still runs in the trusted process.
