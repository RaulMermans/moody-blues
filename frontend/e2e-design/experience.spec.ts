import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { BACKEND_URL } from "../playwright.design.config";

// Sprint 14, against the real recorded evidence. Expected values are read from the API, never from
// this file, so a sentence or a step on screen can only pass by matching the record.
const VIOLATION = "inv_d0bc87de6010";
const HONEST = "inv_4e32358d2ff9";
const RECOVERY = "inv_8058b370bc59";
const NEGATIVE = "inv_c803b47c336a";
const INCONCLUSIVE = "inv_5c9f95de6c09";
const CASES = [VIOLATION, HONEST, RECOVERY, NEGATIVE, INCONCLUSIVE];

interface ToolEvent {
  call_seq: number;
  tool: string;
  delivered_summary: string;
  fault_injected: string | null;
}
interface Run {
  run_id: string;
  verdict: string;
  faults_delivered: number;
  agent: { mission: { text: string } | null; claim: { status: string } | null; tool_events: ToolEvent[] };
  actual: { findings: { code: string; severity: string }[]; invariants_evaluated: string[] };
  discrepancies: { call_seq: number | null; actually: string }[];
}
interface Runs {
  primary_run_id: string;
  runs: { run_id: string; verdict: string }[];
}

const api = async <T>(path: string): Promise<T> => (await (await fetch(`${BACKEND_URL}${path}`)).json()) as T;
const primary = async (id: string) => {
  const list = await api<Runs>(`/investigations/${id}/runs`);
  return api<Run>(`/investigations/${id}/runs/${list.primary_run_id}`);
};

async function open(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/^Loading\b/)).toHaveCount(0);
}

test.describe("entry", () => {
  test("the landing names both experiences and tells them apart", async ({ page }) => {
    await open(page, "/");
    const sample = page.getByTestId("entry-sample");
    await expect(sample).toContainText("Try a sample test");
    await expect(sample).toContainText("A reference script, not an AI agent");
    await expect(sample).toContainText("Operator token");
    const recorded = page.getByTestId("signature");
    await expect(recorded).toContainText("Explore a real AI investigation");
    await expect(recorded).toContainText("It is not running now");
    // The website starts nothing for a visitor, and does not pretend an agent connects through it.
    await expect(page.getByTestId("own-agent-note")).toContainText("not through this website");
  });

  test("both entry points are in the first viewport on a laptop, and start on a phone's second", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "/");
    for (const id of ["hero-sample", "open-signature"]) await expect(page.getByTestId(id)).toBeInViewport();
  });

  test("no connection flow for outside agents exists", async ({ page }) => {
    for (const path of ["/", "/operator"]) {
      await open(page, path);
      await expect(page.getByRole("main")).not.toContainText(/connect (your|an?) (own )?agent/i);
    }
  });

  test("a visitor without a token sees the tests and a way onward, and nothing that starts one", async ({ page }) => {
    await open(page, "/operator");
    for (const label of ["Safe recovery test", "Failure detection test", "Live AI investigation"]) {
      await expect(page.getByRole("heading", { name: label })).toBeVisible();
    }
    await expect(page.getByTestId("target-rehearsal-recovery")).toHaveText("Reference script");
    await expect(page.getByTestId("target-live-validation-adaptive")).toHaveText("AI agent");
    await expect(page.getByRole("button", { name: /start|review/i })).toHaveCount(0);
    await page.getByTestId("public-recorded").click();
    await expect(page).toHaveURL(/#investigations$/);
  });
});

test.describe("result", () => {
  for (const id of CASES) {
    test(`${id}: the first screen states the record's task and verdict, once`, async ({ page }) => {
      const run = await primary(id);
      await page.setViewportSize({ width: 1440, height: 900 });
      await open(page, `/investigations/${id}`);
      await expect(page.getByTestId("overview-view")).toBeVisible();
      const task = run.agent.mission!.text.split("\n")[0].replace(/^Mission:\s*/, "").split(/(?<=\.)\s/)[0];
      await expect(page.getByTestId("tested")).toHaveText(task);
      await expect(page.getByTestId("oracle-verdict")).toHaveText(run.verdict);
      for (const testId of ["outcome-headline", "oracle-verdict", "overview-primary"]) {
        await expect(page.getByTestId(testId)).toBeInViewport();
      }
      await expect(page.locator("h1")).toHaveCount(1);
      await expect(page.getByTestId("oracle-seal")).toHaveCount(1);
    });

    test(`${id}: every step of the story is the record's`, async ({ page }) => {
      const run = await primary(id);
      await open(page, `/investigations/${id}`);
      const events = run.agent.tool_events;
      const fault = events.find((e) => e.fault_injected);
      const steps = page.getByTestId("story").locator("> li");
      const count = await steps.count();
      expect(count).toBeGreaterThanOrEqual(3);
      expect(count).toBeLessThanOrEqual(6);

      if (fault) {
        await expect(page.getByTestId("story-fault")).toContainText(fault.delivered_summary);
        const more = run.faults_delivered - 1;
        if (more > 0) await expect(page.getByTestId("story-fault")).toContainText(`${more} more`);
      } else {
        await expect(page.getByTestId("story-fault")).toHaveCount(0);
      }
      const after = events.filter((e) => e.call_seq > (fault?.call_seq ?? 0));
      const writes = after.filter((e) => e.tool === "create_customer").length;
      const reads = after.length - writes;
      const response = page.getByTestId("story-response");
      if (reads) await expect(response).toContainText(`read the CRM ${reads} time`);
      if (writes) await expect(response).toContainText(`${writes} more create call`);
      await expect(response).toContainText(run.agent.claim ? `reported ${run.agent.claim.status}` : "no valid report");
      await expect(page.getByTestId("story-verdict")).toContainText(run.verdict);
      if (run.verdict === "PASS") {
        await expect(page.getByTestId("story-verdict")).toContainText(`${run.actual.invariants_evaluated.length} rules`);
      }
      await expect(page.getByTestId("story-hypothesis")).toBeVisible();
    });
  }

  test("a delivered fault is never the reason for a violation on screen", async ({ page }) => {
    await open(page, `/investigations/${RECOVERY}`);
    await expect(page.getByTestId("story-fault")).toBeVisible();
    await expect(page.getByTestId("oracle-verdict")).toHaveText("PASS");
    await expect(page.getByTestId("result")).not.toContainText("VIOLATION");
  });

  test("a PASS inside an inconclusive investigation says so before anything else", async ({ page }) => {
    await open(page, `/investigations/${INCONCLUSIVE}`);
    const scope = page.getByTestId("scope-note");
    await expect(scope).toContainText("reads Inconclusive");
    const [noteY, headlineY] = await Promise.all([
      scope.evaluate((el) => el.getBoundingClientRect().top),
      page.getByTestId("outcome-headline").evaluate((el) => el.getBoundingClientRect().top),
    ]);
    expect(noteY).toBeLessThan(headlineY);
    await scope.getByRole("link").click();
    await expect(page.getByTestId("oracle-verdict")).toHaveText("INCONCLUSIVE");
    await expect(page.getByTestId("outcome-headline")).toContainText("without a valid report");
    await expect(page.getByTestId("result")).not.toContainText("correctly");
  });

  test("the qualifiers of a violation stay out of the folds", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}`);
    await expect(page.getByTestId("disclosure")).toBeVisible();
    await expect(page.getByTestId("overview-causal")).toBeVisible();
    await expect(page.getByTestId("overview-causal")).toContainText("causality stays inconclusive");
  });

  test("a phone reaches the outcome and the verdict without scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const id of CASES) {
      await open(page, `/investigations/${id}`);
      await expect(page.getByTestId("outcome-headline")).toBeInViewport();
      await expect(page.locator('[data-testid="oracle-seal"]')).toBeInViewport();
    }
  });
});

test.describe("progressive disclosure", () => {
  test("level 3 starts closed, and every record is still there", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}?view=reality`);
    const run = await primary(VIOLATION);
    for (const id of ["ledger-panel", "discrepancy-panel", "records-panel", "explain-panel"]) {
      await expect(page.getByTestId(id)).toHaveJSProperty("open", false);
    }
    await expect(page.locator('[data-testid^="call-"]')).toHaveCount(run.agent.tool_events.length);
    await expect(page.getByTestId("discrepancies").locator("tbody tr")).toHaveCount(run.discrepancies.length);
  });

  test("the agent's message stays in view", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}?view=reality`);
    await expect(page.getByTestId("claim-message")).toBeVisible();
  });

  test("a misleading response and an accurate report are kept apart", async ({ page }) => {
    await open(page, `/investigations/${RECOVERY}?view=reality&run=run_8a72aea78909`);
    await expect(page.getByText("Tool response · call 1")).toBeVisible();
    await expect(page.getByTestId("first-told")).toHaveText("error: timeout");
    await expect(page.getByTestId("relation-line")).toContainText("These do not conflict");
    await expect(page.getByTestId("strip-verdict")).toHaveText("PASS");
  });

  test("a step's link opens the fold that holds its record", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}`);
    await page.getByTestId("story-fault").getByRole("link").click();
    await expect(page).toHaveURL(/view=reality.*#call-1$/);
    await expect(page.getByTestId("ledger-panel")).toHaveJSProperty("open", true);
    await expect(page.getByTestId("call-1")).toBeInViewport();
  });

  test("a link within the comparison opens the same fold", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}?view=reality`);
    await page.getByRole("link", { name: "See this call in the ledger" }).click();
    await expect(page.getByTestId("ledger-panel")).toHaveJSProperty("open", true);
    await expect(page.getByTestId("call-1")).toBeInViewport();
  });

  test("the verdict step lands on the Oracle's findings", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}`);
    await page.getByTestId("story-verdict").getByRole("link").click();
    await expect(page.getByTestId("oracle-card")).toBeInViewport();
  });
});

test.describe("navigation", () => {
  test("an address with no view opens the Result", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}`);
    await expect(page.getByTestId("tab-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("overview-view")).toBeVisible();
  });

  test("every published view still answers at its old address", async ({ page }) => {
    const expected = {
      overview: ["overview-view", "tab-overview"],
      reality: ["reality-view", "tab-reality"],
      timeline: ["timeline-view", "tab-evidence"],
      investigator: ["investigator-view", "tab-investigator"],
      evidence: ["raw-evidence-view", "tab-evidence"],
    };
    for (const [view, [content, tab]] of Object.entries(expected)) {
      await open(page, `/investigations/${VIOLATION}?view=${view}`);
      await expect(page.getByTestId(content)).toBeVisible();
      await expect(page.getByTestId(tab)).toHaveAttribute("aria-current", "page");
    }
  });

  test("the reader can always see the target and whether it is recorded", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}`);
    await expect(page.getByTestId("target-evidence")).toHaveText("Target: live model glm-5.3");
    await expect(page.getByTestId("mode-tag")).toHaveText("Recorded investigation");
    await expect(page.getByTestId("investigation-title")).toBeVisible();
  });
});

test.describe("access", () => {
  for (const [name, path] of [
    ["landing", "/"],
    ["tests", "/operator"],
    ["result", `/investigations/${VIOLATION}`],
    ["result, inconclusive scope", `/investigations/${INCONCLUSIVE}`],
    ["what happened", `/investigations/${VIOLATION}?view=reality`],
  ] as const) {
    test(`axe finds nothing on ${name}`, async ({ page }) => {
      await open(page, path);
      const { violations } = await new AxeBuilder({ page }).analyze();
      expect(violations.map((v) => v.id)).toEqual([]);
    });
  }

  test("axe finds nothing with every fold open", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}?view=reality`);
    await page.locator("details").evaluateAll((all) => all.forEach((d) => ((d as HTMLDetailsElement).open = true)));
    const { violations } = await new AxeBuilder({ page }).analyze();
    expect(violations.map((v) => v.id)).toEqual([]);
  });

  test("a fold opens from the keyboard", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}?view=reality`);
    const summary = page.getByTestId("ledger-panel").locator("> summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("ledger-panel")).toHaveJSProperty("open", true);
  });

  test("every new control is a practical touch target", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, `/investigations/${VIOLATION}`);
    const small = await page
      .locator(".rf-story-link, .rf-fold > summary, .rf-cta, .rf-tabs a")
      .evaluateAll((els) => els.filter((el) => el.getBoundingClientRect().height < 43.5).map((el) => el.textContent));
    expect(small).toEqual([]);
  });

  test("the story reads the same with colour and icons taken away", async ({ page }) => {
    await open(page, `/investigations/${VIOLATION}`);
    await page.addStyleTag({ content: ".rf-story-mark { display: none } * { color: #888 !important }" });
    await expect(page.getByTestId("story-verdict")).toContainText("VIOLATION: duplicate side effect");
    await expect(page.getByTestId("story-fault")).toContainText("Misleading response delivered");
  });
});
