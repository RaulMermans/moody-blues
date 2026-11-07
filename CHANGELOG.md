# Changelog

## 0.1.0, developer alpha (not yet released)

First version intended for developers beyond the project's author. Release status and blockers:
[Sprint 20 record](docs/sprints/sprint-20.md).

### Product

- Deterministic fault injection, an independent Truth Oracle, and hash-chained evidence, in CRM World and Job Queue World.
- External Python agents through `moody-blues-sdk` 0.1.1 and `mb-agent/1`, in a local Docker sandbox.
- Local inference through Ollama, experimental.
- The Investigator, repositioned as experimental AI-assisted investigation. Its benchmark results stay published.

### Added in the release preparation

- `make prereqs`, `make sandbox-image`, `make quickstart`, `make clean-local`, `make local-token`, `make evidence-verify`.
- `evidence-verify`: a read-only check of journals, hashes, run reports, tool and model provenance, world identity and Oracle findings.
- `revision` in `/health` and `/api/status` on a deployed release.
- Installation, quickstart, SDK reference, evidence, trust model, compatibility, platform and limitations pages. `SECURITY.md`,
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue and pull request templates.

### Changed

- `make dev` reads the disposable `.moody-local`, with live runs off, instead of `.artifacts`. Set `MOODY_ARTIFACTS_DIR` to choose.
  `make external-run` and `make external-investigate` write there too, unless a run is paid.
- `make setup` no longer installs the Playwright browser. `make setup-test` does.
- `make doctor` checks the digest-pinned image and Docker's memory, and fails if either is missing.
- SDK 0.1.1 marks the additive `record_id` (KI-78).
- README and landing copy lead with testing and verification. Hackathon material moved to the project history.

### Fixed

- `make doctor` could pass on a machine where no agent could start, because it checked an unpinned image.
- `--fault` was silently ignored without `--local-inference`. It is now refused.
- Verifying evidence that no longer parsed crashed instead of reporting it.
- A sandbox that failed to start left no trace in the log (KI-80).
- `make investigator-preflight`, a free command, wrote into `.artifacts` (KI-84).
- Stopping `make dev` segfaulted bash on Linux and left a `core` file (KI-83).
