# First-reader usability session

**Status: `HUMAN_TEST_NOT_RUN`.** No person unfamiliar with the project has used MOODY BLUES. Nothing in this file is a
participant's result. An LLM reading the page is not a participant and does not count.

## Running it (about 15 minutes)

- **Participant:** someone who has not seen the project. No AI background needed, and one reader is worth far more than none.
- **Setup:** the build under test, on the participant's own screen if possible. Start on the landing page, in a fresh tab.
- **Say only:** "I'm testing the site, not you. Please think aloud. I can't answer questions until the end."
- **Do not** explain the product, the Oracle or any term before task 5 is finished. If they stop for two minutes, note it and
  move on.

## Tasks

Read each one aloud, unchanged. Start a timer when you finish reading.

1. "In your own words, what does this product do?"
2. "Open an investigation that has been verified."
3. "What did the agent report?"
4. "What actually happened?"
5. "Why did the Investigator choose its next experiment?"

| Task | Pass means |
|---|---|
| 1 | Says it checks what an AI agent reports against what really happened |
| 2 | Reaches a verified investigation with no help |
| 3 | Finds `completed`, or the agent's message |
| 4 | Finds two records committed where one was required, or the Oracle's violation |
| 5 | Reaches a Decision stage and gives the model's stated reason, and knows it is the model's reasoning rather than a verdict |

## Record

| Task | Passed? | Seconds | Hesitation or wrong turn | Their words |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

Also note wrong interpretations, confusing terms, controls they missed, needless scrolling, and what they think the Oracle
is. Then ask: "What was the most confusing moment?" and "What would you call the Oracle?"

## Structured heuristic evaluation (not a substitute)

Done by the team against the five tasks on the Sprint 13 build. It finds likely problems. It does not show that anyone
understands the product.

| Task | Route | Heuristic finding | Severity | Now |
|---|---|---|---|---|
| 1 | Landing hero | The proposition is one sentence above the fold. "Oracle" appears without a definition until How it works | Minor | Open, to check with a reader |
| 2 | Hero CTA | One primary action, and it opens a verified case | None | |
| 3 | Comparison strip, or Overview | "Agent reported" is labeled and first in reading order | None | |
| 4 | Same strip | "Actual outcome" and the verdict sit beside it | None | |
| 5 | Overview, then Investigator | The reason for a step sits in the previous cycle's Decision, so a reader who opens h5 lands past it | Major | Link added from each hypothesis to the decision that led to it |
| All | Investigator | Model prose was the bulk of the page | Major | Clamped with the full text one control away |
| All | Terms | `w-e1`, `phantom_success`, `h5`, `obs_5` are exact recorded names that a new reader cannot decode | Moderate | Open: changing them would misquote the record |
