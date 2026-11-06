# Design tokens

Source: [`frontend/src/design/styles/tokens.css`](../../frontend/src/design/styles/tokens.css), on `:root`, so every product screen reads them.

Components read only the semantic tier. `--rf-p-*` primitives stay inside that file.

## Colour

Neutral first. Colour marks a word or a rule, and never fills a panel. Reality identity says whose reality
something is, never good or bad. Status says what was found and never marks a reality. Oracle paper is neither:
it is the authority, and it appears once per screen.

| Token | Value | Use |
|---|---|---|
| `--rf-surface-base` | `#0e0e10` | Ground |
| `--rf-surface-raised` | `#161618` | Record slabs, hovered rows |
| `--rf-surface-high` | `#1f1f22` | The selected run |
| `--rf-rule` | `#303034` | Hairlines |
| `--rf-text` | `#f1ede4` | Primary text, warm paper |
| `--rf-text-muted` | `#b5b0a6` | Secondary text |
| `--rf-text-faint` | `#99948b` | Tertiary text and labels |
| `--rf-agent` | `#b6b1dc` | Agent-reported identity: labels and one dashed rule |
| `--rf-actual` | `#e2c9a0` | Authoritative identity: labels and one solid rule |
| `--rf-oracle-surface` | `#f1ede4` | The Oracle's paper |
| `--rf-oracle-ink` | `#0e0e10` | Ink on paper |
| `--rf-oracle-rule` | `#cfc9bd` | Rules on paper |
| `--rf-divergence` | `#f0705a` | Seam breaks and the headline tick, in a VIOLATION only |
| `--rf-status-pass` | `#9ccbb0` | PASS |
| `--rf-status-violation` | `#f0705a` | VIOLATION |
| `--rf-status-inconclusive` | `#d8cf8f` | INCONCLUSIVE |
| `--rf-status-incomplete` | `#b5b0a6` | Failed, cancelled, budget exhausted |
| `--rf-status-unverified` | `#99948b` | No verdict exists |
| `--rf-status-ink` | `#0e0e10` | Ink on a status tile |

Sprint 11 removed `--rf-agent-plane` and `--rf-actual-plane`: a reality no longer has a colour territory. It also
desaturated every accent.

### Product tokens

Inside `.rf`, the product's names are re-pointed, so `Tag`, `Code` and `VerdictTag` take the theme unchanged:

| Product token | Becomes |
|---|---|
| `--background`, `--surface`, `--surface-raised`, `--line` | Surface and rule tokens |
| `--foreground`, `--muted`, `--faint` | Text tokens |
| `--agent` | `--rf-agent` |
| `--truth` | `--rf-actual`. The product's name for the authoritative side |
| `--good`, `--bad`, `--warn` | Status tokens |

## Typography

| Token | Value | Use |
|---|---|---|
| `--rf-font-display` | Archivo, then Arial Narrow, Helvetica Neue | Headlines and section titles |
| `--rf-font-text` | Archivo, then system sans | Reading text |
| `--rf-font-tech` | System monospace | Ids, statuses, tool calls, JSON, labels |
| `--rf-type-poster` | `clamp(2.625rem, 6.1vw, 5.5rem)` | The landing statement, two lines at desktop |
| `--rf-type-headline` | `clamp(1.875rem, 4.9vw, 4.25rem)` | A run's headline |
| `--rf-type-title` | `clamp(1.375rem, 2vw, 1.75rem)` | Section titles |
| `--rf-type-value` | `clamp(1.25rem, 1.8vw, 1.5rem)` | A status or a recorded value |
| `--rf-type-lead` | `clamp(1.0625rem, 1.3vw, 1.25rem)` | Lead text |
| `--rf-type-body` | `0.9375rem` | Reading text |
| `--rf-type-data` | `0.8125rem` | Technical values |
| `--rf-type-micro` | `0.6875rem` | Uppercase labels |
| `--rf-width-display` | `82%` | Archivo's width for headlines |
| `--rf-tracking-micro` | `0.14em` | Label tracking |

Archivo is SIL OFL 1.1, committed as one 90 KB Latin file with width and weight axes
([licence](../../frontend/src/design/fonts/OFL.txt)). It is now on every page, loaded from the app's own origin:
no package and no remote asset. Technical type stays on system fonts, so evidence never waits for a font.

## Spacing and geometry

| Token | Value | Use |
|---|---|---|
| `--rf-space-1` … `--rf-space-16` | `0.25rem` … `4rem` | 4px base spacing |
| `--rf-measure` | `64ch` | Reading width |
| `--rf-hit` | `2.75rem` | The smallest primary control: 44px |
| `--rf-seam-width` | `2.5rem` | The column the seam sits in |

Everything is square: the product no longer has rounded corners. The breakpoints are 720px (rows go side by
side) and 1100px (the strip becomes one line). CSS cannot read a variable in a media query.

## Displacement

The whole distortion budget. A use outside [these conditions](direction.md#the-distortion-budget) is a defect.

| Token | Value | Moves |
|---|---|---|
| `--rf-slip-seam` | `7px` | A broken seam |
| `--rf-slip-record` | `1.25rem` | The extra record of a duplicate (`0.75rem` on a phone) |
| `--rf-slip-headline` | `0.42em` | The second headline line |

Setting all three to zero must leave the page reading the same.

## Motion and focus

| Token | Value | Use |
|---|---|---|
| `--rf-motion-instant` | `120ms` | Hover backgrounds. The only motion in the system |
| `--rf-focus-inner` / `-outer` | Paper / ink | Two-ring focus, visible on every surface |

Sprint 10's plane, stamp and draw tokens are gone with the animations that used them. Sprint 13 owns motion.
