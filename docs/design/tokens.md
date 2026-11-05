# Design tokens

Source: [`frontend/src/design/styles/tokens.css`](../../frontend/src/design/styles/tokens.css), scoped to `.rf`.

Components read only the semantic tier. `--rf-p-*` primitives stay inside that file.

## Colour

Reality identity says whose reality something is. It never says good or bad. Status says what was found,
and never marks a reality. Oracle paper is neither: it is the authority.

| Token | Value | Use |
|---|---|---|
| `--rf-surface-base` | `#0d0c12` | Ground |
| `--rf-surface-raised` | `#191720` | Cards on the ground |
| `--rf-surface-high` | `#25212e` | Claim slips, lab chrome |
| `--rf-rule` | `#3a3446` | Quiet rules |
| `--rf-text` | `#f2eff4` | Primary text |
| `--rf-text-muted` | `#aba4b6` | Secondary text |
| `--rf-text-faint` | `#958ea2` | Tertiary text, on base and raised only |
| `--rf-agent` | `#a88bff` | Agent Reality identity |
| `--rf-agent-plane` | `#1a1430` | Agent Reality territory |
| `--rf-actual` | `#ffb77a` | Actual Reality identity |
| `--rf-actual-plane` | `#1f150e` | Actual Reality territory |
| `--rf-oracle-surface` | `#f2eff4` | The Oracle's paper |
| `--rf-oracle-ink` | `#0d0c12` | Ink on paper |
| `--rf-oracle-rule` | `#c9c3cf` | Rules on paper |
| `--rf-divergence` | `#f26a73` | The crack and recorded fractures only |
| `--rf-status-pass` | `#8de0c2` | PASS |
| `--rf-status-violation` | `#f26a73` | VIOLATION |
| `--rf-status-inconclusive` | `#dcf06e` | INCONCLUSIVE |
| `--rf-status-incomplete` | `#aba4b6` | Failed, cancelled, budget exhausted |
| `--rf-status-unverified` | `#958ea2` | No verdict exists |
| `--rf-status-ink` | `#0d0c12` | Ink on a solid seal |

The brief's starting palette held, except for additions: `--rf-status-inconclusive` is a new acid yellow,
because the product's warm `--warn` sat too close to amber identity. The two plane colours are new too.

### Product tokens

Inside `.rf`, the product's names are re-pointed, so `Tag`, `Code` and `VerdictTag` take the theme unchanged:

| Product token | Becomes |
|---|---|
| `--background`, `--surface`, `--surface-raised`, `--line` | Surface and rule tokens |
| `--foreground`, `--muted`, `--faint` | Text tokens |
| `--agent` | `--rf-agent` |
| `--truth` | `--rf-actual`. The product's name for Actual Reality: cyan today, amber here |
| `--good`, `--bad`, `--warn` | Status tokens |

## Typography

| Token | Value | Use |
|---|---|---|
| `--rf-font-display` | Archivo, then Arial Narrow, Impact | Editorial type and large evidence words |
| `--rf-font-tech` | System monospace | Ids, timestamps, tool calls, JSON, labels |
| `--rf-font-text` | System sans | Reading text |
| `--rf-type-colossal` | `clamp(3.75rem, 9.5vw, 10rem)` | Landing headline |
| `--rf-type-poster` | `clamp(3rem, 7vw, 6.5rem)` | Evidence words, page titles |
| `--rf-type-title` | `clamp(1.75rem, 3.2vw, 3rem)` | Section and frame titles |
| `--rf-type-lead` | `clamp(1.0625rem, 1.3vw, 1.25rem)` | Lead text |
| `--rf-type-body` | `0.9375rem` | Reading text |
| `--rf-type-data` | `0.8125rem` | Technical values |
| `--rf-type-micro` | `0.6875rem` | Uppercase labels |
| `--rf-leading-display` | `0.86` | Display line height |
| `--rf-tracking-display` | `-0.012em` | Display tracking |
| `--rf-tracking-micro` | `0.16em` | Label tracking |
| `--rf-width-compressed` | `62%` | Archivo's narrowest width |

Archivo is SIL OFL 1.1, committed as one 90 KB Latin file with width and weight axes
([licence](../../frontend/src/design/fonts/OFL.txt)). It adds no package and loads no remote asset.
Technical type uses system fonts, so evidence never waits for a font.

## Grid, rules and geometry

| Token | Value | Use |
|---|---|---|
| `--rf-space-1` … `--rf-space-16` | `0.25rem` … `4rem` | 4px base spacing |
| `--rf-gutter` | `clamp(1rem, 3vw, 2.5rem)` | Page gutter |
| `--rf-measure` | `62ch` | Reading width |
| `--rf-border-hair` / `-rule` / `-heavy` / `-slab` | `1px` / `2px` / `6px` / `14px` | Rule weights |
| `--rf-cut` | `14px` | The claim slip's cut corner |
| `--rf-band` | `120px`, `148px` from 1200px | Width of the fracture band |
| `--rf-split` | `42%` | Where the two realities meet |
| `--rf-echo-near` / `-far` | `5px` / `11px` | Echo displacement |
| `--rf-misregister` | `0.035em` | Layer offset in display type |

Breakpoints are 768px (the realities sit side by side) and 1200px. CSS cannot read a variable in a media
query, so `--rf-bp-*` record the values and the queries repeat them.

## Motion and focus

| Token | Value | Use |
|---|---|---|
| `--rf-motion-instant` | `90ms` | Hover |
| `--rf-motion-snap` | `180ms` | Stamp |
| `--rf-motion-shift` | `320ms` | Plane shift |
| `--rf-motion-draw` | `620ms` | Reserved for Sprint 13 line drawing |
| `--rf-ease-snap` | `cubic-bezier(0.2, 0.9, 0.1, 1)` | Displacement settling |
| `--rf-ease-stamp` | `cubic-bezier(0.5, 0, 0.1, 1)` | Verdict landing |
| `--rf-focus-inner` / `-outer` | Paper / ink | Two-ring focus, visible on every surface |

## Promoting tokens in Sprint 11

1. Import `tokens.css` from `globals.css` and put `rf` on the page you are converting.
2. Remove that page's lab-only classes from the `@source not` lines.
3. Re-run `make test-design` and the product's e2e suite. The token names do not change.
