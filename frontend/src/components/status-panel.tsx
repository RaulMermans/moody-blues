"use client";

import { useCallback, useEffect, useState } from "react";

import type { IntegrationState, IntegrationStatus, SystemStatus } from "@/lib/status-types";

const POLL_MS = 15_000;

const STATE_LABEL: Record<IntegrationState, string> = {
  available: "Available",
  unavailable: "Unavailable",
  configured_unverified: "Configured · not verified",
  not_configured: "Not configured",
  not_checked: "Not checked",
};

const STATE_TONE: Record<IntegrationState, string> = {
  available: "bg-emerald-400",
  unavailable: "bg-rose-500",
  configured_unverified: "bg-amber-400",
  not_configured: "bg-slate-500",
  not_checked: "bg-slate-500",
};

const INTEGRATION_LABEL: Record<string, string> = {
  docker_sandbox: "Docker sandbox",
  vultr_inference: "Vultr Serverless Inference",
};

type ViewState = { kind: "loading" } | { kind: "loaded"; status: SystemStatus };

function Dot({ className }: { className: string }) {
  return <span aria-hidden className={`inline-block h-2 w-2 shrink-0 rounded-full ${className}`} />;
}

/** Without a key the hosted site makes no model calls at all; the backend's detail stays below. */
function stateLabel(item: IntegrationStatus): string {
  if (item.name === "vultr_inference" && item.state === "not_configured") {
    return "Off between authorized runs";
  }
  return STATE_LABEL[item.state];
}

function IntegrationRow({ item }: { item: IntegrationStatus }) {
  return (
    <li
      className="flex flex-col gap-1 border-t border-white/10 py-3 sm:flex-row sm:items-baseline sm:justify-between"
      data-testid={`integration-${item.name}`}
      data-state={item.state}
    >
      <span className="flex items-center gap-2 text-sm text-slate-200">
        <Dot className={STATE_TONE[item.state]} />
        {INTEGRATION_LABEL[item.name] ?? item.name}
      </span>
      <span className="text-right">
        <span className="block font-mono text-xs uppercase tracking-wide text-slate-300">
          {stateLabel(item)}
        </span>
        <span className="block text-xs text-slate-500">{item.detail}</span>
      </span>
    </li>
  );
}

async function fetchStatus(): Promise<SystemStatus> {
  try {
    const res = await fetch("/api/status", { cache: "no-store" });
    if (!res.ok) throw new Error(`status route returned HTTP ${res.status}`);
    return (await res.json()) as SystemStatus;
  } catch (err) {
    return {
      backend: "unreachable",
      checkedAt: new Date().toISOString(),
      error: `Frontend proxy unreachable: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/** Readiness checks are live; health entries fill in anything readiness doesn't cover. */
function mergeIntegrations(status: SystemStatus | null): IntegrationStatus[] {
  if (status?.backend !== "connected") return [];
  const live = status.readiness.checks;
  const rest = status.health.integrations.filter((i) => !live.some((c) => c.name === i.name));
  return [...live, ...rest];
}

export function StatusPanel() {
  const [view, setView] = useState<ViewState>({ kind: "loading" });

  const refresh = useCallback(() => {
    void fetchStatus().then((status) => setView({ kind: "loaded", status }));
  }, []);

  useEffect(() => {
    let active = true;
    const load = () =>
      void fetchStatus().then((status) => {
        if (active) setView({ kind: "loaded", status });
      });
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const backendState = view.kind === "loading" ? "checking" : view.status.backend;
  const integrations = mergeIntegrations(view.kind === "loaded" ? view.status : null);

  return (
    <section
      aria-labelledby="system-status"
      className="rounded-lg border border-white/10 bg-white/[0.03] p-5"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="system-status" className="text-sm font-medium uppercase tracking-widest text-slate-400">
          System status
        </h2>
        <button
          type="button"
          onClick={refresh}
          className="rounded border border-white/15 px-2 py-1 text-xs text-slate-300 hover:bg-white/10"
        >
          Refresh
        </button>
      </div>

      <div
        className="mt-4 flex items-center gap-3"
        data-testid="backend-status"
        data-state={backendState}
        role="status"
        aria-live="polite"
      >
        <Dot
          className={
            backendState === "connected"
              ? "bg-emerald-400"
              : backendState === "unreachable"
                ? "bg-rose-500"
                : "animate-pulse bg-slate-500"
          }
        />
        <span className="text-base text-slate-100">
          {backendState === "connected" && "Backend connected"}
          {backendState === "unreachable" && "Backend unreachable"}
          {backendState === "checking" && "Checking backend…"}
        </span>
      </div>

      {view.kind === "loaded" && view.status.backend === "connected" && (
        <p className="mt-1 font-mono text-xs text-slate-500" data-testid="backend-meta">
          v{view.status.health.version} · {view.status.health.environment} · readiness{" "}
          <span data-testid="readiness-status">{view.status.readiness.status}</span>
          {view.status.requestId && <> · {view.status.requestId}</>}
        </p>
      )}
      {view.kind === "loaded" && view.status.backend === "unreachable" && (
        <p className="mt-1 text-xs text-rose-300" data-testid="backend-error">
          {view.status.error}
        </p>
      )}

      {integrations.length > 0 && (
        <ul className="mt-4" aria-label="Integrations">
          {integrations.map((item) => (
            <IntegrationRow key={item.name} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}
