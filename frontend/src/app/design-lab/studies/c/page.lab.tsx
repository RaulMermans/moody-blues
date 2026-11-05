import { Suspense } from "react";

import { LoadingPanel } from "@/components/ui";
import { loadCase } from "@/design/lab-data";
import { CaseFrame } from "@/design/prototypes/case-frame";
import { StudyDossier } from "@/design/prototypes/studies";

async function Study() {
  return <CaseFrame loaded={await loadCase()}>{(model) => <StudyDossier model={model} />}</CaseFrame>;
}

export default function Page() {
  return (
    <main data-testid="study">
      <Suspense fallback={<LoadingPanel label="Loading the recorded run" />}>
        <Study />
      </Suspense>
    </main>
  );
}
