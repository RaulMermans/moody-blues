# Evaluation and limitations

What has been shown, what has not, and how far each result reaches.

## What the evidence supports

| Claim | Supported? | Evidence |
|---|---|---|
| The Oracle verifies state independently of agent claims | **Yes** | Tamper-resistance tests; 0 disagreements in Sprint 19 |
| Faults are deterministic, and delivery is recorded | **Yes** | 575 benchmark experiments with validity recorded |
| Verified failures reproduce on deterministic targets | **Yes**, for scripts | 28 of 28 |
| External agents run contained in local Docker | **Yes**, locally | `make external-containment`. Not tested on a hosted VM |
| Two worlds share one runtime | **Yes** | Golden file; both worlds benchmarked |
| A real local model can drive a queue agent | **Yes**, as integration | 7 runs. Says little about model quality |
| Autonomous investigation finds more than simpler testing | **No** | See below |
| The Investigator's conclusions can be relied on | **No**, for the model tested | 25 of 40 contradicted the verified findings. Rely on the Oracle |
| Works with any agent framework | **Not shown** | Python, through the SDK |

## The Investigator is experimental

The Investigator is experimental AI-assisted investigation: one model that proposes hypotheses and experiments inside a
deterministic workflow. Its effectiveness has not been shown to exceed simpler testing strategies.

- **[Registered evaluation](evaluations/sprint-06/report.md): `NO_DEMONSTRATED_ADVANTAGE`.** Fixed testing found a verified
  failure in 2 of 3 investigations, adaptive in 1 of 3, non-adaptive generation in 0 of 3, on `glm-5.3`, on a small sample.
- **[Sprint 19 benchmark](evaluations/sprint-19/report.md): `INCONCLUSIVE`** (eligible share 0.52). With `qwen3:4b-instruct`
  against 14 scripted targets, it found 1.24 failures per investigation, against 1.93 for a fixed plan and 1.69 for a seeded
  random plan, at about 18 times the time. Its primary rate of 5.17 looks higher only because more of its budget went on
  faults that never fired, which shrinks the denominator. Do not quote that rate alone.

One small model and scripted targets do not describe stronger models. These results do not show the Investigator cannot
help. They show nobody should assume it does. You do not need it to use this project.

## Limitations

**Scope.** Two synthetic worlds, three fault kinds. A result covers the listed world, fault and target. One run is one
sample, not a rate, and a verdict states what is true of a run, not why. Saying a fault raised the chance of a failure needs
a registered contrast against a clean control.

**Agents.** Python through the SDK, and standard library only inside the sandbox. Scripted and fixture results never
describe model behavior. A real hosted model has not driven an external agent.

**Isolation.** Containers share the host kernel. gVisor and Kata have not been evaluated. Not a boundary for hostile code from
strangers. See the [trust model](security/trust-model.md).

**Evidence.** Nothing is signed. Verification finds damage, not a determined forger.

**Hosting.** The public demo is a single VM running an earlier revision. It has no Job Queue World and no external agents, and
its own live investigation found no violation. The spend ledger is an application-side estimate, not a provider limit.

**Worlds.** Adding one means editing the source, and only two similar worlds exist, so `mb-world/1` should not be read as a
stable or general contract.
