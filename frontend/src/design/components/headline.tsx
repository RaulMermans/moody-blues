import type { ElementType } from "react";

/**
 * The two-sentence statement of a run: what was reported, then what reality recorded. It takes plain
 * strings, so a recorded value cannot be wrapped in it by accident. `outOfRegister` sets the second
 * line off the first by a small fixed offset. It is a position, not a layer: screen readers get the
 * sentence once, and the page reads the same with the offset removed.
 */
export function Headline({
  first,
  second,
  outOfRegister = false,
  as: Tag = "h1",
  size = "headline",
}: {
  first: string;
  second: string;
  outOfRegister?: boolean;
  as?: ElementType;
  size?: "headline" | "poster" | "compact";
}) {
  return (
    <Tag
      className="rf-headline"
      data-register={outOfRegister ? "out" : "in"}
      data-size={size}
      data-testid="headline"
    >
      <span className="rf-headline-first">{first}</span>{" "}
      <span className="rf-headline-second">{second}</span>
    </Tag>
  );
}
