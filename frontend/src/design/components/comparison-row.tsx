import type { ReactNode } from "react";

import type { Relation, SeamTone } from "../model";

import { DivergenceDivider } from "./divergence-divider";

/**
 * One event seen from both sides. A row is the unit of comparison, so a screen reader and a phone
 * both meet the two sides together, each under its own label, rather than one whole column at a time.
 */
export function ComparisonRow({
  title,
  agentLabel,
  actualLabel,
  agent,
  actual,
  relation,
  tone,
  id,
  agentTestId,
}: {
  title: string;
  agentLabel: string;
  actualLabel: string;
  agent: ReactNode;
  actual: ReactNode;
  relation: Relation;
  tone: SeamTone;
  id?: string;
  agentTestId?: string;
}) {
  return (
    <section aria-label={title} className="rf-row" id={id} data-tone={tone} data-testid="comparison-row">
      <div className="rf-cell" data-reality="agent" data-testid={agentTestId}>
        <p className="rf-label">{agentLabel}</p>
        {agent}
      </div>
      <DivergenceDivider relation={relation} tone={tone} />
      <div className="rf-cell" data-reality="actual">
        <p className="rf-label">{actualLabel}</p>
        {actual}
      </div>
    </section>
  );
}
