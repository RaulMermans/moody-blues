"use client";

import { useEffect, useId, useRef, useState } from "react";

const LONG_TEXT = 240;

/**
 * Recorded text, shortened on screen only. The whole text is always in the page and read by assistive
 * technology, and nothing is summarised. The control exists only when lines are really cut, which
 * depends on the width. Without JavaScript the noscript rule in the view shows everything.
 */
export function ClampText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const [cut, setCut] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();
  const long = text.length > LONG_TEXT;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Also fires when a folded cycle opens, because the text only has a size from then on.
    const observer = new ResizeObserver(() => {
      if (el.dataset.open === undefined) setCut(el.scrollHeight > el.clientHeight + 1);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (!long) return <>{text}</>;
  return (
    <>
      <span ref={ref} id={id} className="rf-clamp" data-open={open || undefined}>
        {text}
      </span>
      {cut || open ? (
        <button
          type="button"
          className="rf-more"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          data-testid="clamp-toggle"
        >
          {open ? "Show less" : "Show the full text"}
        </button>
      ) : null}
    </>
  );
}
