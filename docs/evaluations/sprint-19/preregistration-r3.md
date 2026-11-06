# Sprint 19 preregistration, revision 3

Written after the revision 2 pilot and before any main trial. Revisions 1 and 2 stand. Frozen form: [spec-r3.json](spec-r3.json) with
[plan-r3.json](plan-r3.json). Everything in [revision 1](preregistration.md) and [revision 2](preregistration-r2.md) carries over except one
number.

**Found.** With the wording fixed, the revision 2 pilot had no rejected proposals. All six experiments ran in both adaptive trials, but
each then ended `failed (prompt_limit)`: the closing prompt, with six observations, is about 25,700 characters against a limit of 24,000, so
the Investigator could never conclude. Prompts measured 7,234 to 22,641 characters across calls 1 to 6, growing about 3,000 per experiment.

**Correction.** `max_prompt_chars` goes from 24,000 to 28,000. The local provider's own limits are unchanged and still refuse rather than
truncate.

**Seen and left alone.** In both trials the model never filled `previous_status`, so it assessed no hypothesis, and every hypothesis after
the first few is a near copy. That is model behavior and is what the benchmark should measure, so nothing was changed to prompt it.
