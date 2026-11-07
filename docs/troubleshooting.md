# Troubleshooting

Start with `make prereqs`, then `make doctor`. Every recorded issue is in [known-issues.md](troubleshooting/known-issues.md).

| Symptom | Cause | Fix |
|---|---|---|
| `uv: command not found`, or `[FAIL] uv` | Tool not installed | [Installation](installation.md) lists each tool |
| `[FAIL] docker  the daemon is not reachable` | Docker is not running | Start Docker Desktop, or `colima start` |
| `[FAIL] docker  ... under 2 GiB of memory` | The daemon's VM is too small | Raise it, for example `colima start --memory 4` |
| `[FAIL] sandbox-image  pinned image missing` | Not pulled yet | `make sandbox-image` |
| `make sandbox-image` fails | No network, or a registry limit | Retry when online. The image is never replaced by another tag |
| `Prerequisites are missing` from `make quickstart` | A required check failed | `make prereqs` says which |
| My run is not in the browser | Not signed in, or another evidence directory | Sign in on `/operator` with `make local-token`. Your own runs are operator evidence and are hidden until you do |
| `operator token must be at least 32 chars` | A short `MOODY_OPERATOR_TOKEN` | Remove it to use the generated one, or lengthen it |
| Port 3000 or 8000 is in use | Another service | Stop that service. The ports are fixed |
| `--fault needs --local-inference` | `FAULT=` only applies with `LOCAL=1` | Otherwise the rehearsal plan chooses the faults |
| A run is `INCONCLUSIVE` with `not started` | The sandbox did not start | The reason is in the run's `error` in `evidence.json` and in the log. Check Docker, then rerun |
| Leftover `moody-sbx-*` containers | A process was killed | `make sandbox-clean` |
| `make evidence-verify` exits 2 | Nothing to check | Run `make quickstart`, or pass `DIR=` |
| `make evidence-verify` reports `FAIL` | A record changed after it was written | Rerun the test. Do not edit evidence to make it pass |
