# ADR 0009: The design lab is not in the production build

**Status:** accepted, Sprint 10.

## Context

Sprint 10 needs working prototypes in the real app against real evidence, while the submitted release must
stay unaffected. A hidden route or a runtime flag would still ship the code.

## Decision

- Lab routes are `*.lab.tsx`. That is a route file only when `MOODY_DESIGN_LAB=1` adds `lab.tsx` to
  `pageExtensions` at build time. Without it, the routes do not exist.
- With the flag, Next builds to `.next-lab` using `tsconfig.lab.json`, so product output and types are untouched.
- The lab has its own Tailwind entry. `globals.css` excludes lab sources with `@source not`, so the product
  stylesheet is byte-identical.
- The theme re-points the product's token names inside `.rf`. It is the existing system in a new scope.
- The lab reads the evidence API through `lib/evidence.ts`. It holds no copy of any result.

## Rejected

- **A `NODE_ENV` check that returns 404.** The code would still ship.
- **Storybook.** A dependency and a second build, for a handful of pages.
- **Reading bundles from disk.** It would skip the hash and schema checks the API applies.
- **Sharing `tsconfig.json`.** Including both type directories failed the production build (KI-50).

## Consequences

Never set `MOODY_DESIGN_LAB` in deployment. Moving a component into the product means removing it from the
`@source not` list, so the product CSS changes on purpose, in that commit.
