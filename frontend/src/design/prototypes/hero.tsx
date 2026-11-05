import Link from "next/link";

import { MODE_LABEL } from "@/lib/labels";

import { DisplayType } from "../components/display-type";
import { Crack, DivergenceField } from "../components/divergence-divider";
import { OracleSeal } from "../components/oracle-seal";
import { RealityEcho } from "../components/reality-echo";
import { RecordSlab } from "../components/record-slab";
import type { ComparisonModel } from "../model";

/** The landing study. The headline is editorial; every object under it comes from the recorded run. */
export function Hero({ model, href }: { model: ComparisonModel; href: string }) {
  return (
    <DivergenceField state={model.divergence} scale={2.1} className="rf-hero">
      <Crack state={model.divergence} orientation="vertical" scale={2.1} className="rf-hero-crack-v" />
      <div className="rf-hero-bar">
        <p className="rf-wordmark">MOODY BLUES</p>
        <p className="rf-micro">The Reality Distortion Lab for AI Agents</p>
      </div>
      <h1 className="rf-hero-headline">
        <DisplayType text="What the agent believed." effect="slice" className="rf-hero-line rf-hero-line-agent" />{" "}
        <DisplayType text="What actually happened." className="rf-hero-line rf-hero-line-actual" />
      </h1>
      <div className="rf-hero-object rf-hero-object-agent" data-reality="agent">
        <RealityEcho>
          <div className="rf-slip">
            <p className="rf-micro">Agent&apos;s final status</p>
            <p className="rf-evidence-word rf-evidence-word-sm" data-testid="claim-status">
              {model.claim?.status ?? "no valid claim"}
            </p>
          </div>
        </RealityEcho>
      </div>
      <Crack state={model.divergence} orientation="horizontal" className="rf-hero-crack-h" />
      <div className="rf-hero-object rf-hero-object-actual" data-reality="actual">
        <p className="rf-micro" data-testid="record-count">
          {model.newRecords.length} new records committed
        </p>
        <div className="rf-hero-slabs">
          {model.newRecords.map((record) => (
            <RecordSlab key={record.customer.customer_id} record={{ ...record, mention: "not_assessed" }} />
          ))}
        </div>
      </div>
      <div className="rf-hero-foot">
        <div className="rf-hero-pitch">
          <p className="rf-hero-lead">
            MOODY BLUES distorts the environment around AI agents and verifies the gap between
            perception and reality.
          </p>
          <Link href={href} className="rf-cta" data-testid="hero-cta">
            Explore a verified failure <span aria-hidden>→</span>
          </Link>
        </div>
        <div className="rf-hero-verdict">
          <OracleSeal state={model.seal} size="sm" />
          {model.disclosure ? <p className="rf-hero-disclosure">{model.disclosure}</p> : null}
          <p className="rf-micro" data-testid="provenance">
            {MODE_LABEL[model.mode]} · {model.targetLabel} · {model.world}
          </p>
        </div>
      </div>
    </DivergenceField>
  );
}
