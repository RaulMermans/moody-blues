import { defineConfig, devices } from "@playwright/test";

// External runs through the real pages. Its own config, because these runs are operator evidence,
// so it needs an operator token, and that would change what every other suite sees.
const BACKEND_PORT = 8132;
const FRONTEND_PORT = 3132;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const ARTIFACTS = "frontend/.e2e-external/artifacts";
const OPERATOR_TOKEN = "external-ui-test-token-external-ui-test-token";

export default defineConfig({
  testDir: "./e2e-external",
  // Runs once, through the same pipeline a developer's run goes through. The backend reads from disk.
  globalSetup: "./e2e-external/seed.ts",
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
        MOODY_ARTIFACTS_DIR: ARTIFACTS,
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
