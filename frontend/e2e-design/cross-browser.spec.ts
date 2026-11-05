import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

// Runs in both engines. Layout-dependent facts that differ between them: `summary` as a grid, font
// stretch on a variable font, sticky tabs, and hash targets on streamed content.

const VIOLATION = "inv_d0bc87de6010";
const SHOTS = join(__dirname, "..", "..", "docs", "design", "screenshots", "sprint-11");

for (const { width, height } of [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
]) {
  test(`the comparison lays out at ${width}px`, async ({ page, browserName }) => {
    await page.setViewportSize({ width, height });
    await page.goto(`/investigations/${VIOLATION}`);
    await expect(page.getByText(/^Loading\b/)).toHaveCount(0);
    await page.evaluate(() => document.fonts.ready);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    for (const id of ["headline", "strip-claim", "strip-state", "strip-verdict"]) {
      const box = await page.getByRole("main").getByTestId(id).boundingBox();
      expect(box!.y + box!.height, id).toBeLessThanOrEqual(height);
    }

    // The summary of a ledger row is a grid: its two sides sit level from tablet up.
    const row = page.getByTestId("call-5").locator("summary");
    const sides = await row.locator(".rf-call-side").evaluateAll((els) =>
      els.map((el) => el.getBoundingClientRect()).map((r) => ({ x: r.x, y: r.y })),
    );
    if (width >= 720) {
      expect(Math.abs(sides[0].y - sides[1].y)).toBeLessThan(2);
      expect(sides[1].x).toBeGreaterThan(sides[0].x + 100);
    } else {
      expect(sides[1].y).toBeGreaterThan(sides[0].y);
    }

    // Variable width axis: the display face must really be condensed, not silently regular.
    const stretch = await page.locator(".rf-headline").evaluate((el) => getComputedStyle(el).fontStretch);
    expect(stretch).toBe("82%");

    if (process.env.MOODY_DESIGN_SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await page.screenshot({ path: join(SHOTS, `engine-${browserName}-${width}.png`) });
    }
  });
}

test("a deep link lands on its row and opens it", async ({ page }) => {
  await page.goto(`/investigations/${VIOLATION}?view=reality&run=run_cc34d7a6e314#call-7`);
  await expect(page.getByTestId("call-7")).toBeInViewport();
  await expect(page.getByTestId("call-7").locator("details")).toHaveJSProperty("open", true);
});
