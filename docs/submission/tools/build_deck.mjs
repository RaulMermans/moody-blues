// Renders slides.html to a PDF and one PNG per slide. Local only.
//   node docs/submission/tools/build_deck.mjs <shots-dir> <output-dir>
import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
const require = createRequire(resolve("frontend") + "/");
const { chromium } = require("@playwright/test");
const [shots, out] = process.argv.slice(2).map((p) => resolve(p));
const HOSTED_LIVE = process.env.HOSTED_LIVE_NOTE ?? "The hosted live run found no violation: the agent recovered in all 3 runs.";
const html = (await readFile("docs/submission/tools/slides.html", "utf8"))
  .replace("__CROP__", `file://${shots}/reality-crop.png`)
  .replace("__HOSTED_LIVE__", HOSTED_LIVE);
const staged = `${out}/slides.rendered.html`;
await writeFile(staged, html);
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
await page.goto(`file://${staged}`, { waitUntil: "networkidle" });
for (const slide of await page.$$(".slide")) {
  const id = await slide.getAttribute("id");
  const over = await slide.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const bad = [...el.querySelectorAll("*")].filter((n) => {
      const r = n.getBoundingClientRect();
      return n.tagName !== "path" && r.height > 0 && (r.bottom > box.bottom + 1 || r.right > box.right + 1);
    });
    return bad.length;
  });
  if (over) console.log(`OVERFLOW ${id}: ${over} element(s)`);
  await slide.screenshot({ path: `${out}/slide-${id}.png` });
}
await page.pdf({ path: `${out}/moody-blues-deck.pdf`, width: "1920px", height: "1080px", printBackground: true, preferCSSPageSize: true });
await browser.close();
