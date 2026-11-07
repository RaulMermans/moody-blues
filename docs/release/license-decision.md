# License decision

**Status: OPEN. An owner decision.** Nothing here applies a license. Until one is chosen, the repository is public with all
rights reserved, and no public open-source release is authorized.

## What was reviewed

Reviewed on 2026-11-07, on `sprint/20-developer-alpha-release`.

| Area | Finding | Effect on a repository license |
|---|---|---|
| Vendored code | None. No third-party source is copied into the repository | None |
| Vendored font | Archivo, `frontend/src/design/fonts/`, under SIL OFL 1.1, with `OFL.txt` beside it | Stays under OFL. Keep the file. Name the exception in any notice |
| Python dependencies | 45 installed: MIT, BSD, Apache-2.0, PSF, and MPL-2.0 for `certifi` and `hypothesis` (dev only) | Installed from lockfiles, not redistributed. No conflict with MIT or Apache-2.0 |
| Node dependencies, production | 63: MIT, Apache-2.0, ISC, BSD, 0BSD. Also `caniuse-lite` (CC-BY-4.0, data) and `@img/sharp-libvips-*` (LGPL-3.0-or-later, an optional prebuilt binary) | Installed, not redistributed. Review only if a future release ships a bundled binary |
| Hackathon assets, screenshots, recorded evidence | Project-made | Covered by the repository license, unless the owner excludes them |
| Third-party names | "Vultr" appears in docs and code as a factual reference | A license grants no trademark rights |

## Options

| Option | Fits when | Note |
|---|---|---|
| **MIT** | Simple, permissive, and plausibly matches the hackathon's open-license requirement | Recommended unless a patent grant matters |
| Apache-2.0 | An explicit patent grant matters | Also permissive. Needs a `NOTICE` only if you want one |

The hackathon rules are the owner's to check. They could not be read from here.

## Once the owner decides

1. Add `LICENSE` at the root, with the owner's chosen copyright holder and year.
2. Copy it to `sdk/python/LICENSE`, so the SDK and repository agree.
3. Add `license = "<SPDX id>"` and `license-files = ["LICENSE"]` to `pyproject.toml` and `sdk/python/pyproject.toml`, and
   `"license": "<SPDX id>"` to `frontend/package.json`.
4. Add the SDK classifier, and `Development Status :: 3 - Alpha`.
5. Replace the license section of `README.md`, and the last section of `CONTRIBUTING.md`.
6. Rerun `make test` and the SDK build, then record the decision in an ADR.
