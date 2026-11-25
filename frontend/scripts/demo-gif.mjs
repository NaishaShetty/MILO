// demo-gif.mjs -- screenshots of the demo-mode replay, for docs/demo.gif.
// Usage (with the dev server running in demo mode on $BASE):
//   node scripts/demo-gif.mjs <missionId> <outDir>
import { chromium } from "@playwright/test";

const [missionId, outDir] = process.argv.slice(2);
const base = process.env.BASE ?? "http://127.0.0.1:5199";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
await page.goto(`${base}/?demo=1`);
await page.waitForSelector("text=Meet MILO");
await page.screenshot({ path: `${outDir}/00-home.png` });
await page.goto(`${base}/replay/${missionId}`);
const scrub = page.locator("#scrub");
await scrub.waitFor();
const max = Number(await scrub.getAttribute("max"));
const stops = [1, 3, 5, 8, 11, 14, Math.max(0, max - 3), max].filter((v, i, a) => v <= max && a.indexOf(v) === i);
let i = 1;
for (const v of stops) {
  await scrub.evaluate((el, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, v);
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${outDir}/${String(i++).padStart(2, "0")}-replay.png` });
}
await page.goto(`${base}/leaderboard`);
await page.waitForSelector("text=Leaderboard");
await page.waitForTimeout(300);
await page.screenshot({ path: `${outDir}/${String(i++).padStart(2, "0")}-leaderboard.png` });
await browser.close();
console.log(`captured ${i} frames`);
