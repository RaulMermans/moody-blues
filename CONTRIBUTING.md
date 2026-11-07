# Contributing

Thanks for looking. v0.1.0 is a developer alpha, so please open an issue before anything large.

## Setup

Follow [installation](docs/installation.md), then `make setup-test` for the browser suites.

## Before opening a pull request

```sh
make lint typecheck test     # offline, a few minutes
make test-integration        # real Docker
make check                   # everything except live calls
```

Add a regression test for every real defect, and keep documentation in the same change as the code.

## Rules that matter most

[AGENTS.md](AGENTS.md) is the full rule set. The ones reviewers will hold you to:

- **Never weaken a failing test** to get green. Find the cause.
- **Only the Oracle gives a verdict**, and it reads committed state, never what an agent was told.
- **External and generated code runs only in the sandbox.** Never mount the Docker socket or host paths.
- **Never hand-edit evidence**, a frozen registration or a ledger. A correction is a new revision.
- **Never describe a script or fixture as a model**, or a recorded run as live.
- **No secrets** in code, logs, fixtures or commits.

## Commands that cost money

`make help` marks them `LIVE + CHARGEABLE`. You never need them to contribute, and they refuse to run without credentials and
explicit confirmation.

## What is out of scope for now

New worlds, fault families, agent frameworks and model providers, public agent uploads, and multi-tenant accounts. Open an issue
to discuss one. See [Adding a world](docs/extending-worlds.md).

## Licensing of contributions

The project has no license yet, so please wait for one before contributing code.
