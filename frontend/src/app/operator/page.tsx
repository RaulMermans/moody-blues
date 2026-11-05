import { Suspense } from "react";

import { OperatorConsole, OperatorLogin } from "@/components/operator-console";
import { LoadingPanel } from "@/components/ui";
import { operatorToken } from "@/lib/evidence";

async function Gate() {
  const token = await operatorToken();
  return token ? <OperatorConsole /> : <OperatorLogin />;
}

export default function Page() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">Operator</h1>
        <p className="text-sm leading-6 text-muted">
          Start a bounded investigation. Reading recorded investigations needs no access. Starting
          anything does.
        </p>
      </header>
      <Suspense fallback={<LoadingPanel label="Checking operator session" />}>
        <Gate />
      </Suspense>
    </main>
  );
}
