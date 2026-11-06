import { defineConfig, devices } from "@playwright/test";

// The pages, read against evidence a real local model produced. Starts no model and seeds nothing:
// MOODY_E2E_LOCAL_ARTIFACTS names the directory `make local-eval` wrote. Never part of `make check`.
const BACKEND_PORT = 8133;
const FRONTEND_PORT = 3133;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const OPERATOR_TOKEN = "local-ui-test-token-local-ui-test-token-local";

export default defineConfig({
  testDir: "./e2e-local",
  workers: 1,
  reporter: "line",
  use: { baseURL: `http://127.0.0.1:${FRONTEND_PORT}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run uvicorn moody_blues.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: "..",
      url: `${BACKEND_URL}/health`,
      env: {
        MOODY_VULTR_API_KEY: "",
        MOODY_LIVE_RUNS_ENABLED: "false",
        MOODY_OPERATOR_TOKEN: OPERATOR_TOKEN,
        MOODY_RECORDED_EVIDENCE_DIR: "evidence/recorded",
        MOODY_ARTIFACTS_DIR: process.env.MOODY_E2E_LOCAL_ARTIFACTS ?? "",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `pnpm exec next start --hostname 127.0.0.1 --port ${FRONTEND_PORT}`,
      url: `http://127.0.0.1:${FRONTEND_PORT}/design-lab`,
      env: { MOODY_BACKEND_URL: BACKEND_URL, MOODY_DESIGN_LAB: "1" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
