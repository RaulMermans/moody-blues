# Sprint 19 preregistration, revision 4

Written after the revision 3 pilot and before any main trial. Revisions 1 to 3 stand. Frozen form: [spec-r4.json](spec-r4.json) with
[plan-r4.json](plan-r4.json).

**Found.** One of two adaptive pilot trials ended `failed (investigator_provider_error)` on its closing call. The request was 30,835 bytes
before encoding, and the local provider refused it, correctly, because it could not be shown to fit the 12,288-token context with room to
answer. Widening that limit would weaken a control to suit a study, so it stays as it is.

**Correction.** A menu prompt is now compact JSON, with the same content and order. Prompts outside menu mode are byte for byte unchanged,
which `make eval-verify` and the fingerprint tests hold to.

**Seen and left alone.** Asked to list claimed findings, the model wrote ids that are not experiments, which the checks record as
`missing_evidence_reference`. That is model behavior.
