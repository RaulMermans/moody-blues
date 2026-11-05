import type { ReactNode } from "react";

import { DisplayType } from "./display-type";

export type Reality = "agent" | "actual";

const FRAME: Record<Reality, { title: string; note: string }> = {
  agent: { title: "Agent Reality", note: "What the agent was told and what it filed" },
  actual: { title: "Actual Reality", note: "What committed state recorded" },
};

/**
 * One side of a comparison. The two sides differ in shape as well as colour: Agent Reality has a
 * broken, offset edge, and Actual Reality is held by a heavy square rule.
 */
export function RealityFrame({
  reality,
  children,
  note,
  className = "",
}: {
  reality: Reality;
  children: ReactNode;
  note?: string;
  className?: string;
}) {
  const frame = FRAME[reality];
  return (
    <section
      aria-label={frame.title}
      data-reality={reality}
      data-testid={`frame-${reality}`}
      className={`rf-frame ${className}`}
    >
      <header className="rf-frame-head">
        <DisplayType
          as="h2"
          text={frame.title}
          effect={reality === "agent" ? "misregister" : "plain"}
          className="rf-frame-title"
        />
        <p className="rf-micro">{note ?? frame.note}</p>
      </header>
      {children}
    </section>
  );
}
