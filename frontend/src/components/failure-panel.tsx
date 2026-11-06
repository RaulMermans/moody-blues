import Link from "next/link";

import type { Failure } from "@/lib/evidence";

const COPY: Record<Failure["kind"], { title: string; body: string }> = {
  not_found: {
    title: "No such investigation",
    body: "Nothing is published under this id. Only approved evidence is served here.",
  },
  integrity: {
    title: "This record failed verification",
    body: "Its contents did not match the published hash or schema, so no result is shown. A record that cannot be verified is never displayed as a finding.",
  },
  unreachable: {
    title: "Evidence service unreachable",
    body: "The backend could not be reached, so nothing can be shown. No result is implied.",
  },
  error: {
    title: "Evidence could not be loaded",
    body: "The backend refused or failed this request. No result is implied.",
  },
};

export function FailurePanel({ failure }: { failure: Failure }) {
  const copy = COPY[failure.kind];
  return (
    <section
      role="alert"
      data-testid="evidence-failure"
      data-kind={failure.kind}
      className="border border-warn/40 bg-warn/5 p-6"
    >
      <h2 className="text-lg font-semibold text-warn">{copy.title}</h2>
      <p className="mt-2 max-w-2xl text-sm text-muted">{copy.body}</p>
      <p className="mt-3 break-words font-mono text-xs text-faint">{failure.message}</p>
      {failure.requestId ? (
        <p className="mt-1 break-all font-mono text-xs text-faint">request {failure.requestId}</p>
      ) : null}
      <Link href="/" className="mt-4 inline-block text-sm text-truth hover:underline">
        Back to investigations
      </Link>
    </section>
  );
}
