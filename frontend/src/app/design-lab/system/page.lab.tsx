import { DisplayType } from "@/design/components/display-type";
import { DIVERGENCE_LABEL, DivergenceDivider } from "@/design/components/divergence-divider";
import { OracleSeal } from "@/design/components/oracle-seal";
import { RealityEcho } from "@/design/components/reality-echo";
import type { DivergenceState, SealState } from "@/design/model";

// Specimens of what each primitive can draw. None of this is evidence, and the page says so.
const SEALS: SealState[] = [
  { kind: "verdict", verdict: "PASS", qualifier: null },
  { kind: "verdict", verdict: "PASS", qualifier: "State correct, but no valid claim. Not a success." },
  { kind: "verdict", verdict: "VIOLATION", qualifier: null },
  { kind: "verdict", verdict: "INCONCLUSIVE", qualifier: null },
  { kind: "incomplete", outcome: "failed" },
  { kind: "incomplete", outcome: "cancelled" },
  { kind: "incomplete", outcome: "budget_exhausted" },
  { kind: "unverified", reason: "no_target_run" },
  { kind: "unverified", reason: "outcome_uncertain" },
  { kind: "unverified", reason: "integrity_failed" },
];

const SWATCHES = [
  ["--rf-surface-base", "Ground"],
  ["--rf-surface-raised", "Raised plane"],
  ["--rf-surface-high", "High plane"],
  ["--rf-agent", "Agent Reality identity"],
  ["--rf-actual", "Actual Reality identity"],
  ["--rf-divergence", "Divergence"],
  ["--rf-oracle-surface", "Oracle paper"],
  ["--rf-status-pass", "Status: pass"],
  ["--rf-status-violation", "Status: violation"],
  ["--rf-status-inconclusive", "Status: inconclusive"],
  ["--rf-status-incomplete", "Status: incomplete"],
  ["--rf-status-unverified", "Status: unverified"],
] as const;

const DIVIDERS = Object.keys(DIVERGENCE_LABEL) as DivergenceState[];

export default function SystemPage() {
  return (
    <main className="rf-page">
      <header className="flex flex-col gap-2">
        <DisplayType as="h1" text="System" effect="misregister" className="rf-page-title" />
        <p className="rf-copy">Specimens only. Nothing on this page is evidence or describes a run.</p>
      </header>

      <section className="rf-spec-section" aria-labelledby="colour">
        <h2 id="colour" className="rf-section-title">Colour tokens</h2>
        <div className="rf-spec-grid">
          {SWATCHES.map(([token, name]) => (
            <div key={token} className="rf-swatch">
              <div className="rf-swatch-chip" style={{ background: `var(${token})` }} />
              <span>{name}</span>
              <span className="text-rf-muted">{token}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rf-spec-section" aria-labelledby="type">
        <h2 id="type" className="rf-section-title">Editorial type</h2>
        <DisplayType text="Plain display" className="rf-page-title" />
        <DisplayType text="Sliced display" effect="slice" className="rf-page-title" />
        <DisplayType text="Misregistered" effect="misregister" className="rf-page-title" />
        <p className="font-mono text-sm">cus_00000000 · specimen id · technical type is never treated</p>
      </section>

      <section className="rf-spec-section" aria-labelledby="seals">
        <h2 id="seals" className="rf-section-title">OracleSeal states</h2>
        <div className="rf-spec-grid">
          {SEALS.map((state, index) => (
            <div key={index}>
              <OracleSeal state={state} size="sm" />
            </div>
          ))}
        </div>
      </section>

      <section className="rf-spec-section" aria-labelledby="dividers">
        <h2 id="dividers" className="rf-section-title">DivergenceDivider states</h2>
        <div className="rf-spec-grid">
          {DIVIDERS.map((state) => (
            <div key={state} className="rf-divider-specimen">
              <DivergenceDivider state={state} />
            </div>
          ))}
        </div>
      </section>

      <section className="rf-spec-section" aria-labelledby="echo">
        <h2 id="echo" className="rf-section-title">RealityEcho</h2>
        <div className="max-w-sm">
          <RealityEcho>
            <div className="rf-slip">
              <p className="rf-micro">Decorative outlines, never data</p>
            </div>
          </RealityEcho>
        </div>
      </section>
    </main>
  );
}
