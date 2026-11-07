# Trust model

For v0.1.0, developer alpha. Who is trusted, what the sandbox enforces, and what it does not. The hosted Explorer's
threats are in the [Explorer threat model](threat-model.md).

**This alpha is not intended to accept arbitrary hostile code from anonymous users.** There is no public way to submit an
agent. Containers share the host kernel, and isolation is not equivalent to a dedicated microVM. Run agents you wrote or
have read, on a machine you can afford to rebuild.

## Who is trusted

| Actor | Trust | What holds it to that |
|---|---|---|
| Project maintainers | Trusted | Code review |
| World plugins | Trusted code, listed by hand | No dynamic loading or upload |
| Tool broker and gateway | Trusted | Allowlist, scopes, arguments, quotas and deadlines are checked here |
| Truth Oracle | Trusted | Reads a read-only view. Tamper tests. Takes no input from agents |
| Coordinator | Trusted | The only thing that invokes a target, gateway or Oracle |
| External agents | **Untrusted** | Run only in the sandbox. Everything they send is validated, and a claim is only a claim |
| Generated experiment code | **Untrusted** | Sandbox, plus a validated `mb-exp/1` action set |
| Model output | **Untrusted** | Validated, never repaired. Cannot change a verdict |
| Operator | Authenticated | A token of at least 32 characters. Picks catalog missions only: no code, world, fault or limit |
| Public visitors | Read-only | See only committed, hash-checked recorded investigations. Start nothing |

## What the sandbox enforces

Every untrusted program runs in a fresh container, configured in `sandbox/docker_runner.py`.

| Boundary | Setting |
|---|---|
| Network | `network_mode: none` |
| Filesystem | Read-only root. `/tmp` is a 16 MiB tmpfs with `noexec,nosuid,nodev`. No mounts, no host paths |
| User | Non-root, all capabilities dropped, `no-new-privileges` |
| Memory | 128 MiB by default, swap equal to the limit |
| CPU | 0.5 CPU by default |
| Processes | 64 by default |
| Deadline | Enforced by the host, and by `timeout -s KILL` as PID 1, which the program cannot remove |
| Docker socket | Never mounted |
| Host secrets | No host environment: only `HOME` and `PYTHONDONTWRITEBYTECODE` are set |
| Image | Pinned by digest for agents and generated code, and never pulled implicitly |
| Tools | Allowlisted by scope in trusted code, before the gateway |
| Models | Reachable only through the host, and only those on `external_model_allowlist`. An agent cannot name one |
| Cleanup | Removed after each run. Labeled orphans are reaped once their deadline passes |
| Across worlds | One coordinator, one world. Another world's tool is unknown and reaches no gateway |

`make external-containment`, `make experiment-containment`, `make investigator-containment` and `make containment-report`
test these against a real daemon. Results for this release are in the
[Sprint 20 record](../sprints/sprint-20.md#docker-containment).

## What it does not do

- It does not defend against a kernel or container-runtime exploit. gVisor and Kata have not been evaluated.
- It does not protect the Docker daemon. Anything that can reach it is root-equivalent on the host, including this backend.
- Hosted containment was tested for the one-shot sandbox only. External agents' long-lived sessions have not run on a hosted VM.
- Evidence is hash-chained, not signed.
- The spend ledger is an application estimate, not a provider limit.

## Secrets

Secrets come from the environment or a git-ignored `.env`, as `SecretStr`. They are never in a sandbox, a browser bundle or
exported evidence: export refuses a bundle that contains a configured secret. CI runs gitleaks over the full history. The
local operator token from `make local-token` is a random value for this checkout, and is removed by `make clean-local`.
