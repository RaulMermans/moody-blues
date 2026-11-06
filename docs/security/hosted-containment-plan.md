# External containment on the Vultr VM: plan

**Status: NOT_RUN.** External-agent containment has been tested on Colima only. Do not read local results as a
claim about the VM. This plan needs an authorized maintenance window.

## What differs

Compared from `evidence/containment/report.json`, `evidence/containment/vultr-report.json` (2026-11-05),
`infra/vultr/` and the local daemon. The VM was not contacted in Sprint 16.

| Area | Colima, laptop | Vultr VM | Why it matters |
|---|---|---|---|
| Architecture | aarch64 | x86_64 | Different seccomp syscall tables. Results do not transfer |
| Kernel | 6.8.0-117-generic, in a VM on macOS | 6.8.0-147-generic, on the host | On the VM, an escape reaches the machine that runs the service |
| OS | Ubuntu 24.04.4 | Ubuntu 24.04.5 | |
| Docker | 29.5.2 | 29.1.3, `docker.io` package | Different engine |
| Cgroups | v2, `cgroupfs` | v2, `systemd` | Memory and PID limits are enforced by a different path |
| Daemon security | apparmor, seccomp, cgroupns | Same, plus daemon-wide `no-new-privileges` | The VM is slightly stricter |
| User namespaces | Not enabled | Not enabled | Container uid 65534 is host uid 65534 |
| Runtime | runc | runc. No gVisor or Kata | Shared kernel on both |
| Network | `none` for agents | `none`, with ufw and a Vultr firewall group outside | The VM adds layers, unproven for a session |
| Filesystem | Read-only root, `noexec` tmpfs | Same settings | Same code. Enforcement is unproven for a session |
| Host secrets | `.env` on the laptop, unreachable from the VM guest | `/etc/moody-blues`; no provider key at present | A key added for a live run would raise the stakes |
| Docker socket | Not mounted | Not mounted; only user `moody` can reach it | A backend compromise is a host compromise |

The hosted report predates Sprint 15. It covers the one-shot sandbox, **not the long-lived session**: open stdin, a
process alive for a whole run, attacker-chosen code. None of that has run on the VM.

## Plan

1. Owner confirms the submission is safe and picks a window after judging, or with the app quiet.
2. Confirm the deployed revision has Sprint 15 and 16. **It does not today.** Deploying them is its own decision.
3. Run as user `moody`, with the service left running, so nothing restarts:
   `MOODY_ARTIFACTS_DIR=$(mktemp -d) make external-containment`
4. Run `make containment-report`. Only the instance metadata service can make it `vultr_hosted`.
5. Watch: `docker ps --filter label=io.moody-blues.sandbox` returns to empty, and `/api/status` stays ready.
6. Commit the report beside the existing one, labeled with the host.

**Stop if** `/api/status` degrades, a sandbox survives its deadline, or memory passes 80%.

**This does not make public agents safe.** It would show the configured limits hold there. Arbitrary public bundles
stay out of scope until a stronger isolation layer is decided.
