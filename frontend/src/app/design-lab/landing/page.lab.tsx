import { Suspense } from "react";

import { LoadingPanel } from "@/components/ui";
import { loadCase } from "@/design/lab-data";
import { CaseFrame } from "@/design/prototypes/case-frame";
import { Hero } from "@/design/prototypes/hero";

async function Landing() {
  return (
    <CaseFrame loaded={await loadCase()}>
      {(model) => <Hero model={model} href="/design-lab/comparison" />}
    </CaseFrame>
  );
}

export default function Page() {
  return (
    <main>
      <Suspense fallback={<LoadingPanel label="Loading the recorded run" />}>
        <Landing />
      </Suspense>
    </main>
  );
}
