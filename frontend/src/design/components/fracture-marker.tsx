import type { Discrepancy } from "@/lib/evidence-types";
import { DISCREPANCY_LABEL } from "@/lib/labels";

const SOURCE_LABEL: Record<Discrepancy["source"], string> = {
  oracle: "Oracle",
  fault_event: "Fault record",
};

/**
 * One verified point of discrepancy. It takes a recorded `Discrepancy` and detects nothing itself:
 * without a record there is no marker. Sprint 11 can place these on the timeline by `call_seq`.
 *
 * `tone` is the caller's statement of what the Oracle found. A faulty delivery in a run that ended
 * correct is real, but it is `distortion`, not `fracture`: it must not look like a failure.
 */
export function FractureMarker({
  discrepancy,
  tone,
}: {
  discrepancy: Discrepancy;
  tone: "fracture" | "distortion";
}) {
  const { kind, call_seq: call, agent_saw: saw, actually, source } = discrepancy;
  return (
    <article className="rf-marker" data-kind={kind} data-tone={tone} data-testid="fracture-marker">
      <header className="rf-marker-head">
        <span aria-hidden className="rf-marker-notch" />
        <h3 className="rf-marker-kind">{DISCREPANCY_LABEL[kind]}</h3>
        <p className="rf-micro">
          {call === null ? "Whole run" : `Call ${call}`} · {SOURCE_LABEL[source]}
        </p>
      </header>
      <dl className="rf-marker-body">
        <div>
          <dt className="rf-micro rf-marker-agent">Agent saw</dt>
          <dd>{saw}</dd>
        </div>
        <div>
          <dt className="rf-micro rf-marker-actual">Actually</dt>
          <dd>{actually}</dd>
        </div>
      </dl>
    </article>
  );
}
