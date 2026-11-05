// Captures the real application for the deck and video. Reads only; signs in to nothing.
//   node docs/submission/tools/capture.mjs <base-url> <output-dir>
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
const require = createRequire(resolve("frontend") + "/");
const { chromium } = require("@playwright/test");
const [base, out] = process.argv.slice(2);
const CASE = "/investigations/inv_d0bc87de6010";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5 })).newPage();
const anchors = {};
const SCALE = 1.5;
// Where each named text sits in the screenshot, so the video can pan to it.
const shot = async (name, marks = {}) => {
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  anchors[name] = {};
  for (const [key, text] of Object.entries(marks)) {
    const box = await page.getByText(text).first().boundingBox();
    if (!box) throw new Error(`anchor not found: ${name}/${key}`);
    anchors[name][key] = Math.round(box.y * SCALE);
  }
};
await page.goto(base, { waitUntil: "networkidle" });
await shot("home", { how: "How it works", signature: "Claimed completed, with two records committed", list: /Recorded runs are real past executions/, study: /Registered benchmark/i });
await page.goto(base + "/containment", { waitUntil: "networkidle" });
await shot("containment", { attempted: "What was attempted", forged: /^Search the filesystem/, limits: "What this does not show" });
await page.goto(base + CASE, { waitUntil: "networkidle" });
await page.locator("a,button").filter({ hasText: "Run 5" }).first().click();
await page.waitForLoadState("networkidle");
await shot("reality", { task: /The task it was given/i, table: "Agent Reality", c4: /^#4$/, c5: /^#5$/, c7: /^#7$/, c8: /^#8$/, claim: /^Structured final claim$/, records: /Authoritative records/i });
await page.locator("a,button").filter({ hasText: /^Investigator$/ }).first().click();
await page.waitForLoadState("networkidle");
await shot("investigator", { h1: /^Agent's final claim consistency/, h2: /^Agent's handling of verification/, h3: /^Agent's retry behavior/, h4: /^Agent's recovery when a committed/, h5: /^Agent's recovery when a create/, conclusion: /conclusion: interpretation/i });
await page.locator("a,button").filter({ hasText: /^Timeline$/ }).first().click();
await page.waitForLoadState("networkidle");
await shot("timeline");
// The hosted live run is operator-only, so this view needs the token. It only reads.
const token = process.env.MOODY_HOSTED_OPERATOR_TOKEN;
if (token) {
  await page.goto(base + "/operator", { waitUntil: "networkidle" });
  await page.getByLabel(/operator token/i).fill(token);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.getByRole("button", { name: "Sign out" }).waitFor();
  await page.goto(base + "/investigations/inv_cbd07a262444", { waitUntil: "networkidle" });
  await shot("live", { table: "Agent Reality", claim: /^Structured final claim$/ });
  await page.goto(base + "/operator", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Sign out" }).click();
}
await browser.close();
await writeFile(`${out}/anchors.json`, JSON.stringify(anchors, null, 1));
