"use client";

import { useEffect } from "react";

/**
 * The investigation streams in after the first paint, so a browser arriving on a deep link looks for
 * its anchor before the anchor exists. This repeats that one step once the content is there, and opens
 * the row it lands on. It renders nothing, and the page works without it.
 */
export function HashFocus() {
  useEffect(() => {
    const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    if (!target) return;
    const details = target.querySelector("details");
    if (details) details.open = true;
    target.scrollIntoView({ block: "start" });
  }, []);
  return null;
}
