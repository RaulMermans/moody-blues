# Accessibility and motion

## Results

Measured by `make test-design` in Chromium at 390, 768 and 1440 px.

| Check | Result |
|---|---|
| Horizontal overflow, 7 routes × 3 widths | None |
| Verdict wraps inside a word, or a recorded value is covered | None |
| Evidence text clipped at 390 px | None |
| Keyboard reaches the CTA, disclosure and raw evidence link | Yes |
| Focus ring | 2px solid, plus an outer ring |
| Headline read once and in order | Yes |
| Decorative layers `aria-hidden` | All |
| Animations under `prefers-reduced-motion: reduce` | 0 |

### Contrast

Computed from the rendered tokens. All 23 tested pairs meet AA at 4.5:1.

| Pair | Ratio |
|---|---|
| Text on ground | 17.09 |
| Text on high plane | 13.80 |
| Muted on high plane, the lowest muted pair | 6.53 |
| Faint on raised, the lowest faint pair | 5.63 |
| Agent violet on Agent plane | 6.57 |
| Actual amber on Actual plane | 10.50 |
| Coral on Actual plane | 6.05 |
| Ink on paper | 17.09 |
| Ink on PASS / VIOLATION / INCONCLUSIVE seal | 12.59 / 6.57 / 15.52 |

### Not covered

- No screen reader was used. Accessible names come from Playwright's accessibility snapshot.
- No automated audit such as axe: it would be a new dependency.
- Contrast is computed on solid tokens. Text over moiré was only checked by eye, and the moiré is kept to
  low opacity away from text.
- Chromium only.

## Rules

- Meaning is always carried by words. Colour and shape reinforce them.
- A decorative layer is `aria-hidden` with `pointer-events: none`, so it cannot catch a click.
- Evidence uses a real structure: `section` with a name, `dl`, `ul`, headings.
- Interactive targets on the prototypes are at least 44px high. The lab's own chrome is not.

## Motion language

Sprint 10 defines the language and ships three small demonstrations. Sprint 13 owns the rest.

Motion is sharp and brief. Things land and stop. Nothing loops, so a page at rest is still.

| Implemented | Duration | Meaning |
|---|---|---|
| Agent plane shifts into place | 320ms | The break settles. Violations only |
| Echoes step out from their object | 320ms after 180ms | A displaced duplicate |
| Verdict stamps | 180ms after 320ms | The Oracle has the last word |

Proposed for Sprint 13: the crack drawing in, a state transition from perceived to actual, interrupted
borders. Avoid continuous glitching, parallax, screen shake, and any motion on text being read.

All animation lives inside `@media (prefers-reduced-motion: no-preference)`, so the final state is the default
and reduced motion is not a special case: [landing](screenshots/07-reduced-motion-landing.png),
[comparison](screenshots/07-reduced-motion-comparison.png). A motion must only ever present what the static
page already shows, and must not suggest timing the evidence does not hold.
