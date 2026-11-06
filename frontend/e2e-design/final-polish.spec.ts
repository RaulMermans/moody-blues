import { expect, type Page, test } from "@playwright/test";

import { BACKEND_URL } from "../playwright.design.config";

// Sprint 13, against the real recorded evidence. Expected values come from the API, never from this file.
const VIOLATION = "inv_d0bc87de6010";
const CASES = [VIOLATION, "inv_4e32358d2ff9", "inv_8058b370bc59", "inv_c803b47c336a", "inv_5c9f95de6c09"];

interface Run {
  run_id: string;
  verdict: string;
}
interface RunList {
  primary_run_id: string | null;
  runs: Run[];
}

const api = async <T>(path: string): Promise<T> => (await (await fetch(`${BACKEND_URL}${path}`)).json()) as T;
const investigator = (id: string) => `/investigations/${id}?view=investigator`;
const overview = (id: string) => `/investigations/${id}?view=overview`;

/** Streamed content waits in a hidden segment until it is revealed, and nothing in there can take focus. */
async function settled(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

async function noSidewaysScroll(page: Page) {
  const extra = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(extra).toBeLessThanOrEqual(0);
}

test.describe("public status", () => {
  test("the status route carries named fields only", async ({ request }) => {
    const body = await (await request.get("/api/status")).text();
    for (const forbidden of ["MOODY_", "VULTR_API", "detail", "environment", "requestId", "uptime", "req_", "127.0.0.1"]) {
      expect(body, forbidden).not.toContain(forbidden);
    }
    const status = JSON.parse(body) as { backend: string; integrations: { name: string; state: string }[] };
    expect(status.backend).toBe("connected");
    for (const item of status.integrations) expect(Object.keys(item).sort()).toEqual(["name", "state"]);
  });

  test("the landing speaks in plain words", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("backend-status")).toHaveAttribute("data-state", "connected");
    const text = await page.locator("main").innerText();
    for (const forbidden of ["MOODY_", "API_KEY", "req_", "development", "Docker daemon"]) {
      expect(text, forbidden).not.toContain(forbidden);
    }
    await expect(page.getByTestId("integration-docker_sandbox")).toContainText("Experiment sandbox");
    await expect(page.getByTestId("integration-vultr_inference")).toContainText("Live inference");
  });

  test("the landing list never repeats a word as two tags", async ({ page }) => {
    await page.goto("/");
    for (const id of CASES) {
      const tags = await page.getByTestId(`investigation-${id}`).locator("span.font-mono, span.border").allInnerTexts();
      expect(new Set(tags).size, id).toBe(tags.length);
    }
  });
});

test.describe("overview", () => {
  for (const id of CASES) {
    test(`${id}: the next step and tally follow the record`, async ({ page }) => {
      const list = await api<RunList>(`/investigations/${id}/runs`);
      await page.goto(overview(id));
      const primary = page.getByTestId("overview-primary");
      const shown = list.runs.find((r) => r.run_id === list.primary_run_id);
      expect(shown).toBeTruthy();
      // Only the Oracle's verdict on the shown run may call it a finding.
      if (shown?.verdict === "VIOLATION") await expect(primary).toContainText("verified finding");
      else await expect(primary).not.toContainText("finding");
      await expect(primary).toHaveAttribute("href", new RegExp(`view=reality&run=${shown?.run_id}`));

      const tally = page.getByTestId("overview-tally");
      for (const verdict of ["VIOLATION", "PASS", "INCONCLUSIVE"]) {
        const n = list.runs.filter((r) => r.verdict === verdict).length;
        const cell = tally.getByTestId(`tally-${verdict}`);
        if (n) await expect(cell).toHaveText(String(n));
        else await expect(cell).toHaveCount(0);
      }
    });
  }

  for (const id of CASES) {
    test(`${id}: the Overview qualifies a run exactly as the Comparison does`, async ({ page }) => {
      await settled(page, `/investigations/${id}`);
      const notes = page.getByTestId("scope-note");
      const expected = (await notes.count()) ? await notes.textContent() : null;
      await settled(page, overview(id));
      if (expected) await expect(notes).toHaveText(expected);
      else await expect(notes).toHaveCount(0);
    });
  }

  test("a run whose verdict differs from its investigation is never left unexplained", async ({ page }) => {
    await settled(page, overview("inv_5c9f95de6c09"));
    await expect(page.getByTestId("outcome")).toHaveText("Inconclusive");
    await expect(page.getByTestId("strip-verdict")).toHaveText("PASS");
    await expect(page.getByTestId("scope-note")).toBeVisible();
  });

  test("a recorded case still says it is not running, with its limits folded", async ({ page }) => {
    await page.goto(overview(VIOLATION));
    await expect(page.getByTestId("overview-identity")).toContainText("It is not running now");
    await expect(page.getByTestId("about-panel")).toHaveJSProperty("open", false);
    await page.getByTestId("about-panel").locator("summary").first().click();
    await expect(page.getByTestId("integrity")).toBeVisible();
  });

  test("an unknown run id never reads as no run having taken place", async ({ page }) => {
    await page.goto(`${overview(VIOLATION)}&run=run_000000000000`);
    await expect(page.getByTestId("run-following")).toContainText("not part of this investigation");
    await expect(page.getByTestId("overview-no-run")).toHaveCount(0);
    await expect(page.getByTestId("strip-verdict")).toHaveText("VIOLATION");
  });

  test("the primary action is reached by keyboard and opens the run", async ({ page }) => {
    await settled(page, overview(VIOLATION));
    await page.getByTestId("overview-primary").focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/view=reality&run=/);
  });
});

test.describe("investigator text", () => {
  for (const id of CASES) {
    test(`${id}: long recorded text is whole in the page`, async ({ page }) => {
      const detail = await api<{
        hypotheses: { predicted_observation: string; assessment_reasoning: string | null; hypothesis_id: string }[];
        conclusion: { reasoning: string } | null;
      }>(`/investigations/${id}`);
      await page.goto(investigator(id));
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
      const view = page.getByTestId("investigator-view");
      const dom = await view.textContent();
      const recorded = [
        ...detail.hypotheses.flatMap((h) => [h.predicted_observation, h.assessment_reasoning]),
        detail.conclusion?.reasoning,
      ].filter((t): t is string => !!t);
      for (const text of recorded) expect(dom).toContain(text);
      expect(recorded.length).toBeGreaterThan(0);
    });
  }

  test("a control appears only where lines are really cut", async ({ page }) => {
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await settled(page, investigator(VIOLATION));
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
      await page.waitForTimeout(150);
      const clamps = await page.locator(".rf-clamp").evaluateAll((els) =>
        els.map((el) => ({
          cut: el.scrollHeight > el.clientHeight + 1,
          control: el.nextElementSibling?.getAttribute("data-testid") === "clamp-toggle",
        })),
      );
      expect(clamps.length).toBeGreaterThan(0);
      for (const clamp of clamps) expect(clamp.control).toBe(clamp.cut);
    }
  });

  test("a folded cycle's text gets its control when the cycle opens", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await settled(page, investigator(VIOLATION));
    const cycle = page.getByTestId("hypothesis-h3");
    await expect(cycle.getByTestId("clamp-toggle")).toHaveCount(0);
    await cycle.locator("summary").first().click();
    await expect(cycle.getByTestId("clamp-toggle").first()).toBeVisible();
  });

  test("a hypothesis links back to the decision that led to it", async ({ page }) => {
    const detail = await api<{ hypotheses: { hypothesis_id: string; motivation: string | null }[] }>(
      `/investigations/${VIOLATION}`,
    );
    const reason = detail.hypotheses.find((h) => h.hypothesis_id === "h5")?.motivation;
    expect(reason).toBeTruthy();
    await settled(page, `${investigator(VIOLATION)}&cycle=h5#h5`);
    await page.getByTestId("why-h5").click();
    await expect(page).toHaveURL(/cycle=h4#decision-h4$/);
    const decision = page.locator("#decision-h4");
    await expect(decision).toBeInViewport();
    await expect(decision).toContainText(reason!);
    await expect(page.getByTestId("why-h1")).toHaveCount(0);
  });

  test("a planned case claims no reason it does not have", async ({ page }) => {
    await settled(page, investigator("inv_8058b370bc59"));
    await expect(page.locator('[data-testid^="why-"]')).toHaveCount(0);
  });

  test("a clamp opens from the keyboard and says so", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await settled(page, `${investigator(VIOLATION)}&cycle=h5#h5`);
    const toggle = page.getByTestId("hypothesis-h5").getByTestId("clamp-toggle").first();
    const text = page.getByTestId("hypothesis-h5").locator(".rf-clamp").first();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    const before = (await text.boundingBox())?.height ?? 0;
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveText("Show less");
    expect((await text.boundingBox())?.height ?? 0).toBeGreaterThan(before);
    await expect(toggle).toBeFocused();
    await page.keyboard.press("Space");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  test("without JavaScript nothing stays shortened", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto(`${investigator(VIOLATION)}&cycle=h5#h5`);
    const text = page.getByTestId("hypothesis-h5").locator(".rf-clamp").first();
    await expect(text).toHaveCSS("display", "block");
    await expect(page.getByTestId("clamp-toggle").first()).toBeHidden();
    await context.close();
  });

  for (const width of [320, 390, 720]) {
    test(`opened text and controls fit at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(investigator(VIOLATION));
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
      await expect(page.getByTestId("clamp-toggle").first()).toBeVisible();
      for (const toggle of await page.getByTestId("clamp-toggle").all()) await toggle.click();
      await noSidewaysScroll(page);
      const box = await page.getByTestId("clamp-toggle").first().boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    });
  }
});

test.describe("timeline completeness", () => {
  for (const id of CASES) {
    test(`${id}: every record is reachable, folded or not`, async ({ page }) => {
      const timeline = await api<{ total: number; entries: { seq: number; evidence: { record_sha256: string } }[] }>(
        `/investigations/${id}/timeline`,
      );
      await page.goto(`/investigations/${id}?view=timeline&show=all`);
      const steps = page.locator('[data-testid^="step-"]');
      await expect(steps).toHaveCount(timeline.entries.length);
      expect(timeline.entries.length).toBe(timeline.total);
      const seqs = await steps.evaluateAll((els) => els.map((e) => Number(e.getAttribute("data-testid")?.slice(5))));
      expect(seqs).toEqual(timeline.entries.map((e) => e.seq));
      const dom = await page.getByTestId("timeline-view").textContent();
      for (const entry of timeline.entries) expect(dom).toContain(entry.evidence.record_sha256);
    });
  }

  test("a record opens and closes from the keyboard", async ({ page }) => {
    await settled(page, `/investigations/${VIOLATION}?view=timeline`);
    const row = page.locator(".rf-step > details").first();
    await row.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(row).toHaveJSProperty("open", true);
    await page.keyboard.press("Enter");
    await expect(row).toHaveJSProperty("open", false);
  });
});

test.describe("keyboard walk", () => {
  for (const [name, path] of [
    ["landing", "/"],
    ["overview", overview(VIOLATION)],
    ["timeline", `/investigations/${VIOLATION}?view=timeline`],
    ["investigator", investigator(VIOLATION)],
  ] as const) {
    test(`${name}: every Tab stop is on screen and shows focus`, async ({ page }) => {
      await settled(page, path);
      for (let i = 0; i < 30; i++) {
        await page.keyboard.press("Tab");
        const stop = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement;
          const style = getComputedStyle(el);
          const box = el.getBoundingClientRect();
          return {
            tag: el.tagName,
            outline: style.outlineStyle,
            shadow: style.boxShadow,
            sized: box.width > 0 && box.height > 0,
          };
        });
        if (stop.tag === "BODY") break;
        expect(stop.sized, `stop ${i}`).toBe(true);
        expect(stop.outline !== "none" || stop.shadow !== "none", `stop ${i} ${stop.tag}`).toBe(true);
      }
    });
  }
});

test.describe("motion and structure", () => {
  test("a record settles when opened, unless motion is reduced", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}?view=timeline`);
    const row = page.locator(".rf-step > details").first();
    await row.locator("summary").click();
    await expect(row.locator(".rf-step-detail")).toHaveCSS("animation-name", "rf-reveal");

    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(row.locator(".rf-step-detail")).toHaveCSS("animation-name", "none");
    await page.goto(investigator(VIOLATION));
    await expect(page.locator(".rf-cycle > details[open] > .rf-cycle-body").first()).toHaveCSS("animation-name", "none");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("clamp-toggle").first()).toHaveCSS("transition-duration", "0s");
  });

  for (const [name, path] of [
    ["landing", "/"],
    ["overview", overview(VIOLATION)],
    ["comparison", `/investigations/${VIOLATION}`],
    ["timeline", `/investigations/${VIOLATION}?view=timeline`],
    ["investigator", investigator(VIOLATION)],
    ["evidence", `/investigations/${VIOLATION}?view=evidence`],
    ["containment", "/containment"],
  ] as const) {
    test(`${name}: one h1, and heading levels never skip`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const levels = await page
        .locator("main :is(h1,h2,h3,h4,h5,h6)")
        .evaluateAll((els) => els.map((e) => Number(e.tagName[1])));
      expect(levels.filter((l) => l === 1)).toHaveLength(1);
      for (let i = 1; i < levels.length; i++) expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
    });
  }
});
