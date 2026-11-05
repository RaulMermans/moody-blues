import Link from "next/link";

import { DisplayType } from "@/design/components/display-type";

const ENTRIES = [
  ["/design-lab/landing", "Landing prototype", "What the agent believed. What actually happened."],
  ["/design-lab/comparison", "Reality Comparison prototype", "All five recorded cases, through the new language."],
  ["/design-lab/system", "System", "Tokens, primitives and every seal and divider state."],
  ["/design-lab/studies/a", "Study A: Reality Fracture", "Selected as the primary identity."],
  ["/design-lab/studies/b", "Study B: Mirror Corruption", "Explored, not carried forward."],
  ["/design-lab/studies/c", "Study C: Forensic Brutalism", "Its Oracle treatment is carried forward."],
] as const;

export default function LabIndex() {
  return (
    <main className="rf-page">
      <DisplayType as="h1" text="Reality Fracture" effect="misregister" className="rf-page-title" />
      <div className="rf-index">
        {ENTRIES.map(([href, title, note]) => (
          <Link key={href} href={href}>
            <strong>{title}</strong>
            <span className="rf-copy">{note}</span>
          </Link>
        ))}
      </div>
    </main>
  );
}
