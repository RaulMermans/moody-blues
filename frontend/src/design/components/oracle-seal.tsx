import { OUTCOME_LABEL } from "@/lib/labels";

import type { SealState } from "../model";

type Face = {
  mark: string;
  label: string;
  note: string;
  tone: "pass" | "violation" | "inconclusive" | "incomplete" | "unverified";
};

const UNVERIFIED_NOTE: Record<Extract<SealState, { kind: "unverified" }>["reason"], string> = {
  no_target_run: "No target run took place, so there is nothing to verify.",
  outcome_uncertain: "A target run did not report back. Its outcome is unknown.",
  integrity_failed: "This record failed its integrity check and is not a result.",
};

function faceOf(state: SealState): Face {
  if (state.kind === "incomplete") {
    return {
      mark: "—",
      label: OUTCOME_LABEL[state.outcome],
      note: "The run did not finish. The Oracle returned no verdict.",
      tone: "incomplete",
    };
  }
  if (state.kind === "unverified") {
    return { mark: "∅", label: "Unverified", note: UNVERIFIED_NOTE[state.reason], tone: "unverified" };
  }
  if (state.verdict === "PASS") {
    return { mark: "✓", label: "PASS", note: "Truth Oracle verdict", tone: "pass" };
  }
  if (state.verdict === "VIOLATION") {
    return { mark: "✕", label: "VIOLATION", note: "Truth Oracle verdict", tone: "violation" };
  }
  return { mark: "?", label: "INCONCLUSIVE", note: "Truth Oracle verdict", tone: "inconclusive" };
}

/**
 * The verdict. It is never rotated, offset, echoed or distorted: it is the one object in the system
 * that stays still. `incomplete` and `unverified` render hollow, because no verdict exists.
 */
export function OracleSeal({ state, size = "lg" }: { state: SealState; size?: "sm" | "lg" }) {
  const face = faceOf(state);
  return (
    <div
      className="rf-seal"
      data-tone={face.tone}
      data-size={size}
      data-kind={state.kind}
      data-testid="oracle-seal"
    >
      <span aria-hidden className="rf-seal-mark">
        {face.mark}
      </span>
      <span className="rf-seal-text">
        <span className="rf-seal-label" data-testid="oracle-seal-label">
          {face.label}
        </span>
        <span className="rf-seal-note">{face.note}</span>
        {state.kind === "verdict" && state.qualifier ? (
          <span className="rf-seal-note" data-testid="oracle-seal-qualifier">
            {state.qualifier}
          </span>
        ) : null}
      </span>
    </div>
  );
}
