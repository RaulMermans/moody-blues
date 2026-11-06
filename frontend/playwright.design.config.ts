import { defineConfig, devices } from "@playwright/test";

// The investigation screens and the design lab, built with MOODY_DESIGN_LAB=1 into their own output
// (`pnpm test:design` builds it). The backend serves the real committed bundles read-only. No provider key is set, so nothing here
// can reach inference.
const BACKEND_PORT = 8110;
const FRONTEND_PORT = 3110;

export const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

export default defineConfig({
  testDir: "./e2e-design",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  outputDir: "test-results-design",
  use: { baseURL: `http://127.0.0.1:${FRONTEND_PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] }, testMatch: "cross-browser.spec.ts" },
    // Opt-in, because the browser is not part of `make setup`. Playwright's Firefox build, not a stock install.
    ...(process.env.MOODY_E2E_FIREFOX
      ? [{ name: "firefox", use: { ...devices["Desktop Firefox"] }, testMatch: "cross-browser.spec.ts" }]
      : []),
  ],
  webServer: [
    {
      command: `uv run uvicorn moody_blues.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: "..",
      url: `${BACKEND_URL}/health`,
      env: {
        MOODY_VULTR_API_KEY: "",
        MOODY_LIVE_RUNS_ENABLED: "false",
        MOODY_RECORDED_EVIDENCE_DIR: "evidence/recorded",
        MOODY_ARTIFACTS_DIR: "frontend/.e2e-design/artifacts",
      },
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
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
