import { readFileSync } from "node:fs";
import { connect } from "node:net";
import { join } from "node:path";

import { expect, type Page, test } from "@playwright/test";

// Expected values come from the committed evidence files, not from the deployment under test.

const URL_ = new URL(process.env.MOODY_HOSTED_URL!);
const REAL = process.env.MOODY_HOSTED_TARGET === "vultr";
const TOKEN = process.env.MOODY_HOSTED_OPERATOR_TOKEN;
const LIVE = process.env.MOODY_HOSTED_LIVE === "1";
const VIOLATION = "inv_d0bc87de6010";
const NEGATIVE = "inv_c803b47c336a";
const INCONCLUSIVE = "inv_5c9f95de6c09";
const RECORDED = join(__dirname, "..", "..", "evidence", "recorded");

interface Bundle {
  summary: { outcome: string; verified_finding_count: number };
  runs: { run_id: string; verdict: string }[];
}
const bundle = (id: string) =>
  JSON.parse(readFileSync(join(RECORDED, `${id}.json`), "utf-8")) as Bundle;

function portOpen(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = connect({ host, port, timeout: 4000 });
    const done = (open: boolean) => {
      socket.destroy();
      resolve(open);
    };
    socket.on("connect", () => done(true));
    socket.on("timeout", () => done(false));
    socket.on("error", () => done(false));
  });
}

async function signIn(page: Page) {
  await page.goto("/operator");
  await page.getByLabel(/operator token/i).fill(TOKEN!);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test.describe("transport", () => {
  test("the site is https, with its security headers and no server banner", async ({ request }) => {
    const res = await request.get("/");
    expect(res.status()).toBe(200);
    expect(res.url().startsWith("https://")).toBe(true);
    const headers = res.headers();
    expect(headers["strict-transport-security"]).toContain("max-age=");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(headers["x-powered-by"]).toBeUndefined();
    expect(headers["server"]).toBeUndefined();
  });

  test("plain http is redirected to https", async ({ request }) => {
    test.skip(!REAL, "needs port 80 on the real host");
    const res = await request.get(`http://${URL_.hostname}/`, { maxRedirects: 0 });
    expect([301, 302, 308]).toContain(res.status());
    expect(res.headers()["location"]).toMatch(/^https:/);
  });
});

test.describe("the backend is not exposed", () => {
  test("backend and web ports refuse from the internet", async () => {
    test.skip(!REAL, "local services are reachable from this machine by definition");
    for (const port of [8000, 3000, 2375, 2376]) {
      expect(await portOpen(URL_.hostname, port), `port ${port}`).toBe(false);
    }
  });

  test("no backend route answers through the public site", async ({ request }) => {
    for (const path of [
      "/sandbox/smoke",
      "/operator/status",
      "/operator/jobs",
      "/investigations",
      "/containment/report.json",
      "/openapi.json",
      "/docs",
      "/health",
      "/ready",
    ]) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
    }
    expect((await request.post("/sandbox/smoke")).status()).toBeGreaterThanOrEqual(400);
  });

  test("a forged forwarded header earns nothing", async ({ request }) => {
    const res = await request.post("/api/operator/jobs", {
      data: { mission_id: "rehearsal-blind-retry" },
      headers: {
        origin: URL_.origin,
        "x-forwarded-for": "127.0.0.1",
        "x-forwarded-host": "127.0.0.1:8000",
        "x-forwarded-proto": "http",
      },
    });
    expect(res.status()).toBe(401);
  });
});

test.describe("public recorded investigation", () => {
  test("a clean browser can follow a verified violation to the Oracle", async ({ page }) => {
    const expected = bundle(VIOLATION);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.getByTestId("open-signature").click();
    const main = page.getByRole("main");
    await expect(main.getByTestId("investigation-id")).toHaveText(VIOLATION);
    await expect(main.getByTestId("mode-tag")).toHaveText("Recorded investigation");
    await expect(main.getByTestId("verified-count")).toHaveText(
      String(expected.summary.verified_finding_count),
    );
    await main.getByTestId("tab-evidence").click();
    await main.getByTestId("tab-timeline").click();
    await expect(main.getByTestId("timeline-view")).toBeVisible();
  });

  test("each run shows the verdict in the committed evidence", async ({ page }) => {
    for (const run of bundle(VIOLATION).runs) {
      await page.goto(`/investigations/${VIOLATION}?view=reality&run=${run.run_id}`);
      await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", run.run_id);
      await expect(page.getByTestId("oracle-verdict")).toHaveText(run.verdict);
    }
  });

  test("a negative and an inconclusive case read as what they are", async ({ page }) => {
    await page.goto(`/investigations/${NEGATIVE}`);
    await expect(page.getByTestId("outcome")).toHaveText("No violation found");
    await page.goto(`/investigations/${INCONCLUSIVE}`);
    await expect(page.getByTestId("outcome")).toBeVisible();
  });

  test("an unknown investigation says so", async ({ page }) => {
    await page.goto("/investigations/inv_000000000000");
    await expect(page.getByTestId("evidence-failure")).toHaveAttribute("data-kind", "not_found");
  });

  test("the pages fit a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const path of ["/", `/investigations/${VIOLATION}`, "/containment", "/operator"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const [scroll, width] = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        window.innerWidth,
      ]);
      expect(scroll, path).toBeLessThanOrEqual(width);
    }
  });
});

test.describe("containment evidence", () => {
  test("the page reports the host it really ran on", async ({ page }) => {
    await page.goto("/containment");
    const label = page.getByTestId("containment-environment");
    if (REAL) {
      await expect(label).toHaveText("VULTR HOST");
      await expect(page.getByTestId("containment-status")).toHaveText("PASS");
      await expect(page.getByTestId("containment-attempt")).toHaveCount(8);
    } else {
      await expect(label).toHaveText("LOCAL DEVELOPMENT, NOT HOSTED");
    }
  });
});

test.describe("operator access", () => {
  test("nothing starts without a session", async ({ request }) => {
    const res = await request.post("/api/operator/jobs", {
      data: { mission_id: "rehearsal-blind-retry" },
      headers: { origin: URL_.origin },
    });
    expect(res.status()).toBe(401);
    expect((await request.get("/api/operator/status")).status()).toBe(401);
  });

  test("a request from another origin is refused", async ({ request }) => {
    const res = await request.post("/api/operator/session", {
      data: { token: "x".repeat(40) },
      headers: { origin: "https://evil.example" },
    });
    expect(res.status()).toBe(403);
  });

  test("a wrong token is refused", async ({ request }) => {
    const res = await request.post("/api/operator/session", {
      data: { token: "x".repeat(40) },
      headers: { origin: URL_.origin },
    });
    expect(res.status()).toBe(401);
  });

  test("sign in, rehearse, read the evidence, sign out, lose access", async ({ page, context }) => {
    test.skip(!TOKEN, "MOODY_HOSTED_OPERATOR_TOKEN not provided: report as NOT_RUN");
    test.setTimeout(180_000);
    await signIn(page);

    const cookie = (await context.cookies()).find((c) => c.name === "mb_operator");
    expect(cookie?.secure).toBe(true);
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe("Strict");

    await page.getByTestId("start-rehearsal-blind-retry").click();
    await page.getByTestId("confirm-rehearsal-blind-retry").click();
    const panel = page.getByTestId("job-panel");
    await expect(panel).toHaveAttribute("data-status", "completed", { timeout: 120_000 });
    await page.getByTestId("open-job-evidence").click();
    const main = page.getByRole("main");
    await expect(main.getByTestId("mode-tag")).toHaveText("Rehearsal, no model");
    await expect(main.getByTestId("oracle-verdict")).toHaveText("VIOLATION");

    await page.goto("/operator");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
    expect((await context.cookies()).find((c) => c.name === "mb_operator")).toBeUndefined();
    expect((await page.request.get("/api/operator/status")).status()).toBe(401);
  });
});

test.describe("live model execution", () => {
  test("one authorized investigation reaches Vultr and the Oracle", async ({ page }) => {
    test.skip(!LIVE || !TOKEN || !REAL, "needs explicit authorization: report as NOT_RUN");
    test.setTimeout(600_000);
    await signIn(page);
    await page.getByTestId("start-live-validation-adaptive").click();
    await page.getByRole("button", { name: /^Confirm: may spend/ }).click();
    const panel = page.getByTestId("job-panel");
    await expect(panel).toHaveAttribute("data-status", "completed", { timeout: 540_000 });
    await page.getByTestId("open-job-evidence").click();
    const main = page.getByRole("main");
    await expect(main.getByTestId("mode-tag")).toContainText("Live");
    await expect(main.getByTestId("target-evidence")).toContainText("live model");
    await expect(main.getByTestId("investigation-id")).toHaveText(/^inv_/);
  });
});
