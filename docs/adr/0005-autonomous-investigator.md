# ADR 0005: Single-agent Investigator inside a deterministic workflow

- **Status:** accepted (Sprint 5, 2026-11-04)
- **Context:** Experiments can now be written by a model. That code and that model's reasoning
  are untrusted, yet the system must let them steer an investigation and must still report only
  what the Oracle established.

## Decisions

1. **One model, deterministic everything else.** The model forms hypotheses and writes programs.
   Trusted code holds limits, validation, execution, evidence and findings. *Rejected:* manager,
   critic or researcher agents, which add cost and failure modes before a single agent has shown
   value.
2. **Stateless prompts.** Each call is rebuilt from typed state, with no conversation history.
   Memory is bounded and inspectable, and a paired test can show what differed between two calls.
3. **Observations are built from token-validated fields.** Every string in an observation is a
   `SafeToken`, which cannot hold a sentence, so target claim messages and sandbox summaries are
   unrepresentable there. They survive as a hash and a length. This also covers routes that are
   easy to miss: `ProtocolRejection.detail` can echo untrusted field names, and
   `claim.customer_id` is model-written text. *Rejected:* delimiting untrusted text and asking the
   model to ignore it, which is a request rather than a control.
4. **Generated Python never touches the host process, not even to parse.** Syntax errors are found
   by running in the sandbox. *Rejected:* `ast.parse` on the host: small risk, no need.
5. **Pinned image, approved by a preflight.** `approved_for_generated_code` is true only for a
   digest-pinned image that is never pulled, and the coordinator refuses generated code otherwise.
6. **Rejection stays terminal per experiment; refinement is per investigation.** A replacement is a
   new proposal, allowed once, and only if the failed one provably ran no target. This is the
   deliberate change ADR 0004 anticipated. Diagnostics are enum codes, a line number and known field
   names, so they give little of a validator-probing oracle.
7. **Flat tool schema.** Nested objects came back from `glm-5.3` as JSON-encoded strings. Decoding
   them would repair untrusted output, so the schema is flat and trusted code builds the contracts.
8. **`stale_read`, the one new distortion.** Every live run relied on verification, so a fault
   aimed at verification was the only one likely to teach anything new. It changes only a read's
   response; committed state and the Oracle are unaffected.
9. **Findings separate three things:** what the Oracle confirmed, whether any fault reached the
   target, and whether it reproduced. A live run showed why: a model blamed injected faults for a
   violation in a run where none fired.
10. **One ledger, scoped.** Model calls and target runs reserve under one investigation scope in
    the existing ledger file. A restart cannot reset it.
11. **Adaptation is measured by counterfactual, not narrative.** See
    [the methodology](../evaluations/methodology.md).

## Consequences

- The existing coordinator is unchanged in structure. It gains `allowed_scenarios`, authorship and
  source preservation. Evidence stays schema version 1, and new fields have defaults.
- The Investigator cannot see tool arguments, rows or claim text, so some real behavior is invisible
  to it unless its program inspects structured detail.
- Containers still share a kernel; gVisor is not available on this host.
