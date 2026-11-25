// screenshots.mjs -- README screenshots of the real app, into docs/images/.
//
// Usage (dev server on $BASE, real backend behind its /api proxy):
//   node scripts/screenshots.mjs            # every page, desktop + mobile
//   DEMO_ONLY=1 node scripts/screenshots.mjs  # just the demo-mode pages (no backend)
// `make screenshots` wraps this.
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const base = process.env.BASE ?? "http://127.0.0.1:5176";
const out = process.env.OUT ?? "../docs/images";
const demoOnly = process.env.DEMO_ONLY === "1";
mkdirSync(out, { recursive: true });

const FREEZE = "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}";
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

const browser = await chromium.launch();

async function open(viewport, { demo = false } = {}) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addInitScript((d) => {
    window.localStorage.setItem("milo.tourSeen", "1");
    if (d) window.localStorage.setItem("milo.demo", "1");
    else window.localStorage.removeItem("milo.demo");
  }, demo);
  return context.newPage();
}

async function shot(page, route, file, { wait, click, live } = {}) {
  if (route !== null) await page.goto(base + route);
  // Pages that hold a live stream open never reach "networkidle".
  if (!live) await page.waitForLoadState("networkidle");
  if (click) {
    await page.locator(click).first().click();
    await page.waitForTimeout(1500);
  }
  if (wait) await page.waitForSelector(wait, { timeout: 15_000 });
  await page.addStyleTag({ content: FREEZE });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/${file}` });
  console.log("saved", file);
}

if (!demoOnly) {
  const page = await open(DESKTOP);
  await shot(page, "/", "play-desktop.png");
  // Run one real mission first so Missions and Replay have something to show.
  await page.getByPlaceholder(/put the apple/i).fill("Find the mug");
  await page.getByRole("button", { name: /go/i }).click();
  await page.waitForTimeout(30_000);
  await shot(page, "/missions", "missions-desktop.png", { click: "text=/Open the last mission/", live: true });
  await shot(page, "/memory", "memory-desktop.png");
  await shot(page, "/skills", "skills-desktop.png");
  await shot(page, "/replay", "replay-desktop.png", { click: "main li a, .card li a" });
  await shot(page, "/lab", "lab-desktop.png");
  await shot(page, "/leaderboard", "leaderboard-desktop.png", { wait: "text=Leaderboard" });

  const phone = await open(MOBILE);
  await shot(phone, "/", "play-mobile.png");
  await shot(phone, "/missions", "missions-mobile.png", { click: "text=/Open the last mission/", live: true });
  await shot(phone, "/memory", "memory-mobile.png");
}

const demo = await open(DESKTOP, { demo: true });
await shot(demo, "/", "demo-home-desktop.png", { wait: "text=Meet MILO" });
const missions = await (await fetch(`${base}/demo/missions.json`)).json();
if (missions.length) {
  await shot(demo, `/replay/${missions[0].id}`, "demo-replay-desktop.png", { wait: "#scrub" });
}

await browser.close();
