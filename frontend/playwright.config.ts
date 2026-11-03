import { defineConfig, devices } from "@playwright/test";

// Real end-to-end: starts the actual FastAPI backend and a production Next.js build.
// A second frontend instance points at a closed port to exercise the "unreachable" path
// against a genuinely absent backend (no request mocking).
const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3000;
const ORPHAN_FRONTEND_PORT = 3001;
const DEAD_BACKEND_PORT = 8999;

export const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
export const ORPHAN_FRONTEND_URL = `http://127.0.0.1:${ORPHAN_FRONTEND_PORT}`;
// Not a real credential: a canary to prove key material never reaches the browser.
// It makes the backend report Vultr as configured_unverified; nothing calls Vultr.
export const CANARY_VULTR_KEY = "e2e-canary-not-a-real-key-7c41";

const reuse = !process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run uvicorn moody_blues.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: "..",
      url: `${BACKEND_URL}/health`,
      env: { MOODY_VULTR_API_KEY: CANARY_VULTR_KEY },
      reuseExistingServer: reuse,
      timeout: 60_000,
      stdout: "pipe",
    },
    {
      command: `pnpm start --hostname 127.0.0.1 --port ${FRONTEND_PORT}`,
      url: `http://127.0.0.1:${FRONTEND_PORT}/`,
      env: { MOODY_BACKEND_URL: BACKEND_URL },
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
    {
      command: `pnpm start --hostname 127.0.0.1 --port ${ORPHAN_FRONTEND_PORT}`,
      url: `${ORPHAN_FRONTEND_URL}/`,
      env: { MOODY_BACKEND_URL: `http://127.0.0.1:${DEAD_BACKEND_PORT}` },
      reuseExistingServer: reuse,
      timeout: 60_000,
    },
  ],
});
