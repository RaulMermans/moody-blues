import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

// Real evidence, written by `make local-eval`. Nothing here is seeded, and no fixture stands in.
const ARTIFACTS = process.env.MOODY_E2E_LOCAL_ARTIFACTS ?? "";
const SHOTS = process.env.MOODY_E2E_SHOTS;
const TOKEN = "local-ui-test-token-local-ui-test-token-local";

interface Evaluation {
  identity: { model: string; digest: string };
  investigations: { investigation_id: string; world: string }[];
}
const evaluation = JSON.parse(readFileSync(path.join(ARTIFACTS, "local-eval.json"), "utf-8")) as Evaluation;
const MODEL = evaluation.identity.model;
const investigation = evaluation.investigations[0].investigation_id;

async function signIn(page: Page) {
  await page.goto("/operator");
  await page.getByLabel("Operator token").fill(TOKEN);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("operator-console")).toBeVisible();
}

async function settled(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main")).not.toContainText(/Loading (this )?investigation/);
}

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

test("a visitor cannot see a local run", async ({ page }) => {
  await page.goto(`/investigations/${investigation}`);
  await expect(page.locator("main")).toContainText(/not found|no such|isn.t available/i);
});

test("the list names a local model, not a hosted provider or a fixture", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await settled(page);
  const row = page.getByTestId(`investigation-${investigation}`);
  await expect(row).toContainText("Local model run");
  await expect(row).toContainText("External agent on a local model (Ollama)");
  await expect(row).toContainText("Test of external agent kite-crm-agent");
  await expect(row).not.toContainText("Rehearsal");
  await expect(row).not.toContainText("fixture");
  await row.scrollIntoViewIfNeeded();
  await shot(page, "local-list");
});

test("the result names the agent, the local model and the Oracle's outcome", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${investigation}`);
  await settled(page);
  await expect(page.getByTestId("target-evidence").first()).toContainText(`external agent using local model ${MODEL} (Ollama)`);
  const body = page.locator("main");
  await expect(body).toContainText("KITE");
  await expect(body).not.toContainText("No AI model ran here");
  await expect(body).not.toContainText("labeled fixture");
  await expect(page.getByTestId("mode-tag").first()).toContainText("Local model run");
  await shot(page, "local-result");
});

test("what happened shows the model's real tool calls", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${investigation}?view=reality`);
  await settled(page);
  const body = page.locator("main");
  await expect(page.getByTestId("target-evidence").first()).toContainText(`local model ${MODEL}`);
  await expect(body).not.toContainText("script");
  await expect(body).not.toContainText("baseline policy");
  await shot(page, "local-what-happened");
});

test("the investigation shows hypotheses the local model wrote", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${investigation}?view=investigator`);
  await settled(page);
  const view = page.getByTestId("investigator-view");
  await expect(view).toContainText(/phantom/i);
  await expect(view).not.toContainText(/fixture/i);
  await shot(page, "local-investigation");
});

test("evidence carries the provider, the digest and the source", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${investigation}?view=evidence`);
  await settled(page);
  const body = page.locator("main");
  await expect(body).toContainText("local_ollama");
  await expect(body).toContainText("model_provider");
  await expect(body).toContainText(evaluation.identity.digest);
  await expect(body).toContainText("model_calls_brokered");
  await expect(body).not.toContainText("live_provider");
  await expect(body).not.toContainText("offline_fixture");
  await shot(page, "local-evidence");
});
