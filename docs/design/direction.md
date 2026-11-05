# Design direction

## Concept: two realities, one truth

The product shows the gap between what an agent reported and what happened. The interface makes that
gap physical, and keeps one object perfectly still: the Oracle.

- **Duality.** Two unequal territories, 42/58. They differ in shape as well as colour.
- **Distortion.** One crack, which exists only where the Oracle recorded a violation.
- **Verification.** The Oracle is the only light object in a dark system. It is flat, square and never moves.

## The three studies

All three render the same recorded run, `run_cc34d7a6e314`, through the real evidence API.

| | A: Reality Fracture | B: Mirror Corruption | C: Forensic Brutalism |
|---|---|---|---|
| Image | ![A](screenshots/01-direction-a-reality-fracture.png) | ![B](screenshots/02-direction-b-mirror-corruption.png) | ![C](screenshots/03-direction-c-forensic-brutalism.png) |
| Idea | Overlapping planes split by a crack | A true reflection that fails at the point of disagreement | An evidence dossier with exhibits and a stamp |
| Palette | Charcoal, violet, amber, coral | Pure negative and positive | Paper, ink, one signal orange |
| Type | Compressed heavy Archivo | Expanded thin Archivo | Black Archivo, oversized numerals |

### Selection

| Criterion | A | B | C |
|---|---|---|---|
| Distinctiveness | High | High, but quiet | Medium: the dossier is a known genre |
| Concept fit | High: the break is the product | High for duality, weak for verification | High for verification, weak for distortion |
| Comprehension | High | Medium: mirrored text costs a moment | High |
| Accessibility | High on solid surfaces | Medium: a mirrored word is decoration only, and the layout depends on the axis | High |
| Feasibility | High: CSS and SVG | Medium: symmetry fails on uneven data such as 15 tool calls | High |
| Performance | High | High | High |
| Fit with evidence screens | High: dark, like the product | Low: half of every screen is light | Medium: a full light theme is a second theme |

**Selected: A as the identity, with three parts of C.** These judgements are the design team's, from the
rendered studies. They are not measured results.

Taken from C, and used only for the Oracle:

1. The paper surface. C's weakness as a whole-product theme is its strength on one object: on a dark
   screen, a light slab is unmistakably the authority.
2. Heavy square rules and the invariant ledger.
3. Oversized evidence numerals.

Left out of C: the rotated stamp. It looks forensic, but the Oracle must be the one thing that never tilts.
Left out of B entirely, though the unequal record counts keep its best idea: the reflection fails at the
disagreement.

## Prototypes

| Landing | Reality Comparison |
|---|---|
| ![Landing](screenshots/04-landing.png) | ![Comparison](screenshots/05-comparison-fold.png) |

The two statements sit out of register across the crack. Under each sits the same event in its two states:
the filed status, and the committed rows.

The Comparison reads in one pass: `completed` against `2`, the crack with its count, then the Oracle's
verdict, all above the fold at 1440×900. Tool calls are one link away and no longer lead.

Full page: [desktop](screenshots/05-comparison-full.png), [tablet](screenshots/06-tablet-comparison.png),
[phone](screenshots/06-mobile-comparison.png). Clean case: [Recovery](screenshots/08-comparison-clean-case.png).
Primitives: [system](screenshots/09-system.png).

## Visual principles

1. **Distortion is earned.** Only an Oracle `VIOLATION` cracks the frame, ghosts the title or draws moiré.
   A clean case looks calm, so the crack means something when it appears.
2. **Decoration around evidence, never on it.** Recorded values are large, but they are never layered,
   sliced or skewed.
3. **The Oracle does not move.** Not rotated, not offset, not echoed.
4. **Shape before colour.** Agent Reality has a dashed edge and Actual Reality a heavy solid rule. Each status
   has its own glyph, word and form.
5. **Absence looks like absence.** A missing verdict is hollow. It never resembles a result.
6. **One accent per moment.** Violet and amber claim territory; coral appears only at the break.
7. **Depth from planes.** No shadows, blur or glass.
8. **Unequal on purpose.** The split gives Actual Reality more room, because it is the one that counts.

## An evidence finding that shaped the design

The brief's example was one perceived outcome against two committed records. In the signature run that is
not what the agent believed. Its structured claim says `completed` and names one id, but its message names
the extra record too. The case note calls this "a false status, not concealment".

So the left side shows what the agent **filed**, and the 1 is labeled as ids in the structured claim. The
disclosure is always visible, including on the landing page. The record slab says which record the agent
named where.

The run also holds a real ghost: `cus_539789ad91c7bf14` was reported created at call 1 and never committed.
That appears in Agent Reality as a dashed phantom write, read from `fault_effect`.

The supplied headline "What the agent believed" stays as editorial copy, with the disclosure beside it.
"What the agent reported" would be more exact. That is an owner decision for Sprint 11.

## References

Principles were taken from the supplied pages, read as text: brutalist and dark-mode collections, a
split-screen concept and a split-screen layout catalogue. No artwork or identity was copied. What carried
over: bluntness as a decision, one accent, depth by lighter surfaces, proportion doing the hierarchy.
