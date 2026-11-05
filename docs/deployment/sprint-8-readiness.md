# Hosted preflight: readiness for Sprint 8

_Written at the end of Sprint 7. Nothing here has been deployed, and no VM has been created._

## Decide first

- [ ] Owner approves creating a Vultr VM and the spend it implies.
- [ ] Owner decides whether the hosted demo offers chargeable missions at all. Recorded evidence and
      rehearsals need neither a key nor any credit.
- [x] One real live verification run, locally: `inv_ab4479c3fe80`.

## Blockers

| # | Blocker | Why | Fix |
|---|---|---|---|
| 1 | The backend must not be public | `POST /sandbox/smoke` needs no token and starts a container | Bind FastAPI to a private interface; expose only Next.js |
| 2 | No TLS or reverse proxy | The operator cookie must be `secure` | Terminate TLS, forward the protocol, and decide `secure` from that rather than `request.url` |
| 3 | Docker on the host | Rehearsals and live missions need a daemon and the pinned image | Install Docker; `docker pull` the value of `generated_code_image`; run `make investigator-preflight` on the VM |
| 4 | The ledger is a local file | A fresh VM would start from zero and forget $6.50 of recorded spend | Copy the ledger across, or set the limit from what the provider console shows |
| 5 | Actual billing is unverified | About $7.00 is an estimate at assumed prices | Read the Vultr console before raising any limit |
| 6 | No process supervision | A crash leaves the site down, though jobs reconcile on restart | systemd units for both services; `Restart=on-failure`; a stop timeout above 20 s so cancellation can finish |
| 7 | No public rate limiting | Evidence reads are cheap, but unbounded | Limit at the proxy |
| 8 | Disk retention | `live-jobs/` and experiment records grow without limit | Set a retention policy, and exclude `.artifacts` from anything public |

## Local facts to carry over

- Runs as a single process by design: one worker thread, one file lock. Do not run multiple replicas.
- Set `MOODY_OPERATOR_TOKEN` to a fresh value of at least 32 characters. Do not reuse a local one.
- Leave `MOODY_LIVE_RUNS_ENABLED` unset unless a chargeable mission is intended.
- `MOODY_BACKEND_URL` is read by the Next.js server at request time, so one build serves any backend.
- `MOODY_CORS_ORIGINS` can stay at its default: the browser never calls the backend.
- Recorded evidence ships in the repository. A hosted site needs no `.artifacts` to show it.

## Preflight on the host

```bash
make doctor
make recorded-verify
make investigator-preflight
curl -s 127.0.0.1:8000/ready
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<host>/api/operator/jobs   # expect 403 or 401
curl -s -o /dev/null -w '%{http_code}\n' https://<host>:8000/health                 # expect no connection
```

Then, with a token set, run one rehearsal from the Operator page and open its evidence.

## Measured locally

See [the Sprint 7 record](../sprints/sprint-07.md#resource-usage).
