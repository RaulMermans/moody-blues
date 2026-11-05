import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { BACKEND_URL } from "../playwright.design.config";

// The lab against the real evidence API. Expected values are read from the API, never written here.

const SHOTS = join(__dirname, "..", "..", "docs", "design", "screenshots");
const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
];
const ROUTES = [
  "/design-lab",
  "/design-lab/landing",
  "/design-lab/comparison",
  "/design-lab/system",
  "/design-lab/studies/a",
  "/design-lab/studies/b",
  "/design-lab/studies/c",
];

interface Customer {
  customer_id: string;
  role: string;
  flagged_duplicate: boolean;
}
interface Run {
  run_id: string;
  verdict: "PASS" | "VIOLATION" | "INCONCLUSIVE";
  discrepancies: unknown[];
  agent: {
    claim: { status: string; customer_id: string | null } | null;
    disclosure: unknown;
  };
  actual: { customers: Customer[]; findings: { code: string; severity: string }[] };
}
interface Listing {
  items: { investigation_id: string; summary: { case: { primary_run_id: string | null } | null } }[];
}

async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`);
  expect(res.ok, path).toBe(true);
  return (await res.json()) as T;
}

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
  test("every study and prototype, as rendered", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const [route, name] of [
      ["/design-lab/studies/a", "01-direction-a-reality-fracture"],
      ["/design-lab/studies/b", "02-direction-b-mirror-corruption"],
      ["/design-lab/studies/c", "03-direction-c-forensic-brutalism"],
      ["/design-lab/landing", "04-landing"],
    ]) {
      await page.goto(route);
      await shot(page, name);
    }
    await page.goto("/design-lab/comparison");
    await shot(page, "05-comparison-fold");
    await shot(page, "05-comparison-full", true);
    await page.goto("/design-lab/system");
    await shot(page, "09-system", true);

    const { items } = await api<Listing>("/investigations");
    const clean = items.find((i) => i.investigation_id === "inv_8058b370bc59");
    expect(clean).toBeTruthy();
    await page.goto("/design-lab/comparison?case=inv_8058b370bc59");
    await shot(page, "08-comparison-clean-case");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/design-lab/landing");
    await shot(page, "06-mobile-landing", true);
    await page.goto("/design-lab/comparison");
    await shot(page, "06-mobile-comparison", true);

    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/design-lab/comparison");
    await shot(page, "06-tablet-comparison", true);
  });

  test("reduced motion", async ({ browser }) => {
    const context = await browser.newContext({
      reducedMotion: "reduce",
      viewport: { width: 1440, height: 900 },
    });
    const page = await context.newPage();
    for (const [route, name] of [
      ["/design-lab/landing", "07-reduced-motion-landing"],
      ["/design-lab/comparison", "07-reduced-motion-comparison"],
    ]) {
      await page.goto(route);
      await settled(page);
      expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
      await shot(page, name);
    }
    await context.close();
  });
});

test.describe("truth", () => {
  test("every recorded case renders exactly what its evidence holds", async ({ page }) => {
    const { items } = await api<Listing>("/investigations");
    expect(items.length).toBeGreaterThanOrEqual(5);
    for (const item of items) {
      const id = item.investigation_id;
      const runId = item.summary.case?.primary_run_id;
      if (!runId) continue;
      const run = await api<Run>(`/investigations/${id}/runs/${runId}`);
      await page.goto(`/design-lab/comparison?case=${id}`);
      await settled(page);

      const added = run.actual.customers.filter((c) => c.role === "new");
      await expect(page.getByTestId("oracle-seal-label").first()).toHaveText(run.verdict);
      await expect(page.getByTestId("claim-status")).toHaveText(run.agent.claim?.status ?? "no valid claim");
      await expect(page.getByTestId("record-count")).toHaveText(String(added.length));
      await expect(page.getByTestId("discrepancy-count")).toHaveText(String(run.discrepancies.length));
      await expect(page.getByTestId("fracture-marker")).toHaveCount(run.discrepancies.length);

      // A slab is a real row: same ids, same count, nothing extra drawn as a record.
      const drawn = await page.getByTestId("record-slab").evaluateAll((slabs) =>
        slabs.map((s) => s.getAttribute("data-record")),
      );
      expect(drawn.sort()).toEqual(added.map((c) => c.customer_id).sort());
      await expect(page.locator('[data-flagged="true"]')).toHaveCount(
        added.filter((c) => c.flagged_duplicate).length,
      );

      // The frame breaks only for an Oracle VIOLATION.
      const expected =
        run.verdict === "VIOLATION"
          ? "violation"
          : run.verdict === "INCONCLUSIVE"
            ? "unresolved"
            : run.discrepancies.length
              ? "delivery"
              : "none";
      await expect(page.getByTestId("divergence-field")).toHaveAttribute("data-divergence", expected);
      const cut = await page.locator(".rf-plane-agent").evaluate((el) => getComputedStyle(el).clipPath);
      if (run.verdict === "VIOLATION") expect(cut).toContain("polygon");
      else expect(cut).toBe("none");
      await expect(page.locator(".rf-crack-main")).toHaveCount(run.verdict === "VIOLATION" ? 2 : 0);

      await expect(page.getByTestId("oracle-finding")).toHaveCount(
        run.actual.findings.filter((f) => f.severity === "violation").length,
      );
      if (run.agent.disclosure) await expect(page.getByTestId("disclosure")).toBeVisible();
      await expect(page.getByTestId("provenance")).toContainText("Recorded");
    }
  });

  test("a run the Oracle passed shows no failure effect", async ({ page }) => {
    const id = "inv_8058b370bc59";
    const { primary_run_id: runId } = await api<{ primary_run_id: string }>(`/investigations/${id}/runs`);
    const run = await api<Run>(`/investigations/${id}/runs/${runId}`);
    expect(run.verdict).toBe("PASS");
    expect(run.discrepancies.length).toBeGreaterThan(0);

    await page.goto(`/design-lab/comparison?case=${id}`);
    await settled(page);
    await expect(page.getByRole("heading", { name: "Fracture points" })).toHaveCount(0);
    await expect(page.getByTestId("fracture-marker")).toHaveCount(run.discrepancies.length);
    await expect(page.locator('[data-testid="fracture-marker"][data-tone="fracture"]')).toHaveCount(0);
    for (const selector of [".rf-frame-title .rf-display-layer", ".rf-echo-outline"]) {
      const shown = await page
        .locator(selector)
        .evaluateAll((els) => els.filter((el) => getComputedStyle(el).display !== "none").length);
      expect(shown, selector).toBe(0);
    }
  });

  test("a run with no claim says so and is not sealed as a success", async ({ page }) => {
    const id = "inv_5c9f95de6c09";
    const runId = "run_8145a6bc00d7";
    const run = await api<Run>(`/investigations/${id}/runs/${runId}`);
    expect(run.agent.claim).toBeNull();
    await page.goto(`/design-lab/comparison?case=${id}&run=${runId}`);
    await settled(page);
    await expect(page.getByTestId("claim-status")).toHaveText("no valid claim");
    await expect(page.getByTestId("oracle-seal-label").first()).toHaveText("INCONCLUSIVE");
    await expect(page.getByTestId("divergence-field")).toHaveAttribute("data-divergence", "unresolved");
  });

  test("the signature case keeps the disclosure that qualifies it, on every surface", async ({ page }) => {
    for (const route of ["/design-lab/comparison", "/design-lab/landing"]) {
      await page.goto(route);
      await settled(page);
      await expect(page.getByText("not concealment").first()).toBeVisible();
    }
  });

  test("decoration is silent, empty of evidence, and never a record", async ({ page }) => {
    for (const route of ["/design-lab/landing", "/design-lab/comparison"]) {
      await page.goto(route);
      await settled(page);
      const layers = await page.locator("[data-rf-decorative]").evaluateAll((els) =>
        els.map((el) => ({
          hidden: el.getAttribute("aria-hidden"),
          echo: el.classList.contains("rf-echo-outline"),
          text: el.textContent ?? "",
          record: el.querySelector("[data-record]") !== null,
        })),
      );
      expect(layers.length).toBeGreaterThan(0);
      for (const layer of layers) {
        expect(layer.hidden).toBe("true");
        expect(layer.record).toBe(false);
        if (layer.echo) expect(layer.text).toBe("");
        expect(layer.text).not.toMatch(/cus_|\d/);
      }
      // Echoes never sit around or inside a committed record.
      await expect(page.locator(".rf-echo [data-record]")).toHaveCount(0);
      await expect(page.locator("[data-record] .rf-echo")).toHaveCount(0);
      // Layered type never holds a recorded value.
      await expect(page.locator(".rf-display [data-testid]")).toHaveCount(0);
    }
  });

  test("the seal is square to the grid", async ({ page }) => {
    await page.goto("/design-lab/comparison");
    await settled(page);
    await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished)));
    const transform = await page
      .getByTestId("oracle-seal")
      .first()
      .evaluate((el) => getComputedStyle(el).transform);
    expect(["none", "matrix(1, 0, 0, 1, 0, 0)"]).toContain(transform);
  });

  test("the lab asks only for read-only evidence", async ({ page }) => {
    const seen: string[] = [];
    page.on("request", (r) => seen.push(r.url()));
    for (const route of ROUTES) {
      await page.goto(route);
      await settled(page);
    }
    const origin = new URL(page.url()).origin;
    expect(seen.filter((u) => !u.startsWith(origin) && !u.startsWith("data:"))).toEqual([]);
    expect(seen.filter((u) => u.includes("/api/operator"))).toEqual([]);
  });
});

test.describe("access", () => {
  for (const viewport of VIEWPORTS) {
    test(`no route overflows at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      for (const route of ROUTES) {
        await page.goto(route);
        await settled(page);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, route).toBeLessThanOrEqual(0);
      }
    });
  }

  for (const viewport of VIEWPORTS) {
    test(`verdicts stay whole and evidence stays uncovered at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      for (const route of ROUTES.filter((r) => r !== "/design-lab" && r !== "/design-lab/system")) {
        await page.goto(route);
        await settled(page);
        await page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished)));
        // A verdict never breaks inside a word.
        const broken = await page.locator(".rf-seal-label").evaluateAll((els) =>
          els
            .filter((el) => {
              const range = document.createRange();
              range.selectNodeContents(el);
              return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size > 1;
            })
            .map((el) => el.textContent),
        );
        expect(broken, route).toEqual([]);
        // Nothing sits on top of a recorded value.
        const covered = await page
          .locator(".rf-slab-id, .rf-slip-id, .rf-evidence-word, .rf-count-number, .rf-seal-label, .st-b-id, .st-c-id")
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
        expect(covered, route).toEqual([]);
      }
    });
  }

  test("display type keeps the page gutter at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/design-lab/landing");
    await settled(page);
    const lefts = await page
      .locator(".rf-hero-line .rf-display-layer-a, .rf-hero-line-actual > span")
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().left));
    expect(lefts.length).toBeGreaterThan(0);
    for (const left of lefts) expect(left).toBeGreaterThanOrEqual(16);
  });

  test("the signature pages stay cheap to render", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const route of ["/design-lab/landing", "/design-lab/comparison"]) {
      await page.goto(route);
      await settled(page);
      await page.waitForFunction(() => document.getAnimations().every((a) => a.playState === "finished"));
      const metrics = await page.evaluate(
        () =>
          new Promise<{ cls: number; lcp: number; nodes: number; running: number }>((resolve) => {
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
                  running: document.getAnimations().filter((a) => a.playState === "running").length,
                }),
              250,
            );
          }),
      );
      console.log(route, JSON.stringify(metrics));
      expect(metrics.running, "nothing loops").toBe(0);
      expect(metrics.cls).toBeLessThan(0.1);
    }
  });

  test("evidence text is not clipped at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/design-lab/comparison");
    await settled(page);
    const clipped = await page
      .locator(".rf-slab-id, .rf-slip-id, .rf-marker-body dd, .rf-oracle-list code")
      .evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth + 1).length);
    expect(clipped).toBe(0);
  });

  test("the keyboard reaches every control, with a visible focus ring", async ({ page }) => {
    await page.goto("/design-lab/landing");
    await settled(page);
    await page.getByTestId("hero-cta").focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("hero-cta")).toBeFocused();
    const ring = await page
      .getByTestId("hero-cta")
      .evaluate((el) => {
        const s = getComputedStyle(el);
        return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) };
      });
    expect(ring.style).toBe("solid");
    expect(ring.width).toBeGreaterThanOrEqual(2);

    await page.goto("/design-lab/comparison");
    await settled(page);
    await page.locator("details.rf-details summary").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("claim-message")).toBeVisible();
    await page.getByTestId("raw-evidence").focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/investigations\/inv_.*view=reality/);
  });

  test("the raw evidence link opens the product view of the same run", async ({ page }) => {
    await page.goto("/design-lab/comparison");
    await settled(page);
    const run = await page.getByTestId("comparison").getAttribute("data-run");
    await page.getByTestId("raw-evidence").click();
    await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", run ?? "");
  });

  test("the headline reads once, in order, to assistive technology", async ({ page }) => {
    await page.goto("/design-lab/landing");
    await settled(page);
    const tree = await page.locator("h1").ariaSnapshot();
    expect(tree).toContain("What the agent believed. What actually happened.");
    expect(tree.match(/believed/gi)?.length).toBe(1);
  });

  test("text and status pairs meet WCAG AA", async ({ page }) => {
    await page.goto("/design-lab/system");
    await settled(page);
    const pairs = [
      ["--rf-text", "--rf-surface-base"],
      ["--rf-text", "--rf-surface-high"],
      ["--rf-text", "--rf-agent-plane"],
      ["--rf-text", "--rf-actual-plane"],
      ["--rf-text-muted", "--rf-surface-base"],
      ["--rf-text-muted", "--rf-surface-raised"],
      ["--rf-text-muted", "--rf-surface-high"],
      ["--rf-text-muted", "--rf-agent-plane"],
      ["--rf-text-muted", "--rf-actual-plane"],
      ["--rf-text-faint", "--rf-surface-base"],
      ["--rf-text-faint", "--rf-surface-raised"],
      ["--rf-agent", "--rf-surface-base"],
      ["--rf-agent", "--rf-surface-raised"],
      ["--rf-agent", "--rf-agent-plane"],
      ["--rf-actual", "--rf-surface-base"],
      ["--rf-actual", "--rf-surface-raised"],
      ["--rf-actual", "--rf-actual-plane"],
      ["--rf-divergence", "--rf-surface-base"],
      ["--rf-divergence", "--rf-actual-plane"],
      ["--rf-oracle-ink", "--rf-oracle-surface"],
      ["--rf-status-ink", "--rf-status-pass"],
      ["--rf-status-ink", "--rf-status-violation"],
      ["--rf-status-ink", "--rf-status-inconclusive"],
    ];
    const ratios = await page.evaluate((list) => {
      const root = document.querySelector(".rf") as HTMLElement;
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
