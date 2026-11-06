# ADR 0010: The design system moves into the product

**Status:** accepted, Sprint 11. Amends ADR 0009.

## Context

Sprint 10 kept the design system apart from the product, so the submitted release stayed byte-identical. Sprint 11
redesigns the product's own Reality Comparison. The owner also reversed the visual hierarchy: Forensic Brutalism
is the foundation and Reality Fracture the exception.

## Decision

- `tokens.css` and `primitives.css` are imported by `globals.css` and sit on `:root`. The `.rf` scope is gone,
  so there is one theme and no second system.
- Archivo loads in the root layout, on every page.
- Copy and visual state stay in pure modules, `design/model.ts` and `design/story.ts`, which import nothing
  server-only, so rules can be tested directly against the committed bundles.
- The lab shrinks to a specimen page. Sprint 10's studies and prototypes are deleted, and their screenshots remain
  as the record. `*.lab.tsx` isolation from ADR 0009 is unchanged.
- `make test-design` now tests the product's screens. The lab build contains them, and its backend serves the
  real bundles, so no new server setup was needed.
- A Sprint 10 rule said an echo must not sit near a record. The owner's brief asked for a displaced outline on a
  duplicate. We kept the rule and met the intent differently: the real record itself slips out of line, so nothing
  decorative can ever be counted as state.

## Rejected

- **A `.rf` class on `<html>`.** It would satisfy nothing that `:root` does not, and would need the product's
  "no lab in production" test changed.
- **A new `--mb-*` token namespace.** A rename across the system with no change in meaning.
- **Keeping the studies running.** Three retired looks kept alive is a competing visual specification.

## Consequences

The product CSS and font change on purpose, so the "production CSS hash unchanged" check from KI-50 no longer
applies on this branch. It applied to protect the submitted release, which is protected now by not deploying.
A deploy of this branch needs the owner's approval and a rollback path: see
[Sprint 11](../sprints/sprint-11.md#release).
