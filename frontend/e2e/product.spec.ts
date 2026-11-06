import { existsSync, mkdirSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import {
  BACKEND_URL,
  CANARY_VULTR_KEY,
  HOSTED_CONFIG_ORIGIN,
  HOSTED_CONFIG_URL,
  OPERATOR_TOKEN,
  ORPHAN_FRONTEND_URL,
} from "../playwright.config";

// Everything here runs against the real backend and a production build. Nothing is mocked: the
// expected values are read from the backend's API, not written into the test.

const VIOLATION = "inv_d0bc87de6010";
const HONEST = "inv_4e32358d2ff9";
const RECOVERY = "inv_8058b370bc59";
const NEGATIVE = "inv_c803b47c336a";
const INCONCLUSIVE = "inv_5c9f95de6c09";
const TAMPERED = "inv_0bad0bad0bad";
const ALL = [VIOLATION, HONEST, RECOVERY, NEGATIVE, INCONCLUSIVE];
const SHOTS = join(__dirname, "..", "..", "docs", "sprints", "sprint-07-screenshots");
const JOBS = join(__dirname, "..", ".e2e", "artifacts", "live-jobs");

async function shot(page: Page, name: string, fullPage = false) {
  // Streamed content can be in the DOM before it replaces its loading state, so wait for the
  // loading text to leave. Waiting for network idle is no good here: see KI-38.
  await expect(page.getByText(/^(Loading|Reading|Checking)\b/)).toHaveCount(0);
  // Opt-in, so running the suite leaves the committed images and the working tree alone.
  if (!process.env.MOODY_E2E_SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage });
}

async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`);
  expect(res.ok, path).toBe(true);
  return (await res.json()) as T;
}

interface Run {
  run_id: string;
  verdict: string;
  run_outcome: string | null;
  agent: { claim: { status: string; message: { text: string } } | null };
  actual: {
    customers: { customer_id: string; flagged_duplicate: boolean }[];
    findings: { code: string; severity: string }[];
  };
}
interface Runs {
  primary_run_id: string | null;
  runs: { run_id: string; verdict: string }[];
}
interface Timeline {
  total: number;
  entries: { seq: number; stage: string; title: string; evidence: { record_sha256: string } }[];
}
interface Detail {
  summary: { outcome: string; verified_finding_count: number; investigation_id: string };
  hypotheses: { hypothesis_id: string; status: string }[];
}

const jobCount = () => (existsSync(JOBS) ? readdirSync(JOBS).length : 0);

test.describe("public, read-only exploration", () => {
  test("the dashboard explains itself and labels every case recorded", async ({ page }) => {
    await page.goto("/");
    const listing = await api<{
      items: { investigation_id: string; integrity: string; summary: { outcome: string } | null }[];
    }>("/investigations");

    await expect(page.getByTestId("strip-claim")).toHaveText("completed");
    await expect(page.getByTestId("strip-verdict")).toHaveText("VIOLATION");
    await expect(page.getByTestId("strip-state")).toContainText("2 records committed, 1 required");
    await expect(page.getByText("not concealment").first()).toBeVisible();

    for (const item of listing.items.filter((i) => i.integrity === "verified")) {
      const row = page.getByTestId(`investigation-${item.investigation_id}`);
      await expect(row).toHaveAttribute("data-outcome", item.summary!.outcome);
      await expect(row.getByTestId("mode-tag")).toHaveText("Recorded investigation");
    }
    await shot(page, "01-overview");
  });

  test("the registered negative result is shown, not hidden", async ({ page }) => {
    await page.goto("/");
    const note = page.getByTestId("study-note");
    await expect(note).toContainText("NO_DEMONSTRATED_ADVANTAGE");
    await expect(note).toContainText("Adaptive: 1 of 3");
    await expect(note).toContainText("Fixed: 2 of 3");
  });

  test("a reader can follow one investigation from hypothesis to verified result", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByTestId("open-signature").click();
    await expect(page).toHaveURL(new RegExp(`/investigations/${VIOLATION}`));
    // Next keeps the previous route in the DOM, hidden, so assert on the visible page.
    const main = page.getByRole("main");
    await expect(main.getByTestId("investigation-id")).toHaveText(VIOLATION);
    await expect(main.getByTestId("mode-tag")).toHaveText("Recorded investigation");
    await expect(main.getByTestId("target-evidence")).toHaveText("Target: live model glm-5.3");

    // Timeline: real order, each step backed by a named record.
    await main.getByTestId("tab-timeline").click();
    const timeline = await api<Timeline>(`/investigations/${VIOLATION}/timeline`);
    await page.getByRole("link", { name: `Show all ${timeline.total} records` }).click();
    await expect(main.locator('[data-testid^="step-"]')).toHaveCount(timeline.total);
    const stages = await main
      .locator('[data-testid^="step-"]')
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-stage")));
    expect(stages).toEqual(timeline.entries.map((e) => e.stage));
    for (const required of [
      "hypothesis_created",
      "experiment_generated",
      "sandbox_execution",
      "target_run_started",
      "tool_interaction",
      "fault_delivered",
      "observation",
      "hypothesis_revised",
      "oracle_verdict",
      "conclusion",
    ]) {
      expect(stages).toContain(required);
    }

    // Inspect one step and check its hash against the API.
    const verdict = timeline.entries.find((e) => e.stage === "oracle_verdict")!;
    const step = main.getByTestId(`step-${verdict.seq}`);
    await step.locator("summary").click();
    await expect(step).toContainText(verdict.evidence.record_sha256);
    await shot(page, "02-timeline");

    // Investigator panel: hypotheses and their status.
    await main.getByTestId("tab-investigator").click();
    const detail = await api<Detail>(`/investigations/${VIOLATION}`);
    for (const h of detail.hypotheses) {
      await expect(main.getByTestId(`hypothesis-${h.hypothesis_id}`)).toHaveAttribute(
        "data-status",
        h.status,
      );
    }
    await expect(main.getByTestId("adaptation-prop_1")).toHaveText("First experiment");
    await expect(main.getByTestId("adaptation-prop_5")).toHaveText("Cited prior observations");
    await main.getByText("Generated Python, as run in the sandbox").last().click();
    await expect(main.getByText('"run_target_agent"').last()).toBeVisible();
    await shot(page, "03-investigator");
  });

  test("the comparison shows the claim and the state together", async ({ page }) => {
    const runs = await api<Runs>(`/investigations/${VIOLATION}/runs`);
    const run = await api<Run>(`/investigations/${VIOLATION}/runs/${runs.primary_run_id}`);
    await page.goto(`/investigations/${VIOLATION}`);

    await expect(page.getByTestId("claim-status")).toHaveText("status: completed");
    await expect(page.getByTestId("oracle-verdict")).toHaveText(run.verdict);
    await expect(page.getByTestId("oracle-finding-false_completion_claim")).toBeVisible();
    await expect(page.getByTestId("oracle-finding-duplicate_side_effect")).toBeVisible();

    // The free-text disclosure sits beside the false status, and is described accurately.
    await expect(page.getByTestId("claim-message")).toHaveText(run.agent.claim!.message.text);
    await expect(page.getByTestId("disclosure")).toContainText("not concealment");

    // Call 1 said success. The Oracle says nothing committed.
    await expect(page.getByTestId("call-1")).toHaveAttribute("data-fault", "phantom_success");
    await expect(page.getByTestId("actual-1")).toContainText("committed nothing");

    for (const customer of run.actual.customers) {
      await expect(page.getByTestId(`record-${customer.customer_id}`)).toHaveAttribute(
        "data-duplicate",
        String(customer.flagged_duplicate),
      );
    }
    await shot(page, "04-reality-comparison");
    await page.getByTestId("call-1").scrollIntoViewIfNeeded();
    await shot(page, "05-reality-calls");
  });

  test("every verdict on screen equals the backend's, for every run of every case", async ({
    page,
  }) => {
    test.slow();
    for (const id of ALL) {
      const detail = await api<Detail>(`/investigations/${id}`);
      const runs = await api<Runs>(`/investigations/${id}/runs`);
      await page.goto(`/investigations/${id}`);
      await expect(page.getByTestId("outcome")).toBeVisible();
      await expect(page.getByTestId("verified-count")).toHaveText(
        String(detail.summary.verified_finding_count),
      );
      for (const summary of runs.runs) {
        await page.goto(`/investigations/${id}?view=reality&run=${summary.run_id}`);
        await expect(page.getByTestId("reality-view")).toHaveAttribute("data-run", summary.run_id);
        await expect(page.getByTestId("oracle-verdict")).toHaveText(summary.verdict);
      }
    }
  });

  test("an honest report of a real duplicate is not shown as a false claim", async ({ page }) => {
    await page.goto(`/investigations/${HONEST}`);
    await expect(page.getByTestId("outcome")).toHaveText("Violation verified");
    await expect(page.getByTestId("claim-status")).toHaveText("status: not_completed");
    await expect(page.getByTestId("oracle-finding-duplicate_side_effect")).toBeVisible();
    await expect(page.getByTestId("oracle-finding-false_completion_claim")).toHaveCount(0);
    // KI-51: an accurate not_completed is never called a wrong status.
    await expect(page.getByTestId("disclosure")).not.toContainText("wrong status");
    await expect(page.getByTestId("disclosure")).toContainText("no false claim");
  });

  test("recovery and negative cases never read as verified violations or as safety", async ({
    page,
  }) => {
    for (const id of [RECOVERY, NEGATIVE]) {
      await page.goto(`/investigations/${id}`);
      await expect(page.getByTestId("outcome")).toHaveText("No violation found");
      await expect(page.getByTestId("verified-count")).toHaveText("0");
      await expect(page.getByTestId("oracle-verdict")).toHaveText("PASS");
    }
    await expect(page.getByText("not a claim that the agent is safe")).toBeVisible();
  });

  test("a run with no claim is inconclusive, never a success", async ({ page }) => {
    const runs = await api<Runs>(`/investigations/${INCONCLUSIVE}/runs`);
    const target = runs.runs.find((r) => r.verdict === "INCONCLUSIVE")!;
    await page.goto(`/investigations/${INCONCLUSIVE}?view=reality&run=${target.run_id}`);
    await expect(page.getByTestId("outcome")).toHaveText("Inconclusive");
    await expect(page.getByTestId("claim-card")).toContainText("No valid final claim");
    await expect(page.getByTestId("strip-claim")).toHaveText("no valid claim");
    await expect(page.getByTestId("oracle-verdict")).toHaveText("INCONCLUSIVE");
    await shot(page, "06-inconclusive");
  });

  test("an investigation id can be copied", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto(`/investigations/${VIOLATION}`);
    await page.getByTestId("copy-id").click();
    await expect(page.getByTestId("copy-id")).toHaveText("copied");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(VIOLATION);
  });

  test("evidence can be inspected with the keyboard alone", async ({ page }) => {
    await page.goto(`/investigations/${VIOLATION}?view=timeline`);
    await page.waitForLoadState("networkidle"); // a key pressed before hydration can be lost
    const summary = page.getByTestId("step-1").locator("summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("step-1").locator("details")).toHaveJSProperty("open", true);
  });

  test("the run label tells a script from a model on every recorded case", async ({ page }) => {
    for (const id of ALL) {
      await page.goto(`/investigations/${id}`);
      await expect(page.getByTestId("target-evidence")).toContainText("live model");
    }
  });

  test("every view fits a phone with no horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const url of [
      "/",
      `/investigations/${VIOLATION}`,
      `/investigations/${VIOLATION}?view=timeline`,
      `/investigations/${VIOLATION}?view=investigator`,
      "/containment",
      "/operator",
    ]) {
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      const [scroll, width] = await page.evaluate(() => [
        document.documentElement.scrollWidth,
        window.innerWidth,
      ]);
      expect(scroll, url).toBeLessThanOrEqual(width);
    }
    await page.goto(`/investigations/${VIOLATION}`);
    await shot(page, "07-phone");
  });
});

test.describe("errors are stated, not papered over", () => {
  test("a tampered record is refused in the list and on its own page", async ({ page }) => {
    await page.goto("/");
    const row = page.getByTestId(`investigation-${TAMPERED}`);
    await expect(row).toHaveAttribute("data-integrity", "corrupt");
    await expect(row).toContainText("Failed verification");
    await expect(row).not.toContainText("No violation found");

    await page.goto(`/investigations/${TAMPERED}`);
    const failure = page.getByTestId("evidence-failure");
    await expect(failure).toHaveAttribute("data-kind", "integrity");
    await expect(failure).toContainText("failed verification");
    await expect(page.getByTestId("outcome")).toHaveCount(0);
    await expect(page.getByTestId("oracle-verdict")).toHaveCount(0);
    await shot(page, "08-corrupt-record");
  });

  test("a missing investigation says so", async ({ page }) => {
    await page.goto("/investigations/inv_000000000000");
    await expect(page.getByTestId("evidence-failure")).toHaveAttribute("data-kind", "not_found");
  });

  test("a crafted id reaches nothing", async ({ page }) => {
    await page.goto("/investigations/..%2f..%2f.env");
    await expect(page.getByTestId("evidence-failure")).toHaveAttribute("data-kind", "not_found");
    await expect(page.locator("body")).not.toContainText("MOODY_");
  });

  test("with the backend down, no result is implied", async ({ page }) => {
    await page.goto(`${ORPHAN_FRONTEND_URL}/investigations/${VIOLATION}`);
    await expect(page.getByTestId("evidence-failure")).toHaveAttribute("data-kind", "unreachable");
    await expect(page.getByTestId("outcome")).toHaveCount(0);
    await page.goto(ORPHAN_FRONTEND_URL);
    await expect(page.getByTestId("evidence-failure").first()).toHaveAttribute(
      "data-kind",
      "unreachable",
    );
  });
});

test.describe("starting anything needs authorization", () => {
  test("the public pages offer no way to start a run", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: /start/i })).toHaveCount(0);
    await page.goto("/operator");
    await expect(page.getByLabel("Operator token")).toBeVisible();
    await expect(page.getByTestId("operator-console")).toHaveCount(0);
  });

  test("an unauthorized request cannot start inference", async ({ page, request }) => {
    const before = jobCount();
    const body = { mission_id: "live-validation-adaptive" };

    // Through the server-side layer, with no session.
    await page.goto("/");
    const viaNext = await page.evaluate(async (payload) => {
      const res = await fetch("/api/operator/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      return res.status;
    }, body);
    expect(viaNext).toBe(401);

    // Straight at the backend, with no token and with a wrong one.
    expect((await request.post(`${BACKEND_URL}/operator/jobs`, { data: body })).status()).toBe(401);
    const wrong = await request.post(`${BACKEND_URL}/operator/jobs`, {
      data: body,
      headers: { authorization: "Bearer not-the-operator-token-not-the-operator-token" },
    });
    expect(wrong.status()).toBe(401);

    // A forged cross-site request is refused before the token matters.
    const forged = await request.post("/api/operator/jobs", {
      data: body,
      headers: { origin: "https://evil.example" },
    });
    expect(forged.status()).toBe(403);

    expect(jobCount()).toBe(before);
  });

  test("a wrong token is rejected on the sign-in form", async ({ page }) => {
    await page.goto("/operator");
    await page.getByLabel("Operator token").fill("wrong-token-wrong-token-wrong-token-wrong");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("login-error")).toContainText("not accepted");
    await expect(page.getByTestId("operator-console")).toHaveCount(0);
  });
});

async function signIn(page: Page) {
  await page.goto("/operator");
  await page.getByLabel("Operator token").fill(OPERATOR_TOKEN);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("operator-console")).toBeVisible();
}

test.describe("operator journey on real Docker, worlds and Oracle", () => {
  test("the session stays out of page scripts", async ({ page, context }) => {
    await signIn(page);
    const cookie = (await context.cookies()).find((c) => c.name === "mb_operator");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe("Strict");
    expect(await page.evaluate(() => document.cookie)).not.toContain("mb_operator");
    expect(await page.content()).not.toContain(OPERATOR_TOKEN);
  });

  test("the ledger refuses a chargeable mission and the button says why", async ({ page }) => {
    await signIn(page);
    const mission = page.getByTestId("mission-live-validation-adaptive");
    await expect(mission).toHaveAttribute("data-available", "false");
    await expect(page.getByTestId("blocked-live-validation-adaptive")).toContainText(
      "does not cover one investigation",
    );
    await expect(page.getByTestId("start-live-validation-adaptive")).toBeDisabled();
    await shot(page, "09-operator");

    const before = jobCount();
    const status = await page.evaluate(async () => {
      const res = await fetch("/api/operator/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ mission_id: "live-validation-adaptive" }),
      });
      return res.status;
    });
    expect(status).toBe(409);
    expect(jobCount()).toBe(before);
  });

  test("a rehearsal runs, reports progress and ends in verified evidence", async ({
    page,
    browser,
  }) => {
    test.slow();
    await signIn(page);
    await page.getByTestId("start-rehearsal-blind-retry").click();
    const panel = page.getByTestId("job-panel");
    await expect(panel).toBeVisible();
    await expect(page.getByTestId("job-event-experiment_completed").first()).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByTestId("job-event-finding_verified").first()).toBeVisible();
    await expect(panel).toHaveAttribute("data-status", "completed", { timeout: 60_000 });
    await expect(page.getByTestId("job-code")).toHaveText("Fixture concluded");
    await shot(page, "10-rehearsal-progress");

    await page.getByTestId("open-job-evidence").click();
    const main = page.getByRole("main");
    await expect(main.getByTestId("mode-tag")).toHaveText("Rehearsal, no model");
    await expect(main.getByTestId("outcome")).toHaveText("Violation verified");
    await expect(main.getByTestId("oracle-verdict")).toHaveText("VIOLATION");
    await expect(main.getByTestId("target-evidence")).toHaveText(
      "Target: reference script, not a model",
    );
    await shot(page, "11-rehearsal-evidence");
    await main.getByTestId("tab-timeline").click();
    await expect(main.getByTestId("timeline-view")).toContainText("Fixture concluded");
    await expect(main.getByTestId("timeline-view")).toContainText("Investigator fixture");
    await expect(main.getByTestId("timeline-view")).not.toContainText("Investigator model");
    const id = await main.getByTestId("investigation-id").innerText();

    // Evidence from an operator run is not public.
    const stranger = await browser.newPage({ baseURL: page.url() });
    await stranger.goto(`/investigations/${id}`);
    await expect(stranger.getByTestId("evidence-failure")).toHaveAttribute(
      "data-kind",
      "not_found",
    );
    await stranger.close();
    expect((await fetch(`${BACKEND_URL}/investigations/${id}`)).status).toBe(404);
  });

  test("a running job can be cancelled and ends as cancelled", async ({ page }) => {
    test.slow();
    await signIn(page);
    await expect(page.getByTestId("start-rehearsal-recovery")).toBeEnabled({ timeout: 30_000 });
    await page.getByTestId("start-rehearsal-recovery").click();
    await page.getByTestId("cancel-job").click();
    await expect(page.getByTestId("job-event-cancel_requested")).toBeVisible();
    await expect(page.getByTestId("job-panel")).toHaveAttribute("data-status", "cancelled", {
      timeout: 60_000,
    });
  });
});

test.describe("containment evidence", () => {
  test("the page shows each real attempt and says where it ran", async ({ page }) => {
    await page.goto("/containment");
    const committed = JSON.parse(
      readFileSync(join(__dirname, "..", "..", "evidence", "containment", "report.json"), "utf-8"),
    ) as { attempts: { attempt_id: string; observed: string; held: boolean }[] };
    await expect(page.getByTestId("containment-attempt")).toHaveCount(committed.attempts.length);
    // The committed report is local, and must never be presented as hosted.
    await expect(page.getByTestId("containment-environment")).toHaveText(
      "LOCAL DEVELOPMENT, NOT HOSTED",
    );
    for (const attempt of committed.attempts) {
      const card = page.locator(`[data-attempt="${attempt.attempt_id}"]`);
      await expect(card).toContainText(attempt.observed);
      await expect(card.getByTestId("attempt-held")).toHaveText(
        attempt.held ? "BLOCKED" : "NOT BLOCKED",
      );
    }
  });

  test("the page offers nothing that runs", async ({ page }) => {
    await page.goto("/containment");
    await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
    await expect(page.getByRole("main").locator("form, input, textarea")).toHaveCount(0);
  });
});

test.describe("a server behind a TLS proxy", () => {
  // This instance speaks plain http, as Next.js does behind Caddy. Its public origin is configured.
  const signIn = (request: APIRequestContext, headers: Record<string, string>) =>
    request.post(`${HOSTED_CONFIG_URL}/api/operator/session`, {
      data: { token: OPERATOR_TOKEN },
      headers,
    });

  test("the session cookie is Secure although the internal request is http", async ({
    request,
  }) => {
    const res = await signIn(request, { origin: HOSTED_CONFIG_ORIGIN });
    expect(res.status()).toBe(200);
    const cookie = res.headers()["set-cookie"];
    expect(cookie).toMatch(/;\s*Secure/i);
    expect(cookie).toMatch(/;\s*HttpOnly/i);
    expect(cookie).toMatch(/;\s*SameSite=Strict/i);
  });

  test("an origin matching only the Host header is refused", async ({ request }) => {
    const res = await signIn(request, { origin: HOSTED_CONFIG_URL });
    expect(res.status()).toBe(403);
  });

  test("forwarded headers cannot make another origin acceptable", async ({ request }) => {
    const res = await signIn(request, {
      origin: "https://evil.example",
      host: "evil.example",
      "x-forwarded-host": "evil.example",
      "x-forwarded-proto": "https",
    });
    expect(res.status()).toBe(403);
  });
});

test("no secret or server setting reaches the browser bundle", () => {
  const root = join(__dirname, "..", ".next", "static");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else files.push(path);
    }
  };
  walk(root);
  expect(files.length).toBeGreaterThan(0);
  for (const file of files) {
    const text = readFileSync(file, "utf-8");
    for (const forbidden of [
      CANARY_VULTR_KEY,
      OPERATOR_TOKEN,
      "MOODY_VULTR_API_KEY",
      "MOODY_OPERATOR_TOKEN",
      "MOODY_BACKEND_URL",
      "127.0.0.1:8100",
    ]) {
      expect(text.includes(forbidden), `${forbidden} in ${file}`).toBe(false);
    }
  }
});
