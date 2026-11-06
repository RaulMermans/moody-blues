# ADR 0012: External agents as a target, over stdio, in a long-lived sandbox

- **Status:** accepted, Sprint 15
- **Context:** MOODY BLUES could only test agents it contained itself. A developer had no supported
  way to bring their own, and a thin wrapper around the internal agent would have proved nothing.

## Decision

An external agent is **one more kind of target**, implementing the existing `TargetPort`. It runs
as **one long-lived process in the existing Docker sandbox**, and talks to the host over **its
stdin and stdout**, one JSON document per line (`mb-agent/1`).

```
coordinator ──TargetPort──▶ ExternalAgentTarget ──▶ AdapterDriver ──stdio──▶ agent (sandbox)
     │                            │                      │
     │                            └ World, Oracle        └ ToolPort ──▶ gateway ──▶ faults ──▶ CRM
     └ journal, recovery, evidence (all unchanged)
```

Nothing around the target changes: experiments, authorization, fault selection, the journal,
recovery, the Oracle, the Investigator and the Explorer are the same code. There is no second
engine, no second Oracle and no second evidence format.

## Why these choices

**`TargetPort`, not a new runner.** The coordinator already chooses a target in trusted code and
depends on nothing else, so everything that makes a run trustworthy comes for free.

**stdio, not HTTP.** The sandbox has no network, and HTTP would need one. stdio has no address to
guard, a clear lifecycle and no listener, and it ends when the process ends.

**A long-lived process, not the existing step model.** A sandbox step is one program in, one
document out, and only a process exit lets anything happen. An agent keeps state across tool calls,
and replaying its history into a fresh process for every call would only work for deterministic
code, which rules out the real target: an LLM agent.

**Code travels over stdin.** Host mounts are forbidden and the root filesystem is read-only, so the
agent's package and the SDK are sent as one zip to a small bootstrap, which writes it to the
existing tmpfs. Python imports from a zip, so `noexec` still holds. No image is built, so the
pinned image remains the only thing the sandbox runs. The zip is deterministic, and its hash
identifies what ran.

**The SDK is standard library only.** The sandbox image holds nothing else. This also means the
wire format is the real contract: the SDK does not import the host's models, and
`tests/external/test_contract.py` holds the two together.

**The sandbox is not optional.** `AGENTS.md` says untrusted code runs only through a sandbox.
`ExternalAgentTarget` refuses a runner not approved for generated code, so there is no local,
uncontained mode. Offline tests use a real process through a double labeled
`local_process_test_double`, and only for agents in this repository.

**The host decides what a run is.** Agents state a `target_type`, and it is recorded, but the
evidence label comes from what was observed. The sandbox has no network, so a model can only be
reached through the host, which means an LLM run is exactly a run in which the host brokered a
model call. An agent cannot talk its way into being called a model, or out of it.

**`scenario_ref` is opaque.** Scenario ids name their faults (`phantom-failure`). The brief asks for
a scenario identifier in the context, and giving the real one would tell a target what its world
will do to it, so the agent gets a per-run hash instead.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| HTTP endpoint | Needs a network in the sandbox, or arbitrary outbound calls from the host |
| Subprocess on the host | Untrusted code outside a sandbox. Breaks a hard rule |
| Replay per step, on the existing runner | Only works for deterministic agents |
| Build an image per agent | New infrastructure, and a registry of unpinned images |
| Mount the agent's code | Forbidden |
| `docker` CLI subprocess | A second way to reach the daemon, beside docker-py |
| Trust a declared `target_type` | The label would then be the agent's own claim |

## Consequences

- `TerminationReason`, `target_kind` and `evidence_source` gain values. Evidence with an external
  run is `schema_version` 2. Anything else stays at 1 and byte-identical: `recorded-verify` proves
  it.
- A run costs a container start (about 0.3 s here) rather than a function call.
- `config` on the experiment protocol means nothing to an external agent, and is kept only because
  `mb-exp/1` requires it. The product does not display it for these runs.
- Containment is what Docker gives on this host. It shares a kernel. See the threat model.
