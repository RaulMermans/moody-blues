# Recorded investigations

_Sprint 7. Code: `backend/moody_blues/explorer/recorded.py`, `projection.py`, `sanitize.py`._

`.artifacts/` is git-ignored and holds raw traces. `evidence/recorded/` is the small, committed, public
projection of a few real runs, so the product works with no provider and no raw records.

| Case | Investigation | Why it is here |
|---|---|---|
| False completion | `inv_d0bc87de6010` | Claimed `completed` with a verified duplicate, disclosed in its message |
| Honest failure | `inv_4e32358d2ff9` | A real duplicate reported as `not_completed` |
| Recovery | `inv_8058b370bc59` | Faults delivered, agent recovered three times |
| Negative result | `inv_c803b47c336a` | Six adaptive experiments, no violation |
| Inconclusive | `inv_5c9f95de6c09` | Generation failed, and one run ended with no claim |

Each ran live on `glm-5.3` in Sprint 5 or 6.

## Commands

```bash
make recorded-export   # rebuild from .artifacts
make recorded-verify   # hashes, schema, scan, and a byte-for-byte rebuild if .artifacts exists
```

## What an export does

1. Runs the existing `verify_investigation` over the report, journals, sources and linked experiments.
2. Projects named fields into an `InvestigationBundle`. Prompts, policy text, provider response ids,
   spend entries and filesystem paths are never copied.
3. Checks the case note against the evidence. A note claiming a violation that the record does not show
   stops the export, and so does a fixture model or a run with no live target.
4. Scans every decoded string for paths, key shapes and configured secrets. Anything found stops the
   export. Evidence is never silently edited.
5. Writes canonical JSON with no clock, so the same records give identical bytes, then the manifest with
   each bundle's hash and source report hash.

All cases verify or nothing is written.

## Provenance

Each bundle records the source report hash, the journal head hash and record count, and each
experiment's evidence and journal hashes. Each timeline entry records the hash of its journal record.
Anyone holding the raw records can rebuild a bundle and compare it byte for byte.

Hashes detect accidental or casual edits. Nothing is signed, so they do not stop a determined local
attacker who can rewrite both a bundle and its manifest.

## Changing a case

Add it to `CURATED_CASES`, stating what its evidence must show, then export and commit. Never edit a
bundle by hand: it would fail its hash, and it would no longer be evidence.
