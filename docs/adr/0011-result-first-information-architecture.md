# ADR 0011: Result-first information architecture

Status: accepted, Sprint 14. Replaces the "the default stays the Comparison" decision in
[investigation-experience.md](../design/investigation-experience.md).

## Context

An investigation opened on a page of 12 stacked, fully expanded sections: 1,112 words and 8.5 phone screens. A
reader had to learn five technical view names before finding out what happened.

## Decision

- An address with no `?view=` opens **Result**. The tabs read Result, What happened, Investigation and Evidence.
  Timeline sits inside Evidence.
- The URLs do not change. All five `?view=` values, `run=`, `cycle=`, `event=`, `call=` and `show=all` answer as before.
  Only a bare `/investigations/<id>` lands somewhere new, and it still shows the same run.
- Three levels. Result: outcome and verdict. Story: events and what differed. Evidence: everything else, closed by
  default, and opened by any link that points into it.
- First-screen copy comes from `design/outcome.ts` and `design/sequence.ts`, under the same rules as `story.ts`.
- A qualifier never folds: disclosure, scope, cause, the agent's message and the target's identity stay in view.
- A run whose verdict differs from its investigation leads with its scope note, above the headline.

## Consequences

- The Sprint 11 line "the Comparison is the demo's first screen" no longer holds. The video and deck were already stale.
- Starting a rehearsal takes one more click, because every test now has a confirmation.
- Browser tests that opened a bare address to reach the comparison now name `?view=reality`.
