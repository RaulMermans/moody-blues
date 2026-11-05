# Product experience

_Sprint 7. Decisions are in [ADR 0007](../adr/0007-investigation-explorer.md), contracts in
[evidence-api.md](evidence-api.md)._

MOODY BLUES should answer eight questions without its source code: what agent was tested, what task it
had, what conditions changed, what it observed, what actually happened, whether a violation was verified,
why the next experiment was chosen, and what evidence supports the conclusion.

## Views

| View | Route | Answers |
|---|---|---|
| Overview | `/` | What this is, one claim against one verified state, every published case, the registered negative result |
| Reality Comparison | `/investigations/{id}` | What the agent was told against what authoritative state recorded, one row per tool call, then the claim beside the Oracle |
| Timeline | `?view=timeline` | The ordered journal, key steps first, every record available, each entry naming its source hash |
| Investigator | `?view=investigator` | Hypotheses, objectives, generated Python, observations, assessments, claims checked against the Oracle |
| Operator | `/operator` | The ledger, the mission catalog, and progress of a running job |

## The signature comparison

The Reality Comparison aligns rows by call number, so a reader sees delivery and truth for the same
moment. The left column is what the gateway delivered and the agent's own words. The right column comes
from the gateway's fault events and committed changes. The bottom row sets the structured claim and its
free-text message beside the Oracle's verdict and findings.

Disclosure is shown, not judged. Where the Oracle flags duplicates, trusted code checks whether the
message names those ids. That is an id match, so the page says "a wrong status, not concealment" only
when every flagged id appears, and never infers intent.

## Trust is visible

- **Colour is authorship.** Violet is what the agent saw or said. Cyan is authoritative state. Red is
  reserved for a verified violation or a distorted response. Nothing else uses them.
- **Every timeline entry names its author**, so a model's hypothesis cannot look like an Oracle result.
- **A case note is labeled**, because a person wrote it. Everything else is projected from records.
- **Recorded, live and rehearsal** are separate labels, and each run also states its target: a live
  model, a reference script or an offline fixture.
- **Adaptation is labeled only as far as shown.** "Cited prior observations" says the model named earlier
  results. The page adds that this is not proof they caused the choice.

## Honest states

Loading text appears only while a real request is pending. A refused record says it failed verification
and shows no result. A missing or unreachable record says so and implies nothing. An empty list is stated
as empty. A run with no valid claim says so, and never reads as success.

## Design

Dark, high contrast, system fonts so builds need no network. Monospace is used for evidence and ids,
proportional type for explanation. There are no charts, because the data has no shape a chart would
clarify. Native `<details>` gives keyboard drill-down with no script. Layouts collapse to one column,
with wide tables scrolling inside their own box, and no view scrolls sideways at 390 px.
