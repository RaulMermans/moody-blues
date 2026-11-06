import { expect, test } from "@playwright/test";

import { BACKEND_URL, CANARY_VULTR_KEY, ORPHAN_FRONTEND_URL } from "../playwright.config";

interface Integration {
  name: string;
  state: string;
}

test("renders product identity", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("MOODY BLUES");
  await expect(page.getByRole("heading", { level: 1, name: "MOODY BLUES" })).toBeVisible();
  await expect(page.getByText("Test what agents do.")).toBeVisible();
});

test("shows the real backend connection and integration states", async ({ page, request }) => {
  // Ground truth straight from FastAPI (not through the frontend).
  const health = await request.get(`${BACKEND_URL}/health`);
  const ready = await request.get(`${BACKEND_URL}/ready`);
  expect(health.ok()).toBe(true);
  expect(ready.ok()).toBe(true);
  const healthBody = (await health.json()) as { status: string; version: string; integrations: Integration[] };
  const readyBody = (await ready.json()) as { status: string; checks: Integration[] };
  expect(healthBody.status).toBe("ok");

  await page.goto("/");
  const backend = page.getByTestId("backend-status");
  await expect(backend).toHaveAttribute("data-state", "connected");
  await expect(backend).toContainText("Backend connected");
  await expect(page.getByTestId("backend-meta")).toContainText(`v${healthBody.version}`);
  await expect(page.getByTestId("readiness-status")).toHaveText(readyBody.status);

  // Every state the UI shows must equal what the backend reported.
  for (const check of readyBody.checks) {
    await expect(page.getByTestId(`integration-${check.name}`)).toHaveAttribute(
      "data-state",
      check.state,
    );
  }
  // Vultr must never be displayed as verified/available without a live check.
  await expect(page.getByTestId("integration-vultr_inference")).not.toHaveAttribute(
    "data-state",
    "available",
  );
});

test("browser never receives key material or the internal backend URL", async ({ page }) => {
  const seen: string[] = [];
  page.on("response", async (res) => {
    if (res.request().resourceType() === "fetch" || res.url().endsWith("/")) {
      seen.push(await res.text().catch(() => ""));
    }
  });
  await page.goto("/");
  await expect(page.getByTestId("backend-status")).toHaveAttribute("data-state", "connected");
  // With a key present the UI must say "configured, not verified" -- never "available".
  await expect(page.getByTestId("integration-vultr_inference")).toHaveAttribute(
    "data-state",
    "configured_unverified",
  );
  const html = await page.content();
  for (const body of [...seen, html]) {
    expect(body).not.toContain(CANARY_VULTR_KEY);
    expect(body).not.toContain(BACKEND_URL);
  }
  expect(seen.length).toBeGreaterThan(0);
});

test("shows unreachable when the backend is genuinely down", async ({ page }) => {
  await page.goto(ORPHAN_FRONTEND_URL);
  const backend = page.getByTestId("backend-status");
  await expect(backend).toHaveAttribute("data-state", "unreachable");
  await expect(page.getByTestId("backend-error")).toContainText("Backend unreachable");
  await expect(page.getByRole("list", { name: "Integrations" })).toHaveCount(0);
});
