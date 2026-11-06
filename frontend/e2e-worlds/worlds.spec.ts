import { readFileSync } from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Real records from both worlds, on the real pages. Nothing here is hand-written evidence.
const ROOT = path.resolve(__dirname, "../..");
type Ids = { careful: string; unsafe: string; not_exercised: string; reasoning: string; crm: string };
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
  if (!SHOTS) return;
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
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

test("reasoning checks name each mistake and are not presented as a verdict", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${ids().reasoning}?view=investigator`);
  const panel = page.getByTestId("reasoning-checks");
  await expect(panel).toContainText("not Oracle verdicts");
  for (const [kind, text] of [
    ["unsupported_finding", "does not match the verified findings"],
    ["contradicts_oracle", "h1 was stated as supported"],
    ["repeated_hypothesis", "h2 repeats h1"],
    ["invalid_experiment", "refused before running"],
  ]) {
    await expect(panel.locator(`[data-kind="${kind}"]`)).toContainText(text);
  }
  await expect(panel.getByTestId("verdict")).toHaveCount(0);
  await expect(panel).not.toContainText(/\b(VIOLATION|PASS|INCONCLUSIVE)\b/);
  await shot(page, "queue-reasoning-checks");
});

test("an undelivered fault is its own check, and a clean run says so", async ({ page }) => {
  await signIn(page);
  await page.goto(`/investigations/${ids().not_exercised}?view=investigator`);
  await expect(page.locator('[data-testid="reasoning-check"][data-kind="undelivered_fault"]').first()).toContainText(
    "never fired",
  );
  await page.goto("/investigations/inv_d0bc87de6010?view=investigator");
  await expect(page.getByTestId("investigator-view")).toBeVisible();
  await expect(page.getByTestId("reasoning-checks")).toHaveCount(0);
});

const WIDTHS = [
  ["phone", 390, 844],
  ["tablet", 768, 1024],
  ["desktop", 1440, 900],
] as const;

async function openFolds(page: Page) {
  for (const fold of ["invariants-panel", "records-panel"]) {
    await page.getByTestId(fold).locator("summary, button").first().click();
  }
}

for (const [name, width, height] of WIDTHS) {
  test.describe(`queue panels at ${width}px`, () => {
    test.use({ viewport: { width, height } });

    test(`nothing runs off the ${name} screen, and every panel can be read`, async ({ page }) => {
      await open(page, ids().unsafe);
      await openFolds(page);
      for (const id of ["invariants-panel", "records-panel", "experiment-validity", "run-context"]) {
        await expect(page.getByTestId(id)).toBeVisible();
      }
      const offenders = await page.evaluate(() => {
        const limit = document.documentElement.clientWidth;
        const clipped = (el: Element) => {
          for (let p = el.parentElement; p; p = p.parentElement) {
            if (["auto", "scroll", "hidden"].includes(getComputedStyle(p).overflowX)) return true;
          }
          return false;
        };
        return [...document.querySelectorAll("main *")]
          .filter((el) => el.getBoundingClientRect().right > limit + 1 && !clipped(el))
          .map((el) => `${el.tagName} ${el.getAttribute("data-testid") ?? ""} ${el.className}`.slice(0, 90))
          .slice(0, 6);
      });
      expect(offenders).toEqual([]);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await shot(page, `queue-panels-${width}`);
    });

    test(`axe finds nothing on the queue pages at ${name} width`, async ({ page }) => {
      await open(page, ids().unsafe);
      await openFolds(page);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.goto(`/investigations/${ids().reasoning}?view=investigator`);
      await expect(page.getByTestId("reasoning-checks")).toBeVisible();
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    });
  });
}

test("the queue folds work from the keyboard, with names a screen reader can use", async ({ page }) => {
  await open(page, ids().unsafe);
  const toggle = page.getByTestId("records-panel").locator("summary, button").first();
  await expect(toggle).toHaveAccessibleName(/.+/);
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("records-panel")).toContainText("report.nightly");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("records-panel").getByText("report.nightly").first()).toBeHidden();
});
