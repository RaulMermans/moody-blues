import { defineConfig, devices } from "@playwright/test";

// Runs against a deployment that already exists. It starts nothing, so a pass here cannot come
// from a local server. MOODY_HOSTED_TARGET says what is being tested and goes in the report:
//   vultr            the real public URL: the only target that counts as hosted evidence
//   local-tls-proxy  a dress rehearsal of this suite through a local Caddy, and proof of nothing hosted
const url = process.env.MOODY_HOSTED_URL;
const target = process.env.MOODY_HOSTED_TARGET;
if (!url || !url.startsWith("https://")) throw new Error("set MOODY_HOSTED_URL to an https:// URL");
if (target !== "vultr" && target !== "local-tls-proxy") {
  throw new Error("set MOODY_HOSTED_TARGET to vultr or local-tls-proxy");
}

export default defineConfig({
  testDir: "./e2e-hosted",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: "test-results-hosted",
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results-hosted/results.json" }],
  ],
  use: {
    baseURL: url,
    trace: "retain-on-failure",
    // Only a local proxy has a private certificate. The real target must present a valid one.
    ignoreHTTPSErrors: target === "local-tls-proxy",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
