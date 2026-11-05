import type { ElementType } from "react";

export type DisplayEffect = "plain" | "slice" | "misregister";

/**
 * Expressive editorial type. It takes a plain string, not children, so evidence cannot be wrapped in
 * it by accident: use it for headlines and labels only, never for a recorded value, identifier,
 * number, verdict or control. Screen readers get the text once; the layers are presentation.
 */
export function DisplayType({
  text,
  effect = "plain",
  as: Tag = "span",
  className = "",
}: {
  text: string;
  effect?: DisplayEffect;
  as?: ElementType;
  className?: string;
}) {
  return (
    <Tag className={`rf-display ${className}`} data-effect={effect}>
      <span className={effect === "plain" ? undefined : "rf-display-base"}>{text}</span>
      {effect === "plain" ? null : (
        <>
          <span aria-hidden data-rf-decorative className="rf-display-layer rf-display-layer-a">
            {text}
          </span>
          <span aria-hidden data-rf-decorative className="rf-display-layer rf-display-layer-b">
            {text}
          </span>
        </>
      )}
    </Tag>
  );
}
