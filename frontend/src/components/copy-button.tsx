"use client";

import { useState } from "react";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      data-testid="copy-id"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="inline-flex min-h-11 min-w-11 items-center justify-center border border-line px-2 font-mono text-[11px] text-muted hover:text-foreground"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}
