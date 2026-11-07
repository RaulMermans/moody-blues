# Adding a world

For contributors. **This is an extension guide, not a compatibility guarantee.** `mb-world/1` is an alpha contract and may
change without notice. There is no plugin ABI.

A world is trusted project code, reviewed and listed by hand in `backend/moody_blues/world/registry.py`. Worlds are never
loaded dynamically or uploaded, and nothing untrusted can select one. Writing one means changing this repository, through a
pull request.

The full contract and the eight steps are in [world plugins](architecture/world-plugins.md#adding-a-world). Job Queue World is
the worked example: `backend/moody_blues/world/jobqueue/`.

Three rules decide whether a world belongs here:

1. **A plugin supplies facts, never policy.** No limits, budgets, sandbox settings, evidence rules or verdict meanings.
2. **Verification is deterministic** and reads committed state through `ReadOnlyWorldView`, never delivered responses,
   fault events or an agent's word. Verdicts mean what `derive_verdict` says, in every world.
3. **Faults go through the shared pipeline** and touch only the targeted call's own staged write.

Worlds are out of scope for v0.1.0. Please open an issue before starting one.
