# Accessibility and motion

## Results

Measured by `make test-design` on the product's real screens, at 390, 768 and 1440 px. Every row here is an automated
check. **No screen reader, no real Safari and no person was involved:** see [Not covered](#not-covered).

| Check | Result |
|---|---|
| axe (WCAG 2.0, 2.1, 2.2 A and AA, plus best practice), 12 screens × 3 widths, Chromium, **every disclosure opened first** | 0 violations |
| The task, report, outcome and verdict inside the first screen, 20 runs × 3 widths | All |
| Horizontal overflow, 12 routes × 3 widths, every disclosure opened first | None |
| All five tabs on screen with nothing scrolled away, 320 and 390 px | Yes |
| Headings: one `h1`, no level skipped, 7 screens with everything open | Yes |
| The current tab: `aria-current="page"`, under its full name at 390 px | Yes, from the accessibility tree |
| Keyboard: walks the tabs in order, opens a cycle with Space and a run's trace with Enter | Yes |
| A verdict wrapping inside a word, or a recorded value covered | None |
| Evidence text clipped at 390 px | None |
| Primary controls at least 44×44 px at 390 px | All measured: site nav, breadcrumb, tabs, run picker, ledger rows, disclosures, CTAs, Go deeper, copy, timeline steps and traces, cycles, Overview ladder |
| Keyboard: tabs, ledger rows, run picker; scrollable tables and code blocks are focusable | Yes |
| Focus ring | 2px solid paper, plus an outer ink ring |
| Comparison read order | Label, agent side, the seam as a sentence, authoritative side |
| Meaning with all colour forced to one grey | Verdict, seal glyph, duplicate flag and fault name all remain |
| Animations under `prefers-reduced-motion`, and at rest for everyone | 0 |

### Contrast

Computed from the rendered tokens. All 22 tested pairs meet AA at 4.5:1. The product has no text on decorative
texture any more, so the Sprint 10 gap over moiré is closed by removal.

| Pair | Ratio |
|---|---|
| Text on ground | 16.51 |
| Muted on high plane | 7.61 |
| Faint on high plane | 5.45 |
| Agent lavender on raised | 8.87 |
| Authoritative sand on raised | 11.27 |
| Divergence coral on raised | 6.17 |
| Ink on paper | 16.51 |
| Ink on pass tile | 10.64 |
| Ink on violation tile | 6.58 |
| Ink on inconclusive tile | 12.16 |

### Defects this audit found

axe and the 44px check found these in existing screens. All are fixed:

- The status panel used hard-coded `slate` colours that failed contrast. It now uses tokens.
- `dt` and `dd` sat outside any `dl` on the Investigator view.
- Wide tables were scrollable but not reachable by keyboard. `TableScroll` makes them named, focusable regions.
- The copy button was 22px tall.

Sprint 12 opened every disclosure before checking, and that found more:

- A nested wrapper broke `dl` structure on opened timeline events. Fixed.
- At 390 px, opening a tool call widened the page by 4,449 px (KI-55). It predates this sprint and is fixed.

### Browsers

| Engine | Covered |
|---|---|
| Chromium | Everything above |
| WebKit (Playwright build) | Layout at 3 widths: first-screen fit, overflow on all five views, tabs on screen, ledger rows as a grid, condensed variable font, deep links to calls, cycles and events. Screenshots inspected |
| Safari on real iOS or macOS | NOT_RUN. Playwright's WebKit is close to Safari and is not the same thing |
| Firefox | NOT_RUN |

### Not covered

- **No screen reader was used.** Names and order come from Playwright's accessibility snapshot. VoiceOver and NVDA are NOT_RUN. VoiceOver needs a person listening at the machine, and this sprint ran without one.
- **No user testing.** The 10-second and 30-second goals are design targets. The test is ready to run: [First-reader test](investigation-experience.md#first-reader-test).
- axe was not run in WebKit, and does not cover operator or containment screens.
- Inline links in running text are exempt from the 44px target and are smaller, as WCAG 2.5.8 allows.

### VoiceOver checklist, for a person

Turn on VoiceOver (Cmd-F5) in Safari and open `/investigations/inv_d0bc87de6010`. Record what is actually said.

1. Rotor, Landmarks: "Investigation views" is listed. Rotor, Headings: one heading 1, in order.
2. On a tab: it says "current page" and, at phone width, the full name "Raw evidence".
3. Timeline: a row announces collapsed or expanded, and the VIOLATION row says the word VIOLATION.
4. Investigator: a closed cycle reads its id, its hypothesis, the verdict and the model's reading, in that order.
5. Oracle seal: the verdict is read once, with no stray glyph.

## Rules

- Meaning is always carried by words. Colour and shape reinforce them.
- Decorative glyphs are `aria-hidden` and have a spoken equivalent.
- Evidence uses real structure: a named `section` per comparison row, `dl`, `ul`, tables with captions.
- Each comparison row is one event, so stacked and spoken order keep the two sides together.

## Motion

Sprint 11 removed all three of Sprint 10's entrance animations. The only motion left is a 120ms background
change on hover, and the disclosure chevron, both off under reduced motion. Nothing enters and nothing loops,
so the static page is the whole page.

Sprint 13 owns the motion system. A motion must only ever present what the static page already shows, and must
not suggest timing the evidence does not hold. Avoid continuous glitching, parallax, screen shake, and any motion
on text being read.
