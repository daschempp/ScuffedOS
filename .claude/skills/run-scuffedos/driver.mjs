// driver.mjs — drives the running ScuffedOS frontend and screenshots each surface.
//
// The dashboard is a single-page app: nav is React state, the URL never changes,
// so `chrome --headless --screenshot <url>` can only ever capture Home. You need a
// real automation handle to click between surfaces — that's what this is.
//
// Prereq: backend on :8000 and Vite on :5173 already running (see SKILL.md), and
// Playwright installed in this dir (`npm install`). Chromium is auto-discovered from
// the Playwright browser cache; no project-managed browser download required.
//
// Env knobs:
//   BASE_URL   frontend origin           (default http://localhost:5173)
//   OUT        screenshot output dir     (default /tmp/scuffed-shots)
//   SURFACES   comma list of nav labels  (default the 6 live surfaces)
//
// Exit 0 = every surface rendered; 1 = one or more failed; 2 = no chromium found.

import { chromium } from 'playwright';
import { existsSync, readdirSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

const BASE = process.env.BASE_URL || 'http://localhost:5173';
const OUT = process.env.OUT || '/tmp/scuffed-shots';
const SURFACES = (process.env.SURFACES || 'Home,Calendar,Tasks,Habits,Nutrition,Second Brain')
  .split(',').map(s => s.trim()).filter(Boolean);

// Find a Chromium binary without forcing Playwright to download its own build.
function findChromium() {
  // 1) Playwright's bundled build, if its version happens to be installed.
  try { const p = chromium.executablePath(); if (p && existsSync(p)) return p; } catch { /* noop */ }
  // 2) Newest chromium-* in the Playwright browser cache (macOS or Linux layout).
  for (const root of [join(homedir(), 'Library/Caches/ms-playwright'), join(homedir(), '.cache/ms-playwright')]) {
    if (!existsSync(root)) continue;
    const builds = readdirSync(root)
      .filter(d => /^chromium-\d+$/.test(d))
      .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
    for (const b of builds) {
      for (const rel of [
        'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
        'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
        'chrome-linux/chrome',
      ]) {
        const full = join(root, b, rel);
        if (existsSync(full)) return full;
      }
    }
  }
  // 3) System Google Chrome (macOS).
  const sys = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  return existsSync(sys) ? sys : null;
}

const exe = findChromium();
if (!exe) {
  console.error('No Chromium found. Run: npx playwright install chromium');
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: exe, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();

const consoleErrors = [];
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', e => consoleErrors.push('PAGEERROR: ' + e.message));

await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForSelector('.kit-sidebar', { timeout: 15000 }); // app shell mounted

const results = [];
for (const name of SURFACES) {
  try {
    if (name !== 'Home') {
      // Sidebar items are <button class="kit-navitem"><span>Label</span></button>.
      await page.click(`.kit-navitem:has-text("${name}")`, { timeout: 8000 });
    }
    await page.waitForTimeout(1200); // let the surface fetch + settle
    const file = join(OUT, name.toLowerCase().replace(/ /g, '-') + '.png');
    await page.screenshot({ path: file, fullPage: true });
    const heading = (await page.locator('h1').first().textContent().catch(() => '') || '').trim().slice(0, 60);
    results.push({ name, file, heading, ok: true });
  } catch (e) {
    results.push({ name, ok: false, error: String(e).slice(0, 140) });
  }
}

console.log(JSON.stringify({ chromium: exe, base: BASE, out: OUT, results, consoleErrors: consoleErrors.slice(0, 20) }, null, 2));
await browser.close();
process.exit(results.every(r => r.ok) && consoleErrors.length === 0 ? 0 : 1);
