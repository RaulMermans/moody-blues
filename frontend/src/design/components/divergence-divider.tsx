import type { CSSProperties, ReactNode } from "react";

import type { DivergenceState } from "../model";

// One crack, as [horizontal offset in px from the split, height in %]. The plane's clip path and the
// drawn line both read this, so they cannot drift apart.
const CRACK: [number, number][] = [
  [14, 0], [-8, 9], [22, 17], [-26, 27], [6, 35], [-14, 44],
  [34, 53], [-4, 62], [-30, 71], [12, 80], [-10, 90], [18, 100],
];

function crackPlane(scale: number): string {
  const edge = CRACK.map(([dx, y]) => `calc(var(--rf-split) + ${dx * scale}px) ${y}%`);
  return `polygon(0 0, ${edge.join(", ")}, 0 100%)`;
}

export const DIVERGENCE_LABEL: Record<DivergenceState, string> = {
  violation: "Divergence",
  delivery: "Distorted, state held",
  unresolved: "Unresolved",
  none: "No divergence",
};

/** The field two realities sit in. Only a recorded violation cuts the planes along the crack. */
export function DivergenceField({
  state,
  children,
  scale = 1,
  className = "",
}: {
  state: DivergenceState;
  children: ReactNode;
  scale?: number;
  className?: string;
}) {
  const plane: CSSProperties = state === "violation" ? { clipPath: crackPlane(scale) } : {};
  return (
    <div className={`rf-field ${className}`} data-divergence={state} data-testid="divergence-field">
      <div aria-hidden data-rf-decorative className="rf-plane rf-plane-actual" />
      <div aria-hidden data-rf-decorative className="rf-plane rf-plane-agent" style={plane} />
      {children}
    </div>
  );
}

function CrackLine({ points, className }: { points: string; className: string }) {
  return <polyline points={points} className={className} vectorEffect="non-scaling-stroke" fill="none" />;
}

/** The drawn line. Only `violation` is jagged; every other state is one straight line. */
export function Crack({
  state,
  orientation,
  scale = 1,
  className = "",
}: {
  state: DivergenceState;
  orientation: "vertical" | "horizontal";
  scale?: number;
  className?: string;
}) {
  const vertical = orientation === "vertical";
  const points = CRACK.map(([dx, y]) => (vertical ? `${dx * scale},${y}` : `${y},${dx * 0.5 + 20}`)).join(" ");
  return (
    <svg
      aria-hidden
      data-rf-decorative
      className={`rf-crack rf-crack-${orientation} ${className}`}
      viewBox={vertical ? `${-60 * scale} 0 ${120 * scale} 100` : "0 0 100 40"}
      preserveAspectRatio="none"
    >
      {state === "violation" ? (
        <>
          <CrackLine points={points} className="rf-crack-ghost-agent" />
          <CrackLine points={points} className="rf-crack-ghost-actual" />
          <CrackLine points={points} className="rf-crack-main" />
        </>
      ) : vertical ? (
        <line x1="0" y1="0" x2="0" y2="100" className="rf-crack-straight" vectorEffect="non-scaling-stroke" />
      ) : (
        <line x1="0" y1="20" x2="100" y2="20" className="rf-crack-straight" vectorEffect="non-scaling-stroke" />
      )}
    </svg>
  );
}

/**
 * The boundary itself. It is legible without motion, and its label says what the line means. A clean
 * case gets a clean line: `none` is one straight hairline with no coral anywhere.
 */
export function DivergenceDivider({
  state,
  detail,
  scale = 1,
}: {
  state: DivergenceState;
  detail?: ReactNode;
  scale?: number;
}) {
  return (
    <div className="rf-divider" data-state={state} data-testid="divergence-divider">
      <Crack state={state} orientation="vertical" scale={scale} />
      <Crack state={state} orientation="horizontal" />
      <div className="rf-divider-label">
        <p className="rf-divider-title" data-testid="divergence-label">
          {DIVERGENCE_LABEL[state]}
        </p>
        {detail ? <div className="rf-divider-detail">{detail}</div> : null}
      </div>
    </div>
  );
}
