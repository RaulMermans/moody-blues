# ADR 0007: Investigation Explorer

- **Status:** accepted (Sprint 7, 2026-11-05)
- **Context:** the engine and its evidence existed, but only the source code could explain them. A judge
  needs to see a real investigation in seconds, and a public page must not become a paid inference
  endpoint or a way to read raw traces.

## Decisions

1. **One projection, used for recorded and live evidence.** A pure function turns verified records into
   a bundle, and everything public reads bundles. *Rejected:* an API reading raw records per request,
   which would make the sanitizer the only thing between the public and raw traces.
2. **Committed bundles, not fixtures.** Recorded runs are exported from real records, pinned by hash,
   and rebuildable byte for byte. *Rejected:* handwritten demo data, which would be fabricated evidence.
3. **Refuse, never redact.** A forbidden string stops the export. *Rejected:* redaction, which edits
   evidence silently.
4. **The timeline is built from journal records.** Each entry names one record and its hash.
   *Rejected:* deriving it from the final report, which would be a story about the run.
5. **Progress comes from tailing the journal.** The Investigator did not change. *Rejected:* callbacks
   in the workflow, which would widen a trusted component for a display concern.
6. **One in-process worker, state on disk.** One investigation runs at a time anyway, under an existing
   file lock. *Rejected:* Redis or Celery, which add infrastructure and solve no problem this has.
7. **Refused, not queued.** A second job gets 409. *Rejected:* a queue, which would turn a double click
   into a second paid run.
8. **A shared operator token.** Sent only server to server, held in an httpOnly SameSite=Strict cookie.
   *Rejected:* an identity platform, out of scope for one operator.
9. **Rehearsal missions.** The real pipeline with a labeled fixture and a reference script, so the
   lifecycle can be tested for free and the product can be shown without spending. *Rejected:* testing
   the job path only with doubles, which would leave Docker and the Oracle unproven in that path.
10. **The API cannot change a limit.** Spending needs an environment change by the owner.

## Consequences

- A bundle is a snapshot. A change to the projection needs a re-export, and hashes change.
- In-process jobs tie a run to one server process. This suits a single VM. More than one replica would
  need a shared lock, which `exclusive` is not.
- A token is shared, so actions are not attributed to a person.
