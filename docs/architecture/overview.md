# Architecture overview

_Last updated: Sprint 2 (2026-11-03). Covers only what is implemented; planned components are
marked as planned._

## Shape

A hybrid workflow–agent design. One adaptive **Investigator** (planned, Sprint 2+) will be
surrounded by deterministic services for execution, world state and verification. Sprint 1
builds those deterministic foundations and the contracts between them.

```text
 Browser ──► Next.js (frontend/)
              └─ /api/status route handler  ──server-side──►  FastAPI (backend/moody_blues)
                                                                ├─ api/       HTTP, request ids, error envelopes
                                                                ├─ services/  health/readiness logic
                                                                ├─ contracts/ Pydantic types shared by all layers
                                                                ├─ inference/ VultrInferenceClient ──► api.vultrinference.com/v1
                                                                ├─ sandbox/   SandboxRunner ──► Docker daemon ──► disposable container
                                                                └─ world/     World Engine: SQLite CRM ◄─ ToolGateway (faults) ; TruthOracle (read-only)
 CLI (moody-blues world-demo | world-run) ──► services/world_runner ──► world/
```

Built in Sprint 2: the synthetic CRM World Engine, controlled fault injection
(Phantom Success, Phantom Failure), the independent Truth Oracle, versioned scenarios and
deterministic world replay. See [world-engine.md](world-engine.md).

Planned (not built): the Investigator loop, LLM target agents, a coordinator between
sandboxes and the world, and evaluation across experiments.

## Components

### Backend (`backend/moody_blues`)

- **`api/app.py`**: `create_app(settings, sandbox_runner=...)` is the factory. Constructing
  the app makes no network calls. Dependencies live on `app.state` and are injected through
  `api/deps.py`, so tests can swap them.
- **`api/middleware.py`**: `RequestIdMiddleware` is the outermost ASGI middleware. It accepts
  a well-formed inbound `X-Request-ID` or generates one, binds it to a `ContextVar` for logs,
  echoes it on every response, and logs one structured line per request. It also turns
  unhandled exceptions into the 500 envelope. That has to happen here: Starlette routes
  catch-all `Exception` handlers to a layer outside user middleware (see known issues KI-4).
- **`api/errors.py`**: every error response is `{"error": {category, message, retryable},
  "request_id"}`. `MoodyBluesError` carries an `ErrorCategory`, which maps to an HTTP status.
- **`config.py`**: `Settings` (pydantic-settings), prefix `MOODY_`, with bounds on every
  numeric field. Secrets are `SecretStr`.
- **`logging.py`**: stdlib logging with a JSON or console formatter. Each line includes the
  request id when there is one.

### Health semantics

| Endpoint | Checks | Never claims |
|---|---|---|
| `GET /health` | Process is up; which integrations are *configured* | That Docker or Vultr work |
| `GET /ready` | Live Docker daemon ping (free) | That Vultr works. Vultr stays `configured_unverified`, because checking it costs money. |

Integration states: `not_configured`, `configured_unverified`, `not_checked`, `available`,
`unavailable`. Only a check that actually ran sets `checked_at`.

### Inference (`inference/vultr.py`)

`VultrInferenceClient` wraps the OpenAI Python SDK pointed at
`https://api.vultrinference.com/v1`. It handles:

- Timeouts, and bounded retries through the SDK's backoff (retries cover connection
  errors, 408, 409, 429 and 5xx; 401 is not retried).
- Error classification into `ErrorCategory.PROVIDER_*`.
- An `InferenceResult` that records `requested_model` alongside the provider-`reported_model`,
  the response id, finish reason, token usage (`None` when the provider doesn't return it),
  latency and tool calls.

Tool-call arguments come back as raw JSON text. Callers must validate them with a Pydantic
model before use (see `inference/smoke.py::AddNumbersArgs`).

The OpenAI SDK 3.x is built on `httpx2`, not `httpx`. Offline tests inject an `httpx2.Client`
backed by `MockTransport` fixtures, so the real SDK code path runs unchanged.

### Sandbox (`sandbox/`)

`SandboxRunner` (Protocol) has two methods: `run(SandboxRequest) -> SandboxResult` and
`ping()`. Infrastructure failures raise `SandboxError` or `SandboxUnavailableError`. A
`SandboxResult` is returned only when the code actually ran; it never stands in for an error.

`DockerSandboxRunner` creates one fresh container per run:

| Restriction | Setting |
|---|---|
| Network | `network_mode=none` (loopback only) |
| Identity | uid/gid `65534` (nobody) |
| Privileges | `cap_drop=ALL`, `no-new-privileges` |
| Filesystem | read-only root; `/tmp` as a 16 MB `noexec,nosuid,nodev` tmpfs; no host mounts |
| Resources | memory with swap disabled, CPU quota (`nano_cpus`), PID limit |
| Environment | only `HOME` and `PYTHONDONTWRITEBYTECODE`. Host env is never passed. |
| Wall time | host-side deadline, then SIGKILL, reported as `TIMED_OUT` (exit 137) |
| Output | log driver `max-size` plus in-process truncation (`*_truncated` flags) |
| Lifecycle | `remove(force=True, v=True)` in `finally`; `cleaned_up` is reported per run |
| Daemon | resolves `MOODY_DOCKER_HOST`, then `DOCKER_HOST`, then the active `docker context` |

#### Sandbox threat model

The restrictions above are **configured and observed** (`tests/security`). That is not a
proof of containment. Remaining risks:

- The container shares the host kernel (on macOS, the Colima/Docker Desktop VM kernel).
  Kernel exploits are out of scope for Sprint 1.
- It uses Docker's default seccomp and AppArmor profiles, not custom ones.
- No user-namespace remapping is configured.
- The image (`python:3.12-slim`) is pulled by tag, not digest.
- The image's own `ENV` values (PATH, LANG, PYTHON_VERSION and similar) are visible. They are
  not secrets.

Candidate hardening for later sprints: gVisor (`runsc`), a custom seccomp profile, digest
pinning, rootless Docker.

### World Engine (`world/`, `services/world_runner.py`)

These are three separate layers:

- **Actual world:** a per-world SQLite file.
- **Agent-perceived world:** `ToolResponse` objects from `ToolGateway`, which may be
  distorted.
- **Verified truth:** `TruthOracle`, reading through a SQLite-enforced read-only connection.

There is no HTTP surface yet. Full design: [world-engine.md](world-engine.md) and
[ADR 0002](../adr/0002-world-engine.md).

### Frontend (`frontend/`)

Next.js 16 (App Router, Cache Components), strict TypeScript, Tailwind v4. The browser calls
only `/api/status`, a route handler. That handler fetches `/health` and `/ready` from FastAPI
at request time, using `MOODY_BACKEND_URL` (server-only, so one build works against any
backend). The page renders integration states exactly as the backend reports them, and shows
no invented experiment data.
