import type { Relation, SeamTone } from "../model";

const GLYPH: Record<Relation, string> = { equal: "=", differs: "≠", unknown: "?" };

const SPOKEN: Record<Relation, string> = {
  equal: "The two sides agree.",
  differs: "The two sides differ.",
  unknown: "There is nothing to compare on one side.",
};

/**
 * The seam between two sides of one row. The glyph says what the row found, in plain symbols, and a
 * screen reader hears the same as a sentence. `break` is the one displaced state, and it needs an
 * Oracle VIOLATION. Rows without a recorded difference draw a steady hairline and no glyph unless the
 * caller asks for one, so a run of them reads as a calm line.
 */
export function DivergenceDivider({
  relation,
  tone,
  glyph = true,
}: {
  relation: Relation;
  tone: SeamTone;
  glyph?: boolean;
}) {
  return (
    <span className="rf-seam" data-tone={tone} data-relation={relation} data-testid="seam">
      {glyph ? (
        <span className="rf-seam-glyph">
          <span aria-hidden>{GLYPH[relation]}</span>
          <span className="sr-only">{SPOKEN[relation]}</span>
        </span>
      ) : null}
    </span>
  );
}
