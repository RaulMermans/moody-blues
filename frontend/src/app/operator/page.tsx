import { Suspense } from "react";

import Link from "next/link";

import { OperatorConsole, OperatorLogin } from "@/components/operator-console";
import { TestCard } from "@/components/test-card";
import { LoadingPanel } from "@/components/ui";
import { operatorToken } from "@/lib/evidence";
import { TEST_CATALOG } from "@/lib/test-catalog";

/** A visitor sees what exists before being asked for anything, and has somewhere to go without a token. */
function Public() {
  return (
    <div className="flex flex-col gap-6">
      <ul aria-label="Available tests" className="rf-tests">
        {TEST_CATALOG.map((entry) => (
          <li key={entry.missionId} className="flex">
            <TestCard entry={entry} availability="Shown after sign-in" />
          </li>
        ))}
      </ul>
      <div className="grid gap-6 md:grid-cols-2">
        <OperatorLogin />
        <div className="flex flex-col items-start gap-3">
          <h2 className="rf-section-title">No token?</h2>
          <p className="rf-body">
            Starting a test needs operator access. Reading results does not: recorded AI investigations are
            open to everyone.
          </p>
          <Link href="/#investigations" className="rf-cta rf-cta-quiet" data-testid="public-recorded">
            Explore recorded investigations <span aria-hidden>→</span>
          </Link>
        </div>
      </div>
    </div>
  );
}

async function Gate() {
  const token = await operatorToken();
  return token ? <OperatorConsole /> : <Public />;
}

export default function Page() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 pb-12 pt-6 sm:px-6 sm:pt-8">
      <header className="flex flex-col gap-2">
        <h1 className="rf-outcome">Choose a test</h1>
        <p className="rf-lead">Each test puts a target through a controlled failure, then checks what really happened.</p>
      </header>
      <Suspense fallback={<LoadingPanel label="Checking operator session" />}>
        <Gate />
      </Suspense>
    </main>
  );
}
