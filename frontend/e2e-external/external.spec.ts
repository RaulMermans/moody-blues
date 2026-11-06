import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const ROOT = path.resolve(__dirname, "../..");
function ids(): { careful: string; unsafe: string } {
  return JSON.parse(readFileSync(path.join(ROOT, "frontend/.e2e-external/artifacts/external-ids.json"), "utf-8"));
}
const TOKEN = "external-ui-test-token-external-ui-test-token";
const SHOTS = process.env.MOODY_E2E_SHOTS;

async function signIn(page: Page) {
  await page.goto("/operator");
  await page.getByLabel("Operator token").fill(TOKEN);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("operator-console")).toBeVisible();
}

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test("a visitor cannot see an external run", async ({ page }) => {
  await page.goto(`/investigations/${ids().unsafe}`);
  await expect(page.locator("main")).toContainText(/not found|no such|isn.t available/i);
  await expect(page.locator("main")).not.toContainText("Acme CRM");
  await page.goto("/");
  await expect(page.getByTestId(`investigation-${ids().unsafe}`)).toHaveCount(0);
});

test("the list names the external agent", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await expect(page.getByTestId(`investigation-${ids().unsafe}`)).toContainText("Test of external agent acme-crm-unsafe");
  await expect(page.getByTestId(`investigation-${ids().careful}`)).toContainText("Test of external agent acme-crm-careful");
});

test("the unsafe script shows its name, its verdict, and that it is no model", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${ids().unsafe}`);
  const target = page.getByTestId("target-evidence").first();
  await expect(target).toContainText("Acme CRM agent (unsafe script), external script, not a model");
  await expect(page.getByTestId("investigation-title")).toContainText("Test of external agent acme-crm-unsafe");
  const body = page.locator("main");
  await expect(body).toContainText("Violation");
  await expect(body).toContainText("No AI model ran here");
  await expect(body).not.toContainText("reference script");
  await expect(body).not.toContainText("live model");
  await shot(page, "external-unsafe-result");
});

test("the careful script passes, and a pass on a script stays qualified", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${ids().careful}`);
  await expect(page.getByTestId("target-evidence").first()).toContainText("external script, not a model");
  const body = page.locator("main");
  await expect(body).toContainText("No AI model ran here");
  await expect(body).not.toContainText("Violation verified");
  await shot(page, "external-careful-result");
});

test("what happened reads as a script, on the existing comparison", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${ids().unsafe}?view=reality`);
  const body = page.locator("main");
  await expect(page.getByTestId("target-evidence").first()).toContainText("external script, not a model");
  await expect(body).toContainText("script");
  await expect(body).not.toContainText("The agent");
  await expect(body).not.toContainText("baseline policy"); // an external agent has no policy of ours
  await shot(page, "external-unsafe-reality");
});

test("evidence keeps its links and its provenance", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${ids().unsafe}?view=evidence`);
  const body = page.locator("main");
  await expect(body).toContainText("external_agent");
  await expect(body).toContainText("external_scripted");
  await expect(body).toContainText("mb-agent/1");
  await expect(body).toContainText("bundle_sha256");
  await shot(page, "external-unsafe-evidence");
});
