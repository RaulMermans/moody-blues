import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

// Real records from both worlds, on the real pages. Nothing here is hand-written evidence.
const ROOT = path.resolve(__dirname, "../..");
type Ids = { careful: string; unsafe: string; not_exercised: string; crm: string };
const ids = (): Ids =>
  JSON.parse(readFileSync(path.join(ROOT, "frontend/.e2e-worlds/artifacts/world-ids.json"), "utf-8"));
const TOKEN = "worlds-ui-test-token-worlds-ui-test-token-xx";
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

async function open(page: Page, id: string) {
  await signIn(page);
  await page.goto(`/investigations/${id}?view=reality`);
  await expect(page.getByTestId("outcome-summary")).toBeVisible();
}

test("the list says which environment each run tested", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await expect(page.getByTestId(`investigation-${ids().unsafe}`).getByTestId("investigation-world")).toHaveText("Job Queue");
  await expect(page.getByTestId(`investigation-${ids().crm}`).getByTestId("investigation-world")).toHaveText("Synthetic CRM");
  await shot(page, "worlds-list");
});

test("a queue violation shows the environment, the task and what happened, in its own words", async ({ page }) => {
  await open(page, ids().unsafe);
  const main = page.locator("main");
  await expect(page.getByTestId("run-context")).toContainText("Job Queue");
  await expect(page.getByTestId("mission")).toContainText("Submit exactly one job");
  await expect(main).toContainText("VIOLATION");
  await expect(main).toContainText("job queue");
  await expect(main).toContainText("external script, not a model");
  await expect(page.getByTestId("claim-status")).toContainText("completed");
  await expect(main).toContainText("submit_job");
  await shot(page, "queue-violation");
});

test("no CRM word appears anywhere on a queue run", async ({ page }) => {
  await open(page, ids().unsafe);
  for (const fold of ["invariants-panel", "records-panel"]) {
    await page.getByTestId(fold).locator("summary, button").first().click();
  }
  const text = (await page.locator("main").innerText()).toLowerCase();
  for (const word of ["crm", "customer", "client_request_id", "create_customer"]) {
    expect(text, word).not.toContain(word);
  }
  await shot(page, "queue-panels");
});

for (const view of ["overview", "reality", "investigator", "timeline", "evidence"]) {
  test(`no CRM word on the ${view} view of a queue investigation`, async ({ page }) => {
    await signIn(page);
    await page.goto(`/investigations/${ids().unsafe}?view=${view}`);
    await expect(page.locator("main")).toContainText("acme-queue-unsafe");
    await page.waitForLoadState("networkidle");
    const text = (await page.locator("main").innerText()).toLowerCase();
    for (const word of ["crm", "customer", "client_request_id"]) {
      const at = text.indexOf(word);
      expect(at === -1 ? "" : text.slice(Math.max(0, at - 60), at + 40), word).toBe("");
    }
  });
}

test("the Oracle's checks are the queue's own, and the broken one is marked", async ({ page }) => {
  await open(page, ids().unsafe);
  await page.getByTestId("invariants-panel").locator("summary, button").first().click();
  await expect(page.getByTestId("invariants-panel")).toContainText("Job Queue 1.0.0");
  const broken = page.locator('[data-testid^="invariant-"][data-violated="true"]');
  await expect(broken.first()).toBeVisible();
  await expect(page.getByTestId("invariant-job_status_matches")).toBeVisible();
  await expect(page.getByTestId("invariant-legal_transitions_only")).toContainText("this world");
  await expect(page.getByTestId("invariant-job_count_within_limit")).toContainText("this task");
});

test("authoritative jobs are real rows with their own fields", async ({ page }) => {
  await open(page, ids().unsafe);
  await page.getByTestId("records-panel").locator("summary, button").first().click();
  const panel = page.getByTestId("records-panel");
  await expect(panel).toContainText("report.nightly");
  await expect(panel).toContainText("status queued");
  await expect(panel).toContainText("job_");
});

test("validity says the fault fired, and is not presented as a verdict", async ({ page }) => {
  await open(page, ids().unsafe);
  const line = page.getByTestId("experiment-validity");
  await expect(line).toHaveAttribute("data-class", "exercised");
  await expect(line).toContainText("phantom failure");
  await expect(line).not.toContainText(/violation|pass/i);
});

test("a fault that never fired is said to have tested nothing", async ({ page }) => {
  await open(page, ids().not_exercised);
  const line = page.getByTestId("experiment-validity");
  await expect(line).toHaveAttribute("data-class", "not_exercised");
  await expect(line).toContainText("never fired");
  await expect(page.getByTestId("environment")).toContainText("none reached");
  await shot(page, "queue-not-exercised");
});

test("the careful script passes and stays qualified", async ({ page }) => {
  await open(page, ids().careful);
  const main = page.locator("main");
  await expect(main).toContainText("PASS");
  await expect(main).toContainText("external script, not a model");
  await expect(main).toContainText("does not show the script is safe");
  await shot(page, "queue-pass");
});

test("a new CRM run keeps every CRM word, and gains its environment", async ({ page }) => {
  await open(page, ids().crm);
  await expect(page.getByTestId("run-context")).toContainText("Synthetic CRM");
  await expect(page.locator("main")).toContainText("create_customer");
  await expect(page.locator("main")).toContainText("CRM");
  await shot(page, "crm-with-world");
});

test("a historical recorded bundle reads as it always did", async ({ page }) => {
  await page.goto("/investigations/inv_d0bc87de6010?view=reality");
  await expect(page.getByTestId("outcome-summary")).toBeVisible();
  await expect(page.locator("main")).toContainText("CRM");
  await expect(page.getByTestId("experiment-validity")).toHaveCount(0);
  await expect(page.getByTestId("invariants-panel")).toHaveCount(0);
  await expect(page.getByTestId("run-context")).not.toContainText("Synthetic CRM");
});

test("a visitor cannot see an operator's queue run", async ({ page }) => {
  await page.goto(`/investigations/${ids().unsafe}`);
  await expect(page.locator("main")).not.toContainText("report.nightly");
});
