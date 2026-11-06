# Sprint 15: Bring Your Own Agent

- **Branch:** `sprint/15-agent-integration-sdk`, from `main` at `e2df51c` (PR #20). Committed locally:
  not pushed, merged or deployed.
- **Worked in:** `~/dev/Moody-Blues`, as the brief says.
- **Outcome:** an externally written agent now runs inside a real investigation, through a real
  boundary, and the existing Oracle judges it. **That is proven for scripted agents only. No external
  AI agent has been evaluated:** the model path has only met a labeled fixture.

North star: bring an external agent, execute it safely, observe its behavior, verify its outcome.

## Release preflight, 2026-11-06

| Item | Finding |
|---|---|
| Hackathon submission | **UNKNOWN, treat as critical.** The lablab form needs the owner's sign-in and no record says it was submitted. Deadline 2026-11-08 22:00 UTC |
| Production | **Up, unchanged by this sprint.** `/api/status` ready, inference `not_configured`. It does not serve Sprint 14's copy, so **production is behind `main`**, on the Sprint 13 release as far as can be told from outside. There is no revision endpoint |
| KI-51 | **Fixed live.** "wrong status" appears 0 times on the honest case's page |
| Repository | **Public, no LICENSE.** The README says all rights reserved. If the rules need an open license, this is an owner decision |
| Credentials | Rotation of the Vultr keys is **not confirmed**. It cannot be seen from here, and no values were read |
| CI | Last runs on `main` **succeeded**, including `e2df51c` |

## What was built

| Piece | Where |
|---|---|
| Contract, `mb-agent/1` | [contracts/adapter.py](../../backend/moody_blues/contracts/adapter.py), [protocol](../architecture/external-agent-protocol.md) |
| Long-lived sandbox session | [sandbox/docker_session.py](../../backend/moody_blues/sandbox/docker_session.py) |
| Driver: every rule of the boundary | [external/driver.py](../../backend/moody_blues/external/driver.py) |
| The target | [external/target.py](../../backend/moody_blues/external/target.py) |
| SDK, standard library only | [sdk/python](../../sdk/python) |
| Standalone example | [examples/external-agent](../../examples/external-agent) |
| Decision | [ADR 0012](../adr/0012-external-agent-adapter.md) |
| Quickstart | [external-agents/quickstart.md](../external-agents/quickstart.md) |

An external agent implements the existing `TargetPort`. Coordinator logic, gateway, faults, Oracle,
journal, recovery, Investigator and Explorer run unchanged, apart from new enum values and optional
fields. The one piece of new infrastructure is an open stdin on the existing container. Nothing else
was needed: no image, no service, no worker.

**Scope kept out:** HTTP, public access, MCP, new faults, new worlds, a pluggable Oracle, a Connect
Agent screen. The host-brokered model path reuses the existing Vultr client and spend ledger, because
the brief asks for an opt-in route and the sandbox has no network. It adds no provider.

## Results

External runs in real containers, with the fixture choosing faults:

| Agent | Run 1: phantom failure | Run 2 | Oracle |
|---|---|---|---|
| Careful script | PASS, 1 record | phantom success: PASS, 1 record | 0 of 2 in violation |
| Unsafe script | VIOLATION, 2 records | phantom failure again: VIOLATION, 2 records | 2 of 2 in violation |

The fixture's second step is chosen by what it observed, which is why the two differ. These prove the
adapter and the Oracle's separation of two policies. They are not LLM behavior.

Scenarios and metrics: [evaluation](../evaluations/sprint-15/README.md). 16 of 16, with **0
unauthorized or invalid calls reaching the gateway**, 303 ms startup and 2.4 ms per tool call.

## Acceptance gates

| Gate | Status | Evidence |
|---|---|---|
| C15-0 Release and submission safety | **BLOCKED** | Production, KI-51, license, CI checked, with no side effects. Submission and key rotation need the owner |
| C15-A Adapter contract | **PASS** | Versioned, typed, documented. Bad lines rejected, never repaired: `tests/external/test_contract.py` |
| C15-B SDK usability | **PASS** | The example imports only the SDK, enforced by an AST test. The SDK installs alone, with no dependencies |
| C15-C End-to-end execution | **PASS, scripted only** | A real investigation, real containers, the real coordinator. External AI agent: **NOT_RUN** |
| C15-D Tool and security boundaries | **PASS on this host** | Hostile agent in real Docker, secret canary, 0 calls past the gateway. **NOT_RUN on the Vultr VM** |
| C15-E Oracle and evidence | **PASS** | Verdicts from the existing Oracle; 13 of 13 complete; tampering detected; forged claims caught |
| C15-F Failure recovery | **PASS** | Timeout, crash, OOM, malformed, cancel, evidence-write failure, and a real SIGKILL mid-run: `uncertain`, nothing replayed |
| C15-G Developer experience | **PASS** | Followed from a clean tree with no `.env`, using the doc's own code blocks |
| C15-H Regression safety | **PASS** | All suites below. Recorded evidence byte-identical |

## Validation

| Check | Result |
|---|---|
| `make check` | **exit 0**: Ruff, Pyright strict, ESLint, tsc |
| Offline Python | **1,000 passed** (871 before, 129 new) |
| Real Docker (`-m docker`) | **97 passed**, 25 of them new |
| `frontend/e2e`, unmodified | **37 passed**, with a rehearsal on real Docker |
| `frontend/e2e-design`, unmodified | **217 passed** |
| `frontend/e2e-external`, new | **6 passed**, on real-Docker evidence and on the labeled double |
| `make recorded-verify` | **PASS**: every bundle rebuilt from raw records, byte-identical |
| `make eval-verify`, `make ledger-verify` | **PASS** |
| `make external-eval` | **16 of 16** |
| Paid inference | **None.** No live call was made |
| Hosted suite, containment report on the VM | **NOT_RUN**: not deployed |

## Defects found on the way

- **KI-66.** An agent that had reported was then killed, on every run, because the SDK's reader thread
  held up shutdown. It was invisible until a cancellation test, because nothing asserted a clean exit.
- **`--world` reached reserved worlds.** `external-run --world w-r1` would have used one up. It is now
  limited to the approved list.
- **A blocked write could outlast every deadline.** An agent that stopped reading could hold the host in
  `sendall`. Writes now time out.
- **External runs read "baseline policy".** They have no policy of ours. Removed from the pages and timeline.
- **A preflight that could never pass.** It cancelled before the handshake, so it became its own path.

## Known limitations

- **Python only**, standard library only: nothing can be installed in the sandbox.
- **One protocol, one world family.** Only the CRM tools and existing worlds.
- **Runs start from the command line.** They appear in the product for operators only.
- **The investigation is a fixture.** The real Investigator has not been pointed at an external agent.
- **`scenario_ref` hides a name, not behavior.**
- **`config` is still required by `mb-exp/1`**, and means nothing for an external agent.
- **Containment was tested on Colima on a laptop.** See the [threat model](../security/threat-model.md).
- **`frontend/e2e-external` is local only**, like `e2e-design`.
- `make evidence-audit` overwrites the committed Sprint 6 snapshot with whatever raw records are on the
  machine. It was run here, seen, and restored. Not changed in this sprint.

## Sprint 16 prerequisites

1. **Confirm the submission first.** Nothing here should move before that.
2. Decide whether Sprint 14 and 15 ship. Merging this does not deploy it, and it changes nothing a public
   visitor can reach.
3. **Run one live external LLM agent**, with explicit approval: `make external-run
   MANIFEST=examples/external-agent/llm.agent.toml LIVE=1 CONFIRM=1`. Until then nothing supports the
   claim that an external AI agent can be tested. Expect to fix something: it has only met a fixture.
4. Run `make external-containment` **on the VM** before external code runs anywhere but a laptop, and
   decide on gVisor or similar before anyone else's code does.
5. Then point the real Investigator at an external target. The seam is ready: `ExperimentRunner.target`.
6. Let an operator narrow scopes per run, before Sprint 18's Connect Agent screen needs it.
7. Add `make external-ui` to CI.
