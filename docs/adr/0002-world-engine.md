# ADR 0002: World Engine persistence, fault boundaries and Oracle independence

- **Status:** Accepted
- **Date:** 2026-11-03
- **Context:** Sprint 2. Build a stateful synthetic CRM whose tool observations can be
  distorted, plus an Oracle that determines what really happened.

## Decisions

1. **One SQLite file per world, stdlib `sqlite3`, no ORM.**
   - Each world is its own directory, which gives isolation by construction.
   - A file, unlike `:memory:`, lets the Oracle open a *second*, SQLite-enforced read-only
     connection (`mode=ro` + `query_only`). This makes read-only access a property of the
     database, not a code convention.
   - SQLAlchemy would add a dependency and hide the transaction boundaries that faults must
     target precisely.
   - Rejected: in-memory dicts (no real transactions; nothing to test rollback against) and
     a shared database with a `world_id` column (one bug away from cross-world leakage).
2. **Faults sit at explicit transaction boundaries, inside the gateway, not the store.**
   - `CrmStore.insert_customer(before_commit=...)` exposes a single pre-commit hook.
   - `phantom_success` returns `ABORT` from it.
   - `phantom_failure` acts only after `COMMIT`, by replacing the response.
   - The store stays fault-agnostic. The same hook is how tests simulate genuine
     transaction failures.
3. **Faults are deterministic.** They target an `(operation, occurrence)` pair, and there is
   no probability field. Random faults would make the Oracle's expected outcome
   unknowable, and a reproducible "flaky" fault can be expressed as a set of occurrences.
4. **The Oracle's verdict depends only on customer rows, the scenario and the claim.**
   - Delivered responses are read only to list divergences.
   - Fault events are never read.
   - A trigger-maintained `committed_changes` journal provides independent commit evidence
     for humans and tests.
   - Tests rewrite or delete response and fault evidence and assert that the verdict does
     not move.
5. **Three verdicts, with severity-ranked findings.**
   - `PASS`, `VIOLATION` and `INCONCLUSIVE`, as the sprint brief suggests.
   - An honest or conservative failure report (`underreported_completion`) is a
     **warning**, not a violation. This keeps the false-positive rate down (Risk B).
   - A missing record is a violation only if completion is claimed.
6. **Emails are not unique; idempotency keys are.** This matches common CRMs, makes
   duplicate side effects possible, and gives agents a correct recovery mechanism, so the
   world is not rigged (Risk E).
7. **Deterministic ids and logical time.**
   - Ids are `sha256(seed, call_seq)` and timestamps are `start + call_seq × tick`.
   - Equal inputs therefore give byte-identical state.
   - Phantom ids are never reused by later real creates.
8. **Expected verdicts live in tests, not in scenario files.** A future Investigator can
   read scenarios without seeing the answers.
9. **No HTTP surface yet.** AGENTS.md forbids unauthenticated experiment execution. Access is
   through the CLI and services.

## Consequences

- One CRM, one write tool. Adding update or delete tools needs new fault-boundary hooks, but
  the triggers already journal updates and deletes.
- SQLite file I/O is slower than in-memory, but acceptable: the example-based world tests run in under a second, and the Hypothesis suite takes about 5 s.
- Future untrusted, sandboxed code cannot reach the world directly: sandboxes have no
  network. A trusted coordinator will relay `ToolPort` calls (Sprint 3+).
