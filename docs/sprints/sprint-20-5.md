# Sprint 20.5: final polish and submission readiness

2026-11-07. Branch `release/final-submission-polish`, from `main` `2185db2`. No new features.

## Outcome

- **License applied: MIT**, copyright Raúl Mermans, chosen by the owner on 2026-11-07. `LICENSE`, `sdk/python/LICENSE`,
  `pyproject.toml`, `sdk/python/pyproject.toml`, `frontend/package.json`, README, CONTRIBUTING, CHANGELOG,
  [ADR 0017](../adr/0017-mit-license.md). The Archivo font stays under SIL OFL 1.1. The prepared patch is removed now that it
  is applied.
- **Docs made consistent with the code and the current state.** The README no longer says the demo redeploys automatically:
  `make ship` is run by hand. It now states the hosted live run's result (no violation). FINAL-SUBMISSION, the gates table,
  the publication plan and the submission pack no longer say the license or the README section is pending. `copy.md` is
  marked superseded, so its older short description cannot be pasted by mistake. Two broken anchors in the Sprint 10 record fixed.
- **Page titles.** Every page was titled "MOODY BLUES", so tabs, history and screen readers could not tell them apart
  (WCAG 2.4.2). Now: "Containment · MOODY BLUES", "Run a test · MOODY BLUES", "Investigation · MOODY BLUES"; the landing
  page is unchanged. One e2e assertion added.
- **KI-85.** Gitleaks on the iCloud copy scanned 28 of 156 commits and still said "no leaks found". Recorded with the workaround.

## Checks

| Check | Result |
|---|---|
| Lint (ruff, ESLint) | PASS |
| Typecheck (pyright strict, tsc) | PASS, after removing iCloud `* 2.*` duplicates from generated `frontend/.next` |
| `make test`, `make test-integration`, `make test-e2e` | Local NOT_RUN (iCloud eviction); GitHub CI on the PR. See [results](#suite-results) |
| SDK and backend build | PASS. Wheels and sdist carry `LICENSE`, `License-Expression: MIT`, `Metadata-Version: 2.5` |
| Gitleaks v8.30.0, `main` `2185db2` history | PASS: 156 of 156 non-merge commits, no leaks |
| Gitleaks, tree of `main` | 6 findings, all six already allow-listed false positives in `.gitleaksignore` |
| Gitleaks, `~/dev/Moody-Blues/.artifacts/submission` | PASS: no leaks |
| Public site, `/`, `/containment`, `/operator`, scripts | No key names, bearer tokens or key-shaped strings served |
| `make deploy-lint`, `recorded-verify`, `eval-verify`, `bench-verify` | PASS |
| Relative links in 139 Markdown files | PASS after the two anchor fixes |
| Submission assets | Hashes match FINAL-SUBMISSION. Video H.264 1920×1080 30 fps, AAC 48 kHz, 4:30.4, 28.3 MB. Deck PDF 9 pages. Cover PNG 1920×1080 |
| Official rules, re-read 2026-11-07 | Unchanged: "MIT-compliant"; README must explain Vultr services; limits 5–50 / 50–255 / 600–2000; video MP4/MOV ≤ 300 MB; no deadline time published |

No paid inference, no model download, no infrastructure change. Canonical evidence and `.artifacts` were not modified.

## Video and deck

Recorded 2026-11-05, before the later redesigns. The narration, verdicts and numbers match the README and the evidence:
one VIOLATION, 4 of 4 reruns, 8 of 8 containment attempts blocked, a hosted run with no violation, and
`NO_DEMONSTRATED_ADVANTAGE`. The video frames the Investigator as designing experiments, which is accurate, and shows that it had
no advantage. Only the visual design differs, and FINAL-SUBMISSION discloses it. Not regenerated.

## Suite results

Locally, from the Desktop copy, `make test` passed every test it reached (74%, no failures), then hung in
`tests/explorer/test_legacy_compatibility.py` reading `.artifacts/experiments/*/evidence.json`: 148 of 372 were evicted iCloud
files (KI-34), and about 2,600 files in the checkout were dataless. `brctl download` had not restored them after five minutes,
so the local run was stopped. **Local `make test`, `make test-integration` and `make test-e2e`: NOT_RUN to completion.**

The pull request's GitHub CI is the gate: gitleaks over full history, deploy lint, ruff, pyright, the Python suites, the Docker
integration and security suites, the frontend lint, typecheck and production build, and Playwright e2e with the quickstart.
The merge waited for it.

## Owner actions

See the final report in this sprint's pull request. In short: confirm enrollment, rotate the Vultr account and inference keys,
upload the three assets, press Submit, and keep the confirmation.
