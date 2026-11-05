import type { ReactNode } from "react";

import type { ExecutionMode, ProductOutcome, Verdict } from "@/lib/evidence-types";
import {
  MODE_LABEL,
  MODE_NOTE,
  OUTCOME_LABEL,
  OUTCOME_TONE,
  type Tone,
  VERDICT_TONE,
} from "@/lib/labels";

const TONE_TEXT: Record<Tone, string> = {
  bad: "text-bad border-bad/40 bg-bad/10",
  good: "text-good border-good/40 bg-good/10",
  warn: "text-warn border-warn/40 bg-warn/10",
  neutral: "text-muted border-line bg-raised",
  agent: "text-agent border-agent/40 bg-agent/10",
  truth: "text-truth border-truth/40 bg-truth/10",
};

export function Tag({
  tone = "neutral",
  children,
  title,
  testId,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
  testId?: string;
}) {
  return (
    <span
      title={title}
      data-testid={testId}
      className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[11px] leading-4 ${TONE_TEXT[tone]}`}
    >
      {children}
    </span>
  );
}

export function OutcomeTag({ outcome, testId }: { outcome: ProductOutcome; testId?: string }) {
  return (
    <Tag tone={OUTCOME_TONE[outcome]} testId={testId}>
      {OUTCOME_LABEL[outcome]}
    </Tag>
  );
}

export function VerdictTag({ verdict, testId }: { verdict: Verdict; testId?: string }) {
  return (
    <Tag tone={VERDICT_TONE[verdict]} testId={testId}>
      {verdict}
    </Tag>
  );
}

export function ModeTag({ mode }: { mode: ExecutionMode }) {
  return (
    <Tag tone={mode === "live" ? "truth" : "neutral"} title={MODE_NOTE[mode]} testId="mode-tag">
      {MODE_LABEL[mode]}
    </Tag>
  );
}

export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`font-mono text-[11px] uppercase tracking-[0.14em] text-faint ${className}`}>
      {children}
    </p>
  );
}

export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 break-words font-mono text-sm text-foreground">{children}</dd>
    </div>
  );
}

export function Chevron() {
  return (
    <span aria-hidden className="chevron inline-block text-faint">
      ›
    </span>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="max-h-96 overflow-auto rounded border border-line bg-background p-3 font-mono text-xs leading-5 text-foreground">
      <code>{children}</code>
    </pre>
  );
}

export function LoadingPanel({ label }: { label: string }) {
  return (
    <div role="status" className="rounded-lg border border-line bg-surface p-6">
      <p className="text-sm text-muted">{label}</p>
    </div>
  );
}
