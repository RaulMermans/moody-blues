import Link from "next/link";
import type { ReactNode } from "react";

import type { StepKind, StepLink, StoryStep } from "../sequence";

// Line drawings at one weight, inherited colour. Each names a kind of event, and none decorates.
const ICON: Record<StepKind, ReactNode> = {
  hypothesis: <path d="M9.5 9.2a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8M12 16.5v.1M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z" />,
  attempt: <path d="M4 12h15M13 6l6 6-6 6" />,
  fault: <path d="M12 4 3 20h18L12 4ZM12 10v5M12 17.5v.1" />,
  actual: <path d="M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Zm0 0v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />,
  response: <path d="M4 12a8 8 0 0 1 13.7-5.7L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.7L4 15.5M4 20v-4.5h4.5" />,
  verdict: <path d="M12 3 5 6v5c0 4.4 2.9 8.2 7 10 4.1-1.8 7-5.6 7-10V6l-7-3ZM8.8 12l2.2 2.2 4.2-4.4" />,
  decision: <path d="M6 4v8a4 4 0 0 0 4 4h8M14 12l4 4-4 4" />,
};

function Icon({ kind }: { kind: StepKind }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {ICON[kind]}
    </svg>
  );
}

/** A run's milestones, in recorded order. Reads the same with every colour and icon removed. */
export function StorySequence({
  steps,
  hrefFor,
}: {
  steps: StoryStep[];
  hrefFor: (link: StepLink) => string;
}) {
  return (
    <ol className="rf-story" data-testid="story" data-count={steps.length}>
      {steps.map((step, index) => (
        <li key={step.kind} data-kind={step.kind} data-testid={`story-${step.kind}`}>
          <span className="rf-story-mark">
            <Icon kind={step.kind} />
          </span>
          <div className="rf-story-text">
            <h3>
              <span className="rf-story-index">{index + 1}</span> {step.label}
            </h3>
            <p>{step.detail}</p>
            {step.link ? (
              <Link href={hrefFor(step.link)} className="rf-story-link">
                {step.linkLabel}
              </Link>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
