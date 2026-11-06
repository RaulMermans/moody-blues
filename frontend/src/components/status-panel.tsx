"use client";

import { useEffect, useState } from "react";

import type { IntegrationState, PublicStatus } from "@/lib/status-types";

const POLL_MS = 15_000;

const STATE_LABEL: Record<IntegrationState, string> = {
  available: "Available",
  unavailable: "Unavailable",
  configured_unverified: "Configured, not verified",
  not_configured: "Not configured",
  not_checked: "Not checked",
};

const STATE_TONE: Record<IntegrationState, string> = {
  available: "bg-good",
  unavailable: "bg-bad",
  configured_unverified: "bg-warn",
  not_configured: "bg-faint",
  not_checked: "bg-faint",
};

const INTEGRATION_LABEL: Record<string, string> = {
  docker_sandbox: "Experiment sandbox",
  vultr_inference: "Live inference",
};

type Integration = Extract<PublicStatus, { backend: "connected" }>["integrations"][number];

function Dot({ className }: { className: string }) {
  return <span aria-hidden className={`inline-block h-2 w-2 shrink-0 rounded-full ${className}`} />;
}

/** Recorded investigations need no model, so inference being off is the site's normal state. */
function stateLabel(item: Integration): string {
  if (item.name === "vultr_inference" && item.state === "not_configured") {
    return "Off between authorized runs";
  }
  return STATE_LABEL[item.state];
}

async function fetchStatus(): Promise<PublicStatus> {
  try {
    const res = await fetch("/api/status", { cache: "no-store" });
    if (!res.ok) throw new Error(`status route returned HTTP ${res.status}`);
    return (await res.json()) as PublicStatus;
  } catch {
    return { backend: "unreachable", checkedAt: new Date().toISOString() };
  }
}

export function StatusPanel() {
  const [status, setStatus] = useState<PublicStatus | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      void fetchStatus().then((next) => {
        if (active) setStatus(next);
      });
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const backendState = status?.backend ?? "checking";

  return (
    <section aria-labelledby="system-status" className="rf-status">
      <h2 id="system-status" className="rf-label">
        System status
      </h2>
      <div className="rf-status-grid">
        <div>
          <div
            className="rf-status-line"
            data-testid="backend-status"
            data-state={backendState}
            role="status"
            aria-live="polite"
          >
            <Dot
              className={
                backendState === "connected"
                  ? "bg-good"
                  : backendState === "unreachable"
                    ? "bg-bad"
                    : "animate-pulse bg-faint"
              }
            />
            {backendState === "connected" && "Backend connected"}
            {backendState === "unreachable" && "Backend unreachable"}
            {backendState === "checking" && "Checking backend…"}
          </div>
          {status?.backend === "connected" ? (
            <p className="rf-data" data-testid="backend-meta">
              v{status.version} · readiness <span data-testid="readiness-status">{status.readiness}</span>
            </p>
          ) : null}
          {status?.backend === "unreachable" ? (
            <p className="rf-data" data-testid="backend-error">
              Backend unreachable, so recorded investigations cannot load right now.
            </p>
          ) : null}
        </div>
        {status?.backend === "connected" && status.integrations.length > 0 ? (
          <ul aria-label="Integrations" className="rf-status-list">
            {status.integrations.map((item) => (
              <li key={item.name} data-testid={`integration-${item.name}`} data-state={item.state}>
                <span className="rf-status-line">
                  <Dot className={STATE_TONE[item.state]} />
                  {INTEGRATION_LABEL[item.name] ?? item.name}
                </span>
                <span className="rf-data">{stateLabel(item)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
