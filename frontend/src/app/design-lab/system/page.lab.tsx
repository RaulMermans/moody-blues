import { DivergenceDivider } from "@/design/components/divergence-divider";
import { Headline } from "@/design/components/headline";
import { OracleSeal } from "@/design/components/oracle-seal";
import type { Relation, SealState, SeamTone } from "@/design/model";

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
  ["--rf-agent", "Agent reality identity"],
  ["--rf-actual", "Authoritative reality identity"],
  ["--rf-divergence", "Divergence"],
  ["--rf-oracle-surface", "Oracle paper"],
  ["--rf-status-pass", "Status: pass"],
  ["--rf-status-violation", "Status: violation"],
  ["--rf-status-inconclusive", "Status: inconclusive"],
  ["--rf-status-incomplete", "Status: incomplete"],
  ["--rf-status-unverified", "Status: unverified"],
] as const;

const SEAMS: [Relation, SeamTone, string][] = [
  ["equal", "steady", "Agree"],
  ["unknown", "steady", "Nothing to compare"],
  ["differs", "distortion", "Differs, no violation"],
  ["differs", "break", "Differs, Oracle VIOLATION"],
];

export default function SystemPage() {
  return (
    <main className="rf-lab-page">
      <header>
        <h1 className="rf-page-title">System</h1>
        <p className="rf-body">Specimens only. Nothing on this page is evidence or describes a run.</p>
      </header>

      <section aria-labelledby="colour">
        <h2 id="colour" className="rf-section-title">Colour tokens</h2>
        <div className="rf-spec-grid">
          {SWATCHES.map(([token, name]) => (
            <div key={token} className="rf-swatch">
              <div className="rf-swatch-chip" style={{ background: `var(${token})` }} />
              <span>{name}</span>
              <span>{token}</span>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="type">
        <h2 id="type" className="rf-section-title">Headline</h2>
        <Headline as="p" first="First line, in register." second="Second line, in register." />
        <Headline as="p" first="First line." second="Second line, out of register." outOfRegister />
        <p className="rf-data">cus_00000000 · specimen id · technical type is never treated</p>
      </section>

      <section aria-labelledby="seals">
        <h2 id="seals" className="rf-section-title">OracleSeal states</h2>
        <div className="rf-spec-grid">
          {SEALS.map((state, index) => (
            <div key={index}>
              <OracleSeal state={state} size="sm" />
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="seams">
        <h2 id="seams" className="rf-section-title">DivergenceDivider states</h2>
        <div className="rf-spec-grid">
          {SEAMS.map(([relation, tone, label]) => (
            <div key={label} className="rf-stack">
              <p className="rf-label">{label}</p>
              <div className="h-24 w-10">
                <DivergenceDivider relation={relation} tone={tone} />
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
