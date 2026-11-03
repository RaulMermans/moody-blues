// Mirrors backend/moody_blues/services/health.py. Client-safe (no secrets, no URLs).

export type IntegrationState =
  | "not_configured"
  | "configured_unverified"
  | "not_checked"
  | "available"
  | "unavailable";

export interface IntegrationStatus {
  name: string;
  state: IntegrationState;
  detail: string;
  checked_at: string | null;
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  uptime_seconds: number;
  integrations: IntegrationStatus[];
}

export interface ReadinessResponse {
  status: "ready" | "degraded";
  checks: IntegrationStatus[];
}

export type SystemStatus =
  | {
      backend: "connected";
      checkedAt: string;
      requestId: string | null;
      health: HealthResponse;
      readiness: ReadinessResponse;
    }
  | {
      backend: "unreachable";
      checkedAt: string;
      error: string;
    };
