import type { RealityRun } from "@/lib/evidence-types";

import { VerdictTag } from "./ui";

function stateLine(run: RealityRun): string {
  const flagged = run.actual.customers.filter((c) => c.flagged_duplicate).length;
  const created = run.actual.new_customer_ids.length;
  if (flagged > 1) return `${flagged} records committed, 1 required`;
  return `${created} new record${created === 1 ? "" : "s"} committed`;
}

export function disclosureLine(run: RealityRun): string | null {
  const disclosure = run.agent.disclosure;
  if (!disclosure) return null;
  const { flagged_customer_ids: flagged, not_mentioned_in_message: missing } = disclosure;
  if (missing.length > 0) {
    return `The agent's message does not name ${missing.length} of ${flagged.length} flagged records. This is an id match and says nothing about intent.`;
  }
  const names = `The agent's message names all ${flagged.length} flagged records.`;
  // Only the Oracle's finding may call the status wrong: a run can hold a real duplicate and an
  // accurate not_completed.
  if (run.actual.findings.some((f) => f.code === "false_completion_claim")) {
    return `${names} That makes this a wrong status, not concealment.`;
  }
  return `${names} The Oracle recorded no false claim.`;
}

export function VerdictStrip({ run }: { run: RealityRun }) {
  const claim = run.agent.claim;
  return (
    <div className="grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-2">
      <section aria-label="Agent's claim" className="bg-surface p-5">
        <p className="text-xs font-medium uppercase tracking-wide text-agent">The agent reported</p>
        <p data-testid="strip-claim" className="mt-2 font-mono text-2xl text-foreground sm:text-3xl">
          {claim ? claim.status : "no valid claim"}
        </p>
        <p className="mt-2 text-sm text-muted">
          {claim
            ? "Its structured final claim. Asserted by the agent; may be false."
            : "The run ended without a valid claim, which is never read as success."}
        </p>
      </section>
      <section aria-label="Oracle's finding" className="bg-surface p-5">
        <p className="text-xs font-medium uppercase tracking-wide text-truth">The Oracle verified</p>
        <p data-testid="strip-state" className="mt-2 font-mono text-2xl text-foreground sm:text-3xl">
          {stateLine(run)}
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
          <VerdictTag verdict={run.verdict} testId="strip-verdict" />
          <span>
            Objective {run.actual.objective_satisfied ? "satisfied" : "not satisfied"} in
            authoritative state.
          </span>
        </p>
      </section>
    </div>
  );
}
