import Link from "next/link";
import { Suspense } from "react";

import { LoadingPanel } from "@/components/ui";
import { loadCase } from "@/design/lab-data";
import { CaseFrame } from "@/design/prototypes/case-frame";
import { RealityComparison } from "@/design/prototypes/comparison";
import { listInvestigations } from "@/lib/evidence";
import { CASE_LABEL } from "@/lib/labels";

type Query = Record<string, string | string[] | undefined>;

async function CasePicker({ current }: { current: string | undefined }) {
  const list = await listInvestigations();
  if (!list.ok) return null;
  return (
    <nav aria-label="Recorded cases" className="rf-case-picker">
      {list.data.items.map(({ investigation_id: id, summary }) => {
        if (!summary?.case) return null;
        const active = current ? current === id : summary.case.kind === "verified_violation";
        return (
          <Link
            key={id}
            href={`/design-lab/comparison?case=${id}`}
            aria-current={active ? "page" : undefined}
            data-testid={`case-${id}`}
          >
            {CASE_LABEL[summary.case.kind]}
          </Link>
        );
      })}
    </nav>
  );
}

async function Comparison({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams;
  const id = typeof query.case === "string" ? query.case : undefined;
  const run = typeof query.run === "string" ? query.run : undefined;
  return (
    <>
      <CasePicker current={id} />
      <CaseFrame loaded={await loadCase(id, run)}>
        {(model) => <RealityComparison model={model} />}
      </CaseFrame>
    </>
  );
}

export default function Page({ searchParams }: { searchParams: Promise<Query> }) {
  return (
    <main>
      <Suspense fallback={<LoadingPanel label="Loading the recorded run" />}>
        <Comparison searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
