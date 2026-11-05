import type { ReactNode } from "react";

/**
 * Displaced, empty outlines behind an object. The outlines carry no text and no data, so an echo can
 * never read as a second record. Do not place one around anything that represents a count of records:
 * inside Actual Reality, every object drawn is a real row.
 */
export function RealityEcho({
  children,
  layers = 2,
  className = "",
}: {
  children: ReactNode;
  layers?: 1 | 2;
  className?: string;
}) {
  return (
    <div className={`rf-echo ${className}`}>
      <span aria-hidden data-rf-decorative className="rf-echo-outline rf-echo-near" />
      {layers === 2 ? <span aria-hidden data-rf-decorative className="rf-echo-outline rf-echo-far" /> : null}
      <div className="rf-echo-subject">{children}</div>
    </div>
  );
}
