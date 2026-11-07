# ADR 0017: MIT license

**Status:** accepted, 2026-11-07.

## Context

The repository was public with no license, so nobody could legally use it. The Vultr Agent Rush rules require submissions to be
"MIT-compliant". The review in [license-decision.md](../release/license-decision.md) found no vendored third-party code. It found
one vendored asset, the Archivo font, under SIL OFL 1.1, and dependencies that are installed from lockfiles, not redistributed.

## Decision

- **MIT**, copyright 2026 Raúl Mermans, the sole author of every commit. The owner chose the holder explicitly on 2026-11-07.
- The same text is in `LICENSE` and `sdk/python/LICENSE`, so the SDK's sdist carries its own copy.
- `license = "MIT"` and `license-files = ["LICENSE"]` in both `pyproject.toml` files, `"license": "MIT"` in `frontend/package.json`.
- The Archivo font is named as an exception in `LICENSE` and stays under OFL, with `OFL.txt` beside it.

## Consequences

- The hackathon licensing requirement is met once this is on `main`.
- Contributions are accepted under MIT ([CONTRIBUTING.md](../../CONTRIBUTING.md)).
- The license grants no trademark rights, including to "Vultr".
