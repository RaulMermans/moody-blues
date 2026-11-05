# ADR 0008: One VM, native services, Docker only for sandboxes

**Status:** accepted, Sprint 8.

## Context

The job worker and ledger assume one process. The backend has an unauthenticated route that starts a
container. The credit is limited, and the hackathon is short.

## Decision

- One Vultr VM. Caddy is the only public listener. Next.js and FastAPI run natively under systemd,
  bound to loopback, as two users. Only the backend user can reach Docker.
- Docker runs sandboxes and nothing else. It publishes no port, so it cannot route around the firewall.
- Releases are `git archive` output under `/opt/moody-blues/releases/<sha>`, with a `current` symlink.
  Rollback moves the symlink. State lives in `/var/lib/moody-blues` and no release touches it.
- Plain scripts instead of Terraform: there is one VM and five API calls.
- `MOODY_PUBLIC_ORIGIN` decides the cookie's `Secure` flag and the origin check. Request headers do not.
- A ledger floor makes a lost ledger refuse spending, where it would otherwise look like a fresh start.

## Rejected

- **Containerizing the services.** Published ports bypass ufw, and the backend would still need the Docker
  socket, so this adds parts without removing the main risk.
- **Rootless Docker or gVisor now.** Neither has been run with this sandbox's limits. A late runtime change
  could break containment evidence days before the deadline. `investigator-preflight` reports whether
  `runsc` is available, and evaluating it on the VM stays possible.
- **A Caddy rate-limit plugin.** That needs a custom build of the public edge. A per-source connection limit
  in the host firewall uses what Ubuntu ships. It limits connections, not requests.

## Consequences

The backend user is root-equivalent through Docker, and systemd hardening cannot change that. There is no
redundancy: if the VM fails, the site is down. Both are acceptable for a demonstration.
