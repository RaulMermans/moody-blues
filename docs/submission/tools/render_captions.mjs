// One transparent caption image per spoken line. This ffmpeg has no subtitle filter.
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
const require = createRequire(resolve("frontend") + "/");
const { chromium } = require("@playwright/test");
const [payload, out] = process.argv.slice(2);
const lines = JSON.parse(await readFile(payload, "utf8"));
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1920, height: 190 } })).newPage();
for (const [i, line] of lines.entries()) {
  await page.setContent(`<body style="margin:0;background:transparent;height:190px;display:flex;align-items:flex-end;justify-content:center;padding-bottom:30px;box-sizing:border-box">
  <div style="max-width:1560px;background:rgba(6,8,12,.86);color:#f2f5fa;font:500 37px/1.3 -apple-system,Helvetica,Arial,sans-serif;padding:12px 26px;border-radius:10px;text-align:center"></div></body>`);
  await page.$eval("div", (el, text) => { el.textContent = text; }, line);
  await page.screenshot({ path: `${out}/cap-${i}.png`, omitBackground: true });
}
await browser.close();
