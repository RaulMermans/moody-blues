import type { ReactNode } from "react";

import { MODE_LABEL } from "@/lib/labels";
import type { TestEntry } from "@/lib/test-catalog";

import { Tag } from "./ui";

/** One runnable test, as facts. Used by the public catalog and the signed-in console alike. */
export function TestCard({
  entry,
  availability,
  maxExperiments,
  available,
  blocked = false,
  selected = false,
  children,
}: {
  entry: TestEntry;
  availability: string;
  maxExperiments?: number;
  available?: boolean;
  blocked?: boolean;
  selected?: boolean;
  children?: ReactNode;
}) {
  const id = entry.missionId;
  return (
    <article
      data-testid={`mission-${id}`}
      data-available={available}
      data-selected={selected}
      className="rf-test w-full"
    >
      <span className="flex">
        <Tag tone={entry.mode === "live" ? "warn" : "neutral"}>{MODE_LABEL[entry.mode]}</Tag>
      </span>
      <h2>{entry.label}</h2>
      <p className="rf-body">{entry.summary}</p>
      <dl>
        <dt>Target</dt>
        <dd data-testid={`target-${id}`}>{entry.target}</dd>
        <dt>Scenario</dt>
        <dd>{entry.scenario}</dd>
        <dt>Cost</dt>
        <dd data-testid={`cost-${id}`}>{entry.cost}</dd>
        <dt>AI models</dt>
        <dd data-testid={`inference-${id}`}>{entry.inference}</dd>
        <dt>Experiments</dt>
        <dd data-testid={`experiments-${id}`}>Up to {maxExperiments ?? entry.maxExperiments}</dd>
        <dt>Availability</dt>
        <dd data-testid={blocked ? `blocked-${id}` : `availability-${id}`} data-blocked={blocked || undefined}>
          {availability}
        </dd>
      </dl>
      {children ? <div className="rf-test-action">{children}</div> : null}
    </article>
  );
}
