"use client";

import { useEffect } from "react";

const FRAMES = 180; // about three seconds: a view that streams in has to arrive first

function reveal(hash: string): boolean {
  const target = document.getElementById(decodeURIComponent(hash.slice(1)));
  if (!target) return false;
  for (let node = target.parentElement; node; node = node.parentElement) {
    if (node instanceof HTMLDetailsElement) node.open = true;
  }
  if (target instanceof HTMLDetailsElement) target.open = true;
  if (target.dataset.testid?.startsWith("call-")) {
    const row = target.querySelector("details");
    if (row) row.open = true;
  }
  target.scrollIntoView({ block: "start" });
  return true;
}

/**
 * A browser arriving on a deep link looks for its anchor before streamed content exists, and an anchor
 * inside a closed disclosure has no position to scroll to. A client-side link fires no `hashchange` at
 * all. So this follows the hash itself: on arrival, on a clicked link, and on back and forward, it waits
 * for the address and the target, opens what holds the target, and scrolls there. It renders nothing,
 * and the page works without it.
 */
export function HashFocus() {
  useEffect(() => {
    let frame = 0;
    const follow = (hash: string) => {
      cancelAnimationFrame(frame);
      let left = FRAMES;
      const tick = () => {
        if (window.location.hash === hash && reveal(hash)) return;
        if (--left > 0) frame = requestAnimationFrame(tick);
      };
      tick();
    };
    const onClick = (event: MouseEvent) => {
      const link = event.target instanceof Element ? event.target.closest("a") : null;
      if (link?.hash && link.origin === window.location.origin) follow(link.hash);
    };
    const onHash = () => {
      if (window.location.hash) follow(window.location.hash);
    };
    onHash();
    document.addEventListener("click", onClick);
    window.addEventListener("hashchange", onHash);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("click", onClick);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);
  return null;
}
