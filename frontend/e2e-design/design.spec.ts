import { mkdirSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { BACKEND_URL } from "../playwright.design.config";

// The investigation screens against the real recorded evidence. Expected values come from the API,
// never from this file. The copy rules themselves are covered in rules.spec.ts.

const SHOTS = join(__dirname, "..", "..", "docs", "design", "screenshots", "sprint-12");
const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
];

const VIOLATION = "inv_d0bc87de6010";
const HONEST = "inv_4e32358d2ff9";
const RECOVERY = "inv_8058b370bc59";
const NEGATIVE = "inv_c803b47c336a";
const INCONCLUSIVE = "inv_5c9f95de6c09";
const ALL = [VIOLATION, HONEST, RECOVERY, NEGATIVE, INCONCLUSIVE];
const FALSE_RUN = "run_cc34d7a6e314";
const NO_CLAIM_RUN = "run_8145a6bc00d7";
const UNDER_REPORT_RUN = "run_422f9afbb127";

interface Customer {
  customer_id: string;
  role: string;
  flagged_duplicate: boolean;
  named_in_claim: boolean;
}
interface Run {
  run_id: string;
  verdict: "PASS" | "VIOLATION" | "INCONCLUSIVE";
  run_outcome: string | null;
  faults_delivered: number;
  experiment_id: string;
  world_ref: string;
  discrepancies: { kind: string; call_seq: number | null; agent_saw: string; actually: string }[];
  agent: {
    claim: { status: string; customer_id: string | null; message: { text: string } } | null;
    disclosure: unknown;
    tool_events: { call_seq: number; fault_injected: string | null }[];
    termination: string;
  };
  actual: {
    customers: Customer[];
    findings: { code: string; severity: string }[];
    objective_satisfied: boolean;
    invariants_evaluated: string[];
    invariants_violated: string[];
  };
}
interface Runs {
  primary_run_id: string;
  runs: { run_id: string; verdict: string }[];
}

async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`);
  expect(res.ok, path).toBe(true);
  return (await res.json()) as T;
}

async function eachRun(visit: (id: string, run: Run) => Promise<void>) {
  for (const id of ALL) {
    const { runs } = await api<Runs>(`/investigations/${id}/runs`);
    for (const { run_id: runId } of runs) {
      await visit(id, await api<Run>(`/investigations/${id}/runs/${runId}`));
    }
  }
}

const runUrl = (id: string, runId: string) => `/investigations/${id}?view=reality&run=${runId}`;

async function settled(page: Page) {
  await expect(page.getByText(/^Loading\b/)).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

async function shot(page: Page, name: string, fullPage = false) {
  await settled(page);
  if (!process.env.MOODY_DESIGN_SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage, animations: "disabled" });
}

test.describe("screenshots", () => {
  test("every state, as rendered", async ({ page }) => {
    test.slow();
    const states: [string, string][] = [
      ["landing", "/"],
      ["violation", `/investigations/${VIOLATION}`],
      ["honest-violation", `/investigations/${HONEST}`],
      ["recovery", `/investigations/${RECOVERY}`],
      ["negative", `/investigations/${NEGATIVE}`],
      ["inconclusive-no-claim", runUrl(INCONCLUSIVE, NO_CLAIM_RUN)],
      ["inconclusive-under-report", runUrl(HONEST, UNDER_REPORT_RUN)],
      ["overview", `/investigations/${VIOLATION}?view=overview`],
      ["timeline", `/investigations/${VIOLATION}?view=timeline`],
      ["timeline-recovery", `/investigations/${RECOVERY}?view=timeline`],
      ["timeline-inconclusive", `/investigations/${INCONCLUSIVE}?view=timeline`],
      ["investigator", `/investigations/${VIOLATION}?view=investigator`],
      ["investigator-recovery", `/investigations/${RECOVERY}?view=investigator`],
      ["investigator-inconclusive", `/investigations/${INCONCLUSIVE}?view=investigator`],
    ];
    for (const { width, height } of VIEWPORTS) {
      const size = width === 390 ? "mobile" : width === 768 ? "tablet" : "desktop";
      await page.setViewportSize({ width, height });
      for (const [name, url] of states) {
        await page.goto(url);
        await shot(page, `after-${name}-${size}`);
        if (["violation", "landing", "timeline", "investigator", "overview"].includes(name)) {
          await shot(page, `after-${name}-${size}-full`, true);
        }
      }
    }
  });

  test("with every offset removed, the page reads the same", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    const before = await page.locator("main").innerText();
    await page.addStyleTag({
      content: `:root { --rf-slip-seam: 0px; --rf-slip-record: 0px; --rf-slip-headline: 0em; --rf-divergence: var(--rf-text-muted); } .rf-headline-second::before { display: none; }`,
    });
    expect(await page.locator("main").innerText()).toBe(before);
    await shot(page, "after-violation-effects-off");
  });
});

test.describe("truth", () => {
  test("every recorded run renders exactly what its evidence holds", async ({ page }) => {
    test.slow();
    let seen = 0;
    await eachRun(async (id, run) => {
      seen += 1;
      await page.goto(runUrl(id, run.run_id));
      await settled(page);
      const main = page.getByRole("main");
      const added = run.actual.customers.filter((c) => c.role === "new");
      const flagged = run.actual.customers.filter((c) => c.flagged_duplicate).length;

      await expect(main.getByTestId("reality-view")).toHaveAttribute("data-run", run.run_id);
      await expect(main.getByTestId("strip-verdict")).toHaveText(run.verdict);
      await expect(main.getByTestId("oracle-verdict")).toHaveText(run.verdict);
      await expect(main.getByTestId("strip-claim")).toHaveText(run.agent.claim?.status ?? "no valid claim");
      await expect(main.getByTestId("strip-state")).toHaveText(
        flagged > 1
          ? `${flagged} records committed, 1 required`
          : `${added.length} new record${added.length === 1 ? "" : "s"} committed`,
      );
      await expect(main.getByTestId("record-count")).toHaveText(String(added.length));
      await expect(main.getByTestId("outcome-strip")).toContainText(
        run.actual.objective_satisfied ? "Objective satisfied" : "Objective not satisfied",
      );
      await expect(main.getByTestId("invariant-count")).toHaveText(
        `${run.actual.invariants_evaluated.length} invariants evaluated, ${run.actual.invariants_violated.length} broken`,
      );

      // A slab is a real row: same ids, same count, nothing extra drawn as a record.
      const drawn = await main.getByTestId("record-slab").evaluateAll((slabs) =>
        slabs.map((s) => s.getAttribute("data-record")),
      );
      expect(drawn.sort()).toEqual(added.map((c) => c.customer_id).sort());
      await expect(main.locator('[data-flagged="true"]')).toHaveCount(
        added.filter((c) => c.flagged_duplicate).length,
      );

      // The first divergence row repeats the record word for word.
      const first = run.discrepancies
        .filter((d) => d.call_seq !== null)
        .sort((a, b) => a.call_seq! - b.call_seq!)[0];
      if (first) {
        await expect(main.getByTestId("first-told")).toHaveText(first.agent_saw);
        await expect(main.getByTestId("first-actual")).toHaveText(first.actually);
      }

      // Every call is present, and a fault mark appears on exactly the delivered calls.
      await expect(main.locator('[data-testid^="call-"]')).toHaveCount(run.agent.tool_events.length);
      for (const event of run.agent.tool_events) {
        await expect(main.getByTestId(`call-${event.call_seq}`)).toHaveAttribute(
          "data-fault",
          event.fault_injected ?? "",
        );
      }
      await expect(main.getByTestId("causal-fault")).toHaveText(
        run.faults_delivered ? `Yes, ${run.faults_delivered}` : "No",
      );

      // Distortion needs a VIOLATION.
      const faulted = run.agent.tool_events.filter((e) => e.fault_injected).length;
      const breaks = await main.locator('.rf-seam[data-tone="break"]').count();
      if (run.verdict === "VIOLATION") expect(breaks, run.run_id).toBeGreaterThanOrEqual(faulted);
      else expect(breaks, run.run_id).toBe(0);
      const falseClaim = run.actual.findings.some((f) => f.code === "false_completion_claim");
      await expect(main.getByTestId("headline")).toHaveAttribute("data-register", falseClaim ? "out" : "in");
      if (run.verdict !== "VIOLATION") {
        await expect(main.locator('.rf-slab[data-extra="true"]')).toHaveCount(0);
        await expect(main.locator(".rf-slab-flag")).toHaveCount(0);
      }

      if (run.agent.disclosure) await expect(main.getByTestId("disclosure")).toBeVisible();
      if (run.agent.claim) {
        // The message is on the page and visible, never behind a control.
        await expect(main.getByTestId("claim-message")).toBeVisible();
        await expect(main.getByTestId("claim-message")).toHaveText(run.agent.claim.message.text);
      }
      await expect(main.getByTestId("mode-tag")).toHaveText("Recorded investigation");
    });
    expect(seen).toBe(20);
  });

  test("the false completion states the contradiction and the disclosure", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    await expect(page.getByTestId("headline")).toHaveText(
      "The agent reported completion. Reality recorded a duplicate.",
    );
    await expect(page.getByTestId("disclosure")).toContainText("not concealment");
    await expect(page.locator('.rf-slab[data-extra="true"]')).toHaveCount(1);
    await expect(page.getByTestId("case-study")).toContainText("Reproduced in 4 of 4");
    await expect(page.getByTestId("causal-evidence")).toContainText("causality stays inconclusive");
  });

  test("the duplicate slips as a whole, and only that record moves", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    const lefts = await page.getByTestId("record-slab").evaluateAll((slabs) =>
      slabs.map((s) => ({ extra: s.getAttribute("data-extra"), left: s.getBoundingClientRect().left })),
    );
    const plain = lefts.find((l) => l.extra === "false")!;
    const extra = lefts.find((l) => l.extra === "true")!;
    expect(extra.left - plain.left).toBeGreaterThan(8);
    // Nothing is drawn around it: no second outline that could read as another record.
    const drawn = await page.getByTestId("record-slab").evaluateAll((slabs) =>
      slabs.flatMap((s) => [getComputedStyle(s, "::before").content, getComputedStyle(s, "::after").content]),
    );
    expect(new Set(drawn)).toEqual(new Set(["none"]));
  });

  test("an honest report of a real duplicate keeps its status and draws no contradiction", async ({ page }) => {
    await page.goto(`/investigations/${HONEST}`);
    await settled(page);
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-story", "reported_violation");
    await expect(page.getByTestId("disclosure")).not.toContainText("wrong status");
    await expect(page.getByTestId("disclosure")).toContainText("no false claim");
    const outcome = page.getByTestId("comparison-row").first().getByTestId("seam");
    await expect(outcome).toHaveAttribute("data-relation", "equal");
    await expect(page.locator('.rf-slab[data-extra="true"]')).toHaveCount(1);
  });

  test("a clean recovery stays calm and says what the agent did", async ({ page }) => {
    await page.goto(`/investigations/${RECOVERY}`);
    await settled(page);
    await expect(page.getByTestId("headline")).toHaveText("The agent reported completion. Reality agrees.");
    await expect(page.getByTestId("explain-happened")).toContainText("It checked state and ended with exactly one record");
    await expect(page.getByTestId("causal-violation")).toHaveText("No");
    await expect(page.getByTestId("causal-evidence")).toHaveText("Not applicable: no violation to explain.");
    await expect(page.locator('.rf-seam[data-tone="break"]')).toHaveCount(0);
    const tick = await page
      .locator(".rf-headline-second")
      .evaluate((el) => getComputedStyle(el, "::before").content);
    expect(tick).toBe("none");
    // Nothing on a PASS run is drawn in the divergence colour.
    const coral = await page.evaluate(() => {
      const probe = document.createElement("i");
      probe.style.color = "var(--rf-divergence)";
      document.body.append(probe);
      const value = getComputedStyle(probe).color;
      probe.remove();
      return [...document.querySelectorAll('[data-testid="reality-view"] *')].filter(
        (el) => getComputedStyle(el).color === value || getComputedStyle(el).borderLeftColor === value,
      ).length;
    });
    expect(coral).toBe(0);
  });

  test("a negative result is not called safe", async ({ page }) => {
    await page.goto(`/investigations/${NEGATIVE}`);
    await settled(page);
    await expect(page.getByTestId("explain-matters")).toContainText("does not show the agent is safe");
    const text = await page.getByTestId("reality-view").innerText();
    expect(text.replaceAll("does not show the agent is safe", "")).not.toMatch(/\bsafe\b/i);
  });

  test("a run with no claim says so and is neither success nor failure", async ({ page }) => {
    await page.goto(runUrl(INCONCLUSIVE, NO_CLAIM_RUN));
    await settled(page);
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-story", "no_claim");
    await expect(page.getByTestId("headline")).toContainText("The agent filed no final report.");
    await expect(page.getByTestId("headline")).not.toContainText("false");
    await expect(page.getByTestId("strip-claim")).toHaveText("no valid claim");
    await expect(page.getByTestId("strip-verdict")).toHaveText("INCONCLUSIVE");
    await expect(page.getByTestId("comparison-row").first().getByTestId("seam")).toHaveAttribute(
      "data-relation",
      "unknown",
    );
    await expect(page.locator('.rf-seam[data-tone="break"]')).toHaveCount(0);
  });

  test("an under-report is shown as inconclusive, with its difference marked and undramatic", async ({ page }) => {
    await page.goto(runUrl(HONEST, UNDER_REPORT_RUN));
    await settled(page);
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-story", "under_reported");
    await expect(page.getByTestId("headline")).toHaveAttribute("data-register", "in");
    const seam = page.getByTestId("comparison-row").first().getByTestId("seam");
    await expect(seam).toHaveAttribute("data-relation", "differs");
    await expect(seam).toHaveAttribute("data-tone", "distortion");
  });

  test("a PASS run inside an inconclusive case is scoped, not contradicted", async ({ page }) => {
    await page.goto(`/investigations/${INCONCLUSIVE}`);
    await settled(page);
    await expect(page.getByTestId("outcome")).toHaveText("Inconclusive");
    await expect(page.getByTestId("strip-verdict")).toHaveText("PASS");
    await expect(page.getByTestId("scope-note")).toContainText("reads Inconclusive");
    await page.getByTestId("scope-link").click();
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", NO_CLAIM_RUN);
    await expect(page.getByTestId("scope-note")).toHaveCount(0);
  });

  test("the seal is square to the grid and never carries an offset", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    const transform = await page
      .getByTestId("oracle-seal")
      .first()
      .evaluate((el) => getComputedStyle(el).transform);
    expect(["none", "matrix(1, 0, 0, 1, 0, 0)"]).toContain(transform);
  });

  test("nothing decorative exists to be mistaken for evidence", async ({ page }) => {
    for (const url of ["/", `/investigations/${VIOLATION}`]) {
      await page.goto(url);
      await settled(page);
      await expect(page.locator("[data-rf-decorative]")).toHaveCount(0);
      await expect(page.locator(".rf-echo, .rf-crack, .rf-plane")).toHaveCount(0);
    }
  });

  test("the landing keeps the qualifying disclosure and points at a real failure", async ({ page }) => {
    await page.goto("/");
    await settled(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("MOODY BLUES");
    await expect(page.getByRole("heading", { level: 2 }).first()).toHaveText(
      "What the agent reported. What reality recorded.",
    );
    await expect(page.getByTestId("hero")).toContainText(
      "MOODY BLUES investigates the gap between an AI agent's reported outcome and what actually happened.",
    );
    await expect(page.getByText("not concealment").first()).toBeVisible();
    await page.getByTestId("hero-how").click();
    await expect(page).toHaveURL(/#how$/);
    await page.getByTestId("hero-cta").click();
    await expect(page).toHaveURL(new RegExp(VIOLATION));
    await expect(page.getByRole("main").getByTestId("strip-verdict")).toHaveText("VIOLATION");
  });

  test("the screens ask only for read-only evidence, and nothing leaves the origin", async ({ page }) => {
    const seen: string[] = [];
    page.on("request", (r) => seen.push(r.url()));
    for (const url of ["/", `/investigations/${VIOLATION}`, `/investigations/${VIOLATION}?view=evidence`]) {
      await page.goto(url);
      await settled(page);
    }
    const origin = new URL(page.url()).origin;
    expect(seen.filter((u) => !u.startsWith(origin) && !u.startsWith("data:"))).toEqual([]);
    expect(seen.filter((u) => u.includes("/api/operator"))).toEqual([]);
  });
});

test.describe("incomplete and refused evidence", () => {
  test("a run that does not exist shows no verdict and no headline", async ({ page }) => {
    await page.goto(runUrl(VIOLATION, "run_000000000000"));
    await settled(page);
    await expect(page.getByTestId("evidence-failure")).toHaveAttribute("data-kind", "not_found");
    await expect(page.getByTestId("strip-verdict")).toHaveCount(0);
    await expect(page.getByTestId("headline")).toHaveCount(0);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("the raw view of a missing run refuses as well", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}?view=evidence&run=run_000000000000`);
    await settled(page);
    await expect(page.getByTestId("evidence-failure")).toHaveAttribute("data-kind", "not_found");
    await expect(page.getByTestId("raw-evidence-view")).toHaveCount(0);
  });
});

test.describe("navigation", () => {
  test("the chosen run survives every tab and the back button", async ({ page }) => {
    const run = "run_d48284d5a019";
    await page.goto(runUrl(VIOLATION, run));
    await settled(page);
    await page.getByTestId("tab-evidence").click();
    await expect(page).toHaveURL(new RegExp(`view=evidence&run=${run}`));
    await expect(page.getByTestId("raw-evidence-view")).toHaveAttribute("data-run", run);
    await page.getByTestId("tab-timeline").click();
    await expect(page).toHaveURL(new RegExp(`view=timeline&run=${run}`));
    await page.getByTestId("tab-reality").click();
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", run);
    await page.goBack();
    await expect(page).toHaveURL(/view=timeline/);
    await page.goBack();
    await expect(page.getByTestId("raw-evidence-view")).toHaveAttribute("data-run", run);
  });

  test("a call leads to its journal record, and the record leads back", async ({ page }) => {
    await page.goto(runUrl(VIOLATION, FALSE_RUN));
    await settled(page);
    const call = page.getByTestId("call-5");
    await call.locator("summary").click();
    await call.getByTestId("trace-link").click();
    await expect(page).toHaveURL(/view=timeline.*call=5/);
    const focused = page.locator('[data-focus="exact"]');
    await expect(focused).toHaveCount(2); // the call, and the fault delivered on it
    await expect(focused.first()).toBeInViewport();
    await expect(focused.first().locator("details")).toHaveJSProperty("open", true);
    await focused.first().getByTestId("open-comparison").click();
    await expect(page).toHaveURL(new RegExp(`run=${FALSE_RUN}#call-5$`));
    await expect(page.getByTestId("call-5")).toBeInViewport();
  });

  test("a deep link opened fresh lands on its target", async ({ page }) => {
    await page.goto(`${runUrl(VIOLATION, FALSE_RUN)}#call-7`);
    await settled(page);
    await expect(page.getByTestId("call-7")).toBeInViewport();
    await expect(page.getByTestId("call-7").locator("details")).toHaveJSProperty("open", true);
    await page.goto(`/investigations/${VIOLATION}?view=timeline&show=all&run=${FALSE_RUN}&call=5#trace`);
    await settled(page);
    await expect(page.locator("#trace")).toBeInViewport();
  });

  test("a record links to the call that committed it", async ({ page }) => {
    await page.goto(runUrl(VIOLATION, FALSE_RUN));
    await settled(page);
    await page.getByTestId("record-call-link").first().click();
    await expect(page).toHaveURL(/#call-4$/);
    await expect(page.getByTestId("call-4")).toBeInViewport();
  });

  test("the hypothesis behind a run is one step away", async ({ page }) => {
    await page.goto(runUrl(VIOLATION, FALSE_RUN));
    await settled(page);
    await page.getByTestId("deeper-investigator").click();
    await expect(page).toHaveURL(/view=investigator.*#h5$/);
    await expect(page.getByTestId("hypothesis-h5")).toBeInViewport();
  });

  test("raw evidence holds the recorded fields, including the fault list", async ({ page }) => {
    const run = await api<Run>(`/investigations/${VIOLATION}/runs/${FALSE_RUN}`);
    await page.goto(`/investigations/${VIOLATION}?view=evidence&run=${FALSE_RUN}`);
    await settled(page);
    const view = page.getByTestId("raw-evidence-view");
    await expect(view).toContainText(run.run_id);
    await expect(view).toContainText(run.experiment_id);
    await expect(view).toContainText(run.agent.termination);
    await expect(page.getByTestId("fault-list").locator("li")).toHaveCount(2);
    await expect(page.getByTestId("raw-findings").locator("tbody tr")).toHaveCount(run.actual.findings.length);
  });
});

test.describe("the investigation journey", () => {
  const investigator = (id: string) => `/investigations/${id}?view=investigator`;
  const timeline = (id: string) => `/investigations/${id}?view=timeline`;

  test("every experiment in the Investigator states its own run's recorded result", async ({ page }) => {
    test.slow();
    for (const id of ALL) {
      await page.goto(investigator(id));
      await settled(page);
      const { runs } = await api<Runs>(`/investigations/${id}/runs`);
      for (const { run_id: runId } of runs) {
        const run = await api<Run>(`/investigations/${id}/runs/${runId}`);
        const trial = page.getByTestId(`trial-${runId}`);
        await expect(trial).toHaveAttribute("data-verdict", run.verdict);
        await expect(trial.getByTestId("trial-verdict")).toHaveText(run.verdict);
        await expect(trial.getByTestId("trial-claim")).toHaveText(run.agent.claim?.status ?? "no valid claim");
        await expect(trial.getByTestId("trial-faults")).toHaveText(String(run.faults_delivered));
        await expect(trial.getByTestId("trial-discrepancies")).toHaveText(String(run.discrepancies.length));
      }
    }
  });

  test("a hypothesis is never styled as a verdict", async ({ page }) => {
    await page.goto(investigator(VIOLATION));
    await settled(page);
    const row = page.getByTestId("hypothesis-h5").locator("summary").first();
    await expect(row).toContainText("Model: supported");
    await expect(page.getByTestId("hypothesis-h5").locator('[data-stage="hypothesis"]')).toContainText(
      "Model's proposal, not a finding",
    );
    await expect(page.getByTestId("hypothesis-h5").locator('[data-stage="decision"]')).toContainText(
      "The model's assessment: supported",
    );
  });

  test("a recorded reason is labeled the model's, and shows what it cited", async ({ page }) => {
    await page.goto(`${investigator(VIOLATION)}&cycle=h2#h2`);
    await settled(page);
    const decision = page.getByTestId("hypothesis-h2").locator('[data-stage="decision"]');
    await expect(decision).toContainText("The model's stated reason for the next step, citing obs_1, obs_2");
    await expect(decision).toContainText("A citation is not proof");
  });

  test("a planned experiment has no reason invented for it", async ({ page }) => {
    await page.goto(investigator(RECOVERY));
    await settled(page);
    await expect(page.getByTestId("investigator-view")).not.toContainText("stated reason");
    await expect(page.getByTestId("decision-h1")).toHaveAttribute("data-kind", "planned");
  });

  test("a refused program carries no place in the sequence", async ({ page }) => {
    await page.goto(`${investigator(INCONCLUSIVE)}&cycle=prop_3#prop_3`);
    await settled(page);
    const cycle = page.getByTestId("program-prop_3");
    await expect(cycle).toContainText("2 generated programs refused before execution");
    await expect(cycle).toContainText("Refused: Truncated response");
    await expect(cycle).not.toContainText("First experiment");
    await expect(cycle).toContainText("Nothing ran");
  });

  test("the next decision leads to the next hypothesis, and back returns", async ({ page }) => {
    await page.goto(`${investigator(VIOLATION)}&cycle=h1#h1`);
    await settled(page);
    await page.getByTestId("next-h1").click();
    await expect(page).toHaveURL(/cycle=h2#h2$/);
    await expect(page.getByTestId("hypothesis-h2").locator("details").first()).toHaveJSProperty("open", true);
    await expect(page.getByTestId("hypothesis-h2")).toBeInViewport();
    await page.goBack();
    await expect(page).toHaveURL(/cycle=h1#h1$/);
    await expect(page.getByTestId("hypothesis-h1").locator("details").first()).toHaveJSProperty("open", true);
  });

  test("the default timeline shows milestones, and a run's trace opens in place", async ({ page }) => {
    await page.goto(timeline(VIOLATION));
    await settled(page);
    const entries = (await api<{ entries: { seq: number; stage: string }[] }>(
      `/investigations/${VIOLATION}/timeline`,
    )).entries;
    const verdict = entries.find((e) => e.stage === "oracle_verdict")!;
    const fault = entries.find((e) => e.stage === "fault_delivered")!;
    await expect(page.getByTestId(`step-${verdict.seq}`)).toBeVisible();
    await expect(page.getByTestId(`step-${fault.seq}`)).toBeHidden();
    const trace = page.locator(".rf-trace-group").first();
    await trace.locator("summary").first().focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId(`step-${fault.seq}`)).toBeVisible();
  });

  test("only a verified violation is marked, on every case", async ({ page }) => {
    for (const id of ALL) {
      const { runs } = await api<Runs>(`/investigations/${id}/runs`);
      await page.goto(timeline(id));
      await settled(page);
      await expect(page.getByTestId("discrepancy-mark")).toHaveCount(
        runs.filter((r) => r.verdict === "VIOLATION").length,
      );
    }
    await page.goto(timeline(RECOVERY));
    await settled(page);
    const coral = await page.locator(".rf-step").evaluateAll((els) =>
      els.filter((el) => {
        const dot = getComputedStyle(el, "::before").backgroundColor;
        return dot === "rgb(240, 112, 90)";
      }).length,
    );
    expect(coral).toBe(0);
  });

  test("selecting an event explains it and gives its evidence and its links", async ({ page }) => {
    await page.goto(`${timeline(VIOLATION)}&run=${FALSE_RUN}`);
    await settled(page);
    const step = page.locator('.rf-step[data-verdict="VIOLATION"]');
    await step.locator("summary").first().click();
    await expect(step).toContainText("not why it came about");
    await expect(step).toContainText("experiment journal, seq");
    await expect(step.getByTestId("event-link")).toHaveAttribute("href", new RegExp(`run=${FALSE_RUN}`));
    await step.getByTestId("open-comparison").click();
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", FALSE_RUN);
  });

  test("an event link opened fresh selects that event, even bookkeeping behind a fold", async ({ page }) => {
    const entries = (await api<{ entries: { seq: number; stage: string }[] }>(
      `/investigations/${VIOLATION}/timeline`,
    )).entries;
    for (const stage of ["oracle_verdict", "fault_delivered", "observation"]) {
      const { seq } = entries.find((e) => e.stage === stage)!;
      await page.goto(`${timeline(VIOLATION)}&event=${seq}#event-${seq}`);
      await settled(page);
      const step = page.getByTestId(`step-${seq}`);
      await expect(step).toHaveAttribute("data-focus", "exact");
      await expect(step.locator("details").first()).toHaveJSProperty("open", true);
      await expect(step).toBeInViewport();
    }
  });

  test("a hypothesis on the timeline opens in the Investigator, keeping the run", async ({ page }) => {
    await page.goto(`${timeline(VIOLATION)}&run=${FALSE_RUN}`);
    await settled(page);
    const step = page.locator('.rf-step[data-stage="hypothesis_revised"]').first();
    await step.locator("summary").first().click();
    await step.getByTestId("open-hypothesis").click();
    await expect(page).toHaveURL(new RegExp(`view=investigator.*run=${FALSE_RUN}.*#h2$`));
    await expect(page.getByTestId("hypothesis-h2").locator("details").first()).toHaveJSProperty("open", true);
  });

  test("the overview answers from the evidence and leads to each view", async ({ page }) => {
    const run = await api<Run>(`/investigations/${VIOLATION}/runs/${FALSE_RUN}`);
    await page.goto(`/investigations/${VIOLATION}?view=overview`);
    await settled(page);
    await expect(page.getByTestId("strip-verdict")).toHaveText(run.verdict);
    await expect(page.getByTestId("overview-answers")).toContainText("Duplicate side effect");
    await expect(page.getByTestId("overview-answers")).toContainText("interpretation, not a verdict");
    await expect(page.getByTestId("overview-causal")).toContainText("None in this record");
    await page.getByTestId("ladder-h5").click();
    await expect(page.getByTestId("hypothesis-h5").locator("details").first()).toHaveJSProperty("open", true);
  });

  test("causal evidence stays neutral and leads to the method", async ({ page }) => {
    await page.goto(runUrl(VIOLATION, FALSE_RUN));
    await settled(page);
    await expect(page.getByTestId("causal-evidence")).not.toContainText("3/3");
    await page.getByTestId("method-link").click();
    await expect(page).toHaveURL(/\/#method$/);
    await expect(page.getByTestId("method")).toBeInViewport();
    await expect(page.getByTestId("method")).toContainText("A rerun is not a control");
  });

  test("the landing explains four stages and keeps How it works without the evidence", async ({ page }) => {
    await page.goto("/");
    await settled(page);
    await expect(page.locator(".rf-how li h3")).toHaveText(["Hypothesize", "Experiment", "Observe", "Verify"]);
    await page.getByTestId("hero-how").click();
    await expect(page).toHaveURL(/#how$/);
    await expect(page.locator("#how")).toBeInViewport();
    const signature = await page.getByTestId("signature").boundingBox();
    const how = await page.locator("#how").boundingBox();
    const list = await page.locator("#investigations").boundingBox();
    expect(signature!.y).toBeLessThan(how!.y);
    expect(how!.y).toBeLessThan(list!.y);
  });

  test("each tab is reachable at phone widths, with nothing hidden in overflow", async ({ page }) => {
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/investigations/${VIOLATION}`);
      await settled(page);
      const nav = page.locator(".rf-tabs");
      const clipped = await nav.evaluate((el) => el.scrollWidth - el.clientWidth);
      expect(clipped, `${width}px`).toBeLessThanOrEqual(0);
      for (const key of ["overview", "reality", "timeline", "investigator", "evidence"]) {
        const box = await page.getByTestId(`tab-${key}`).boundingBox();
        expect(box!.x, key).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width, key).toBeLessThanOrEqual(width);
      }
    }
    const tabs = page.locator(".rf-tabs");
    await expect(tabs.getByRole("link", { name: "Raw evidence" })).toBeVisible();
    await expect(tabs.getByRole("link", { name: "Reality Comparison" })).toBeVisible();
  });

  test("the investigation and the followed run stay named on every view", async ({ page }) => {
    for (const view of ["overview", "timeline", "investigator", "evidence"]) {
      await page.goto(`/investigations/${VIOLATION}?view=${view}&run=${FALSE_RUN}`);
      await settled(page);
      await expect(page.getByTestId("investigation-id")).toHaveText(VIOLATION);
      await expect(page.getByTestId("tab-reality")).toHaveAttribute("href", new RegExp(`run=${FALSE_RUN}`));
      await expect(page.getByTestId("run-following")).toContainText("Run 5 of 5");
      await expect(page.getByTestId("run-following")).toContainText("VIOLATION");
      await expect(page.locator("h1")).toHaveCount(1);
    }
    await page.getByTestId("run-clear").click();
    await expect(page).not.toHaveURL(/run=/);
    await expect(page.getByTestId("run-following")).toHaveCount(0);
  });

  test("a run from elsewhere is named as foreign, not followed", async ({ page }) => {
    await page.goto(`${timeline(VIOLATION)}&run=run_000000000000`);
    await settled(page);
    await expect(page.getByTestId("run-following")).toContainText("not part of this investigation");
  });
});

test.describe("access", () => {
  for (const viewport of VIEWPORTS) {
    test(`the four answers fit the first screen on every run at ${viewport.width}px`, async ({ page }) => {
      test.slow();
      await page.setViewportSize(viewport);
      await eachRun(async (id, run) => {
        await page.goto(runUrl(id, run.run_id));
        await settled(page);
        for (const testId of ["headline", "mission", "strip-claim", "strip-state", "strip-verdict"]) {
          const box = await page.getByRole("main").getByTestId(testId).boundingBox();
          expect(box, `${run.run_id} ${testId}`).not.toBeNull();
          expect(box!.y + box!.height, `${run.run_id} ${testId}`).toBeLessThanOrEqual(viewport.height);
        }
      });
    });

    test(`nothing overflows or covers a recorded value at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      for (const url of [
        "/",
        `/investigations/${VIOLATION}`,
        `/investigations/${VIOLATION}?view=timeline&show=all`,
        `/investigations/${VIOLATION}?view=investigator`,
        `/investigations/${VIOLATION}?view=evidence`,
        `/investigations/${VIOLATION}?view=overview`,
        `/investigations/${VIOLATION}?view=timeline`,
        `/investigations/${INCONCLUSIVE}?view=investigator`,
        `/investigations/${RECOVERY}`,
        runUrl(INCONCLUSIVE, NO_CLAIM_RUN),
        "/design-lab",
        "/design-lab/system",
      ]) {
        await page.goto(url);
        await settled(page);
        // Opened, so the check also covers what a reader sees after expanding everything.
        await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, url).toBeLessThanOrEqual(0);
        const broken = await page.locator(".rf-seal-label").evaluateAll((els) =>
          els
            .filter((el) => {
              const range = document.createRange();
              range.selectNodeContents(el);
              return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size > 1;
            })
            .map((el) => el.textContent),
        );
        expect(broken, url).toEqual([]);
        const covered = await page
          .locator(".rf-slab-id, .rf-claim-status, .rf-count-number, .rf-seal-label, .rf-call-value")
          .evaluateAll((els) =>
            els
              .filter((el) => {
                el.scrollIntoView({ block: "center" });
                const r = el.getBoundingClientRect();
                const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return !hit || !(el === hit || el.contains(hit) || hit.contains(el));
              })
              .map((el) => el.textContent),
          );
        expect(covered, url).toEqual([]);
      }
    });

    test(`axe finds no violation at ${viewport.width}px`, async ({ page }) => {
      test.slow();
      await page.setViewportSize(viewport);
      for (const url of [
        "/",
        `/investigations/${VIOLATION}`,
        `/investigations/${RECOVERY}`,
        runUrl(INCONCLUSIVE, NO_CLAIM_RUN),
        `/investigations/${VIOLATION}?view=timeline`,
        `/investigations/${VIOLATION}?view=investigator`,
        `/investigations/${VIOLATION}?view=evidence`,
        `/investigations/${VIOLATION}?view=overview`,
        `/investigations/${VIOLATION}?view=timeline&show=all`,
        `/investigations/${RECOVERY}?view=investigator`,
        `/investigations/${INCONCLUSIVE}?view=investigator`,
        `/investigations/${INCONCLUSIVE}?view=timeline`,
      ]) {
        await page.goto(url);
        await settled(page);
        // Closed disclosures hide their content from axe, so everything is opened first.
        await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
          .analyze();
        const found = results.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => n.target.join(" ")).slice(0, 5),
        }));
        expect(found, url).toEqual([]);
      }
    });
  }

  test("primary controls are at least 44px on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const targets: [string, string][] = [
      ["/", '[data-testid="hero-cta"], [data-testid="hero-how"], [data-testid="open-signature"], header nav a, .rf-wordmark'],
      [
        `/investigations/${VIOLATION}`,
        ".rf-crumb-back, .rf-tabs a, .rf-run, .rf-disclose summary, .rf-call summary, .rf-deeper a, [data-testid=\"copy-id\"]",
      ],
      [`/investigations/${VIOLATION}?view=timeline`, ".rf-step > details > summary, .rf-trace-group > details > summary, [data-testid=\"timeline-scope\"]"],
      [`/investigations/${VIOLATION}?view=investigator`, ".rf-cycle > details > summary, .rf-disclose summary"],
      [`/investigations/${VIOLATION}?view=overview`, ".rf-ladder a, .rf-deeper a"],
    ];
    for (const [url, selector] of targets) {
      await page.goto(url);
      await settled(page);
      const small = await page.locator(selector).evaluateAll((els) =>
        els
          .filter((el) => (el as HTMLElement).offsetParent !== null)
          .map((el) => ({ el: el.textContent?.slice(0, 30), h: el.getBoundingClientRect().height }))
          .filter((b) => b.h < 44),
      );
      expect(small, url).toEqual([]);
    }
  });

  test("headings never skip a level, on any view, with everything open", async ({ page }) => {
    for (const url of [
      "/",
      `/investigations/${VIOLATION}?view=overview`,
      `/investigations/${VIOLATION}`,
      `/investigations/${VIOLATION}?view=timeline`,
      `/investigations/${VIOLATION}?view=investigator`,
      `/investigations/${VIOLATION}?view=evidence`,
      `/investigations/${INCONCLUSIVE}?view=investigator`,
    ]) {
      await page.goto(url);
      await settled(page);
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
      const levels = await page
        .locator("main h1, main h2, main h3, main h4")
        .evaluateAll((els) => els.map((el) => Number(el.tagName[1])));
      expect(levels[0], url).toBe(1);
      expect(levels.filter((l) => l === 1), url).toHaveLength(1);
      levels.forEach((level, i) => {
        if (i) expect(level - levels[i - 1], `${url} heading ${i}`).toBeLessThanOrEqual(1);
      });
    }
  });

  test("the current view is exposed to assistive technology, under its full name", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/investigations/${VIOLATION}?view=evidence`);
    await settled(page);
    const nav = page.getByRole("navigation", { name: "Investigation views" });
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(nav.getByRole("link", { name: "Raw evidence" })).toHaveAttribute("aria-current", "page");
    const snapshot = await nav.ariaSnapshot();
    for (const name of ["Overview", "Reality Comparison", "Timeline", "Investigator", "Raw evidence"]) {
      expect(snapshot).toContain(name);
    }
  });

  test("the keyboard walks the tabs and opens a cycle and a trace", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}?view=investigator`);
    await settled(page);
    await page.waitForLoadState("networkidle");
    await page.getByTestId("tab-overview").focus();
    for (const key of ["reality", "timeline", "investigator", "evidence"]) {
      await page.keyboard.press("Tab");
      await expect(page.getByTestId(`tab-${key}`)).toBeFocused();
    }
    const row = page.getByTestId("hypothesis-h1").locator("summary").first();
    await row.focus();
    await page.keyboard.press("Space");
    await expect(page.getByTestId("hypothesis-h1").locator("details").first()).toHaveJSProperty("open", true);
    const ring = await row.evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(ring).toBe("solid");
  });

  test("a phone stacks the comparison and keeps both labels", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    const row = page.getByTestId("comparison-row").first();
    const agent = await row.locator('[data-reality="agent"]').boundingBox();
    const actual = await row.locator('[data-reality="actual"]').boundingBox();
    expect(actual!.y).toBeGreaterThan(agent!.y + agent!.height - 1);
    expect(Math.abs(actual!.x - agent!.x)).toBeLessThan(1);
    const label = await row
      .locator('[data-reality="actual"] > .rf-label')
      .evaluate((el) => getComputedStyle(el, "::before").content);
    expect(label).toContain("Authoritative");
  });

  test("evidence text is not clipped at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    const clipped = await page
      .locator(".rf-slab-id, .rf-call-value, .rf-findings code, [data-testid='first-told']")
      .evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth + 1).length);
    expect(clipped).toBe(0);
  });

  test("the keyboard reaches every control, with a strong focus ring", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    await page.waitForLoadState("networkidle");
    const tab = page.getByTestId("tab-timeline");
    await tab.focus();
    const ring = await tab.evaluate((el) => {
      const s = getComputedStyle(el);
      return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) };
    });
    expect(ring.style).toBe("solid");
    expect(ring.width).toBeGreaterThanOrEqual(2);
    const summary = page.getByTestId("call-1").locator("summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("call-1").locator("details")).toHaveJSProperty("open", true);
    await page.getByTestId("run-run_d48284d5a019").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", "run_d48284d5a019");
  });

  test("the comparison reads in order to assistive technology", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    const h1 = await page.locator("h1").ariaSnapshot();
    expect(h1.match(/Reality recorded a duplicate/g)?.length).toBe(1);
    const row = await page.getByTestId("comparison-row").first().ariaSnapshot();
    expect(row.indexOf("What it reported")).toBeLessThan(row.indexOf("The two sides differ"));
    expect(row.indexOf("The two sides differ")).toBeLessThan(row.indexOf("What committed"));
    await expect(page.getByRole("region", { name: "Outcome" })).toBeVisible();
  });

  test("meaning is never carried by colour alone", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}`);
    await settled(page);
    await page.addStyleTag({ content: "* { color: #888 !important; border-color: #888 !important; }" });
    await expect(page.getByTestId("strip-verdict")).toHaveText("VIOLATION");
    await expect(page.locator(".rf-seal-mark").first()).toHaveText("✕");
    await expect(page.locator(".rf-slab-flag").first()).toHaveText("✕ Duplicate");
    await expect(page.getByTestId("call-5").locator(".rf-call-fault")).toHaveText("stale_read");
  });

  test("reduced motion: nothing runs, and at rest nothing runs for anyone", async ({ browser, page }) => {
    const context = await browser.newContext({
      reducedMotion: "reduce",
      viewport: { width: 1440, height: 900 },
    });
    const reduced = await context.newPage();
    for (const url of ["/", `/investigations/${VIOLATION}`]) {
      await reduced.goto(url);
      await settled(reduced);
      expect(await reduced.evaluate(() => document.getAnimations().length)).toBe(0);
      await page.goto(url);
      await settled(page);
      expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
    }
    await context.close();
  });

  test("the signature pages stay cheap to render", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const url of ["/", `/investigations/${VIOLATION}`]) {
      await page.goto(url);
      await settled(page);
      const metrics = await page.evaluate(
        () =>
          new Promise<{ cls: number; lcp: number; nodes: number }>((resolve) => {
            let cls = 0;
            let lcp = 0;
            new PerformanceObserver((list) => {
              for (const e of list.getEntries() as (PerformanceEntry & { value: number })[]) cls += e.value;
            }).observe({ type: "layout-shift", buffered: true });
            new PerformanceObserver((list) => {
              lcp = list.getEntries().at(-1)?.startTime ?? 0;
            }).observe({ type: "largest-contentful-paint", buffered: true });
            setTimeout(
              () =>
                resolve({
                  cls: Math.round(cls * 1000) / 1000,
                  lcp: Math.round(lcp),
                  nodes: document.querySelectorAll("*").length,
                }),
              250,
            );
          }),
      );
      console.log(url, JSON.stringify(metrics));
      expect(metrics.cls).toBeLessThan(0.1);
    }
  });

  test("text and status pairs meet WCAG AA", async ({ page }) => {
    await page.goto("/design-lab/system");
    await settled(page);
    const pairs = [
      ["--rf-text", "--rf-surface-base"],
      ["--rf-text", "--rf-surface-raised"],
      ["--rf-text", "--rf-surface-high"],
      ["--rf-text-muted", "--rf-surface-base"],
      ["--rf-text-muted", "--rf-surface-raised"],
      ["--rf-text-muted", "--rf-surface-high"],
      ["--rf-text-faint", "--rf-surface-base"],
      ["--rf-text-faint", "--rf-surface-raised"],
      ["--rf-text-faint", "--rf-surface-high"],
      ["--rf-agent", "--rf-surface-base"],
      ["--rf-agent", "--rf-surface-raised"],
      ["--rf-actual", "--rf-surface-base"],
      ["--rf-actual", "--rf-surface-raised"],
      ["--rf-divergence", "--rf-surface-base"],
      ["--rf-divergence", "--rf-surface-raised"],
      ["--rf-status-pass", "--rf-surface-base"],
      ["--rf-status-inconclusive", "--rf-surface-base"],
      ["--rf-oracle-ink", "--rf-oracle-surface"],
      ["--rf-oracle-ink", "--rf-oracle-rule"],
      ["--rf-status-ink", "--rf-status-pass"],
      ["--rf-status-ink", "--rf-status-violation"],
      ["--rf-status-ink", "--rf-status-inconclusive"],
    ];
    const ratios = await page.evaluate((list) => {
      const root = document.body;
      const rgb = (name: string) => {
        const probe = document.createElement("div");
        probe.style.color = `var(${name})`;
        root.append(probe);
        const canvas = document.createElement("canvas").getContext("2d")!;
        canvas.fillStyle = getComputedStyle(probe).color;
        canvas.fillRect(0, 0, 1, 1);
        probe.remove();
        return [...canvas.getImageData(0, 0, 1, 1).data].slice(0, 3);
      };
      const luminance = (c: number[]) => {
        const [r, g, b] = c.map((v) => {
          const s = v / 255;
          return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      return list.map(([fg, bg]) => {
        const [a, b] = [luminance(rgb(fg)), luminance(rgb(bg))].sort((x, y) => y - x);
        return { fg, bg, ratio: Math.round(((a + 0.05) / (b + 0.05)) * 100) / 100 };
      });
    }, pairs);
    console.log(JSON.stringify(ratios));
    for (const { fg, bg, ratio } of ratios) expect(ratio, `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  });
});
