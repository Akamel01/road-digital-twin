#!/usr/bin/env node
import { createServer } from "node:http";
import {
  readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, statSync,
} from "node:fs";
import { join, extname, resolve, normalize, sep } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { execSync } from "node:child_process";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const ROOT = resolve(__dirname, ".."); // web/
const OUT_DIR = resolve(ROOT, "..", "docs", "evidence", "443");
const BUILD = resolve(ROOT, "out");

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "application/javascript",
  ".mjs": "application/javascript", ".css": "text/css", ".json": "application/json",
  ".geojson": "application/geo+json", ".webp": "image/webp", ".png": "image/png",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
  ".woff": "font/woff", ".ttf": "font/ttf", ".txt": "text/plain", ".csv": "text/csv",
  ".wasm": "application/wasm", ".bin": "application/octet-stream", ".map": "application/json",
};

function resolveChromium() {
  if (process.env.CHROME_BIN && existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  if (process.env.CHROME && existsSync(process.env.CHROME)) return process.env.CHROME;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || join(homedir(), ".cache", "ms-playwright");
  try {
    const dirs = readdirSync(base).filter((d) => d.startsWith("chromium-"));
    for (const d of dirs) {
      for (const sub of ["chrome-linux64", "chrome-linux"]) {
        const cand = join(base, d, sub, "chrome");
        if (existsSync(cand)) return cand;
      }
    }
  } catch {}
  // headless shell
  try {
    const dirs = readdirSync(base).filter((d) => d.startsWith("chromium_headless_shell-"));
    for (const d of dirs) {
      for (const sub of ["chrome-headless-shell-linux64"]) {
        const cand = join(base, d, sub, "chrome-headless-shell");
        if (existsSync(cand)) return cand;
      }
    }
  } catch {}
  for (const name of ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]) {
    try { return execSync(`which ${name}`, { encoding: "utf8" }).trim(); } catch {}
  }
  return null;
}

const browserKind = (process.env.BROWSER || "chromium").toLowerCase();

function sha256File(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

function pngDims(p) {
  const b = readFileSync(p);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });

  const runs = JSON.parse(readFileSync(resolve(ROOT, "..", "docs", "evals", "recon-v2-results.json"), "utf8")).runs.length;

  // static server
  const server = createServer((req, res) => {
    let url = (req.url || "/").split("?")[0];
    if (url === "/") url = "/index.html";
    // normalize + guard
    const decoded = decodeURIComponent(url);
    const rel = decoded.replace(/^\/+/, "");
    const fpath = resolve(BUILD, rel);
    const buildNorm = normalize(BUILD + sep);
    if (!fpath.startsWith(buildNorm)) {
      res.statusCode = 403;
      res.end("forbidden");
      return;
    }
    // directory / evaluations handling
    let target = fpath;
    if (existsSync(target) && statSync(target).isDirectory()) {
      // try index.html
      const idx = join(target, "index.html");
      if (existsSync(idx)) target = idx;
    }
    if (!existsSync(target) || statSync(target).isDirectory()) {
      // fallback: /evaluations -> evaluations.html or evaluations/index.html
      if (decoded === "/evaluations" || decoded === "/evaluations/") {
        const c1 = join(BUILD, "evaluations.html");
        const c2 = join(BUILD, "evaluations", "index.html");
        if (existsSync(c1)) target = c1;
        else if (existsSync(c2)) target = c2;
      }
    }
    if (!existsSync(target) || statSync(target).isDirectory()) {
      res.statusCode = 404;
      res.end("not found");
      return;
    }
    res.setHeader("Content-Type", MIME[extname(target).toLowerCase()] || "application/octet-stream");
    res.end(readFileSync(target));
  });

  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  const base = `http://127.0.0.1:${port}`;

  let browser = null;
  try {
    if (browserKind === "webkit") {
      const { webkit } = await import("playwright-core");
      browser = await webkit.launch({ headless: true });
    } else {
      const exe = resolveChromium();
      if (!exe) {
        console.error("no chromium found; set CHROME_BIN");
        process.exit(2);
      }
      const { chromium } = await import("playwright-core");
      browser = await chromium.launch({ executablePath: exe, headless: true, args: ["--disable-dev-shm-usage", "--no-sandbox"] });
      process.env._CHROME_PATH = exe;
    }

    const chromePath = process.env._CHROME_PATH || (browserKind === "webkit" ? "webkit" : "");

    // desktop + phone full page
    for (const spec of [{ name: "desktop", w: 1440, h: 900 }, { name: "phone", w: 390, h: 844 }]) {
      const context = await browser.newContext({ viewport: { width: spec.w, height: spec.h }, deviceScaleFactor: 1 });
      const page = await context.newPage();
      await page.goto(base + "/evaluations", { waitUntil: "domcontentloaded" });
      await page.waitForSelector('section[aria-labelledby="h-brief"]', { timeout: 20000 });
      // wait for run rows
      await page.waitForFunction((n) => document.querySelectorAll('section[aria-labelledby="h-runs"] tbody tr').length >= n, runs, { timeout: 20000 });
      await page.addStyleTag({ content: "#eval-page{position:static!important;inset:auto!important;height:auto!important;overflow:visible!important}html,body{overflow:visible!important;height:auto!important}" });
      await page.waitForTimeout(100);

      if (spec.name === "phone") {
        const header = await page.locator("header").first().boundingBox();
        if (!header || header.x < 0 || header.x + header.width > 390) {
          throw new Error(`phone header overflow: ${JSON.stringify(header)}`);
        }
        const link = page.locator('a[href="/latest"]').first();
        if (!(await link.isVisible())) throw new Error("back link not visible on phone");
      }

      await page.screenshot({ path: join(OUT_DIR, spec.name + ".png"), type: "png", fullPage: true });
      await context.close();
    }

    // home-phone viewport capture
    {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
      const page = await context.newPage();
      await page.goto(base + "/", { waitUntil: "domcontentloaded" });
      const link = page.locator('a[href="/evaluations"]').first();
      await link.waitFor({ state: "visible", timeout: 20000 });
      const box = await link.boundingBox();
      if (!box || box.x < 0 || box.x + box.width > 390 || box.y + box.height > 844) {
        throw new Error(`home link not in viewport: ${JSON.stringify(box)}`);
      }
      await page.screenshot({ path: join(OUT_DIR, "home-phone.png"), type: "png" });
      await context.close();
    }

    // print info
    const browserLabel = browserKind === "webkit" ? "webkit" : `chromium (${chromePath})`;
    console.log("Browser: " + browserLabel);
    console.log("Viewports: desktop 1440x900, phone 390x844, home-phone 390x844; deviceScaleFactor 1");
    for (const f of ["desktop", "phone", "home-phone"]) {
      const p = join(OUT_DIR, f + ".png");
      const d = pngDims(p);
      console.log(`${f}.png ${d.w} x ${d.h} bytes=${statSync(p).size} sha256=${sha256File(p)}`);
    }
  } finally {
    try { if (browser) await browser.close(); } catch {}
    try { server.close(); } catch {}
  }
}

main().catch((e) => {
  console.error(e && (e.stack || e.message || String(e)));
  process.exit(1);
});
