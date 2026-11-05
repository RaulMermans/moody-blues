import type { ReactNode } from "react";

import { FailurePanel } from "@/components/failure-panel";

import { OracleSeal } from "../components/oracle-seal";
import type { LoadedCase } from "../lab-data";
import type { ComparisonModel } from "../model";

/** Renders a loaded case, or says plainly why there is none. It never substitutes a result. */
export function CaseFrame({
  loaded,
  children,
}: {
  loaded: LoadedCase;
  children: (model: ComparisonModel) => ReactNode;
}) {
  if (!loaded.ok) {
    return (
      <div className="rf-page">
        <FailurePanel failure={loaded} />
      </div>
    );
  }
  if (!loaded.model) {
    return (
      <div className="rf-page">
        <OracleSeal state={loaded.seal} />
      </div>
    );
  }
  return <>{children(loaded.model)}</>;
}
