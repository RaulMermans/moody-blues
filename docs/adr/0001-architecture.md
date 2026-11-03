# ADR 0001: Foundational architecture

- **Status:** Accepted
- **Date:** 2026-11-03
- **Context:** Sprint 1 of MOODY BLUES (Vultr Agent Rush, *Blast Radius Zero*)

## Context

MOODY BLUES will run adversarial experiments on AI agents inside isolated synthetic
environments. It will also verify outcomes independently of what the agent reports. We need a
foundation that is small and easy to reason about, that never overstates what it verified,
and that is safe to run with untrusted, model-generated code.

## Decisions

1. **Hybrid workflow–agent architecture.** One adaptive Investigator (later sprints) sits
   among deterministic services for execution, world state and verification. There is no
   multi-agent framework (LangGraph, CrewAI). One reasoning loop plus deterministic tools is
   easier to test and to audit for truth.
2. **Python 3.12 + FastAPI + Pydantic v2 backend, managed with uv.** Typed contracts at every
   boundary (`contracts/`), with an app factory and DI through `app.state`.
3. **Vultr Serverless Inference through the OpenAI Python SDK.** The endpoint is
   OpenAI-compatible, and the SDK gives us bounded retries, timeouts and a typed error
   hierarchy. We map those errors to our own `ErrorCategory`.
4. **Docker for sandboxing, through docker-py behind a `SandboxRunner` protocol.**
   docker-py gives structured exit codes, separate stdout and stderr streams, OOM status and
   reliable removal, which beats parsing CLI output. The protocol lets us swap in gVisor or a
   remote runner later.
5. **Pyright (strict), not Mypy.** It is faster, strict mode catches `Any` leaks at
   SDK boundaries, and it is the same engine editors use.
6. **Next.js frontend with a server-side proxy route.** We chose a route handler over
   `rewrites` because rewrites are resolved at build time. The route handler reads the backend
   URL at runtime and keeps it, and any credentials, off the browser.
7. **Verification vocabulary is part of the architecture.** Health endpoints and smoke
   commands distinguish *configured* from *verified*. Live provider checks are explicit and
   never automatic.
8. **No Redis, queues, databases or Kubernetes yet.** Nothing in Sprint 1 needs them.

## Consequences

- Positive: a small surface, fast tests, honest status reporting, and a sandbox that can be
  swapped out.
- Negative: sandbox runs are synchronous inside a threadpool request; long experiments will
  need a job model (Sprint 2+). Docker isolation shares a kernel (see the threat model in
  `docs/architecture/overview.md`).
- The OpenAI SDK 3.x depends on `httpx2`. Test transports must use `httpx2`, not `httpx`.
