import type { IntegrationStatus, PublicStatus, SystemStatus } from "./status-types";

/**
 * What the public page may know about the system. Fields are named here, never passed through, so a
 * setting name, environment, request id or error reason cannot reach a browser by being added upstream.
 * Readiness checks are live; health entries fill in anything readiness does not cover.
 */
export function publicStatus(status: SystemStatus): PublicStatus {
  if (status.backend !== "connected") return { backend: "unreachable", checkedAt: status.checkedAt };
  const live = status.readiness.checks;
  const rest = status.health.integrations.filter((i) => !live.some((c) => c.name === i.name));
  return {
    backend: "connected",
    checkedAt: status.checkedAt,
    version: status.health.version,
    revision: status.health.revision ?? null,
    readiness: status.readiness.status,
    integrations: [...live, ...rest].map(({ name, state }: IntegrationStatus) => ({ name, state })),
  };
}
