// web/scripts/measure-288.mjs
import { spawn, execSync } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, extname, resolve, basename } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { chromium } from "playwright-core";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
process.env.LD_LIBRARY_PATH = [
  "/tmp/scratchpad",
  "/tmp/chromelibs/lib/x86_64-linux-gnu",
  "/tmp/chromelibs/usr/lib/x86_64-linux-gnu",
  "/tmp/scratchpad/chromelibs2/lib/x86_64-linux-gnu",
  "/tmp/scratchpad/chromelibs2/usr/lib/x86_64-linux-gnu",
  process.env.LD_LIBRARY_PATH,
].filter(Boolean).join(":");

const args = process.argv.slice(2);
function arg(name) { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; }
function flag(name, defaultVal) { if (args.includes(name)) return true; if (args.includes("--no-" + name.slice(2))) return false; return defaultVal; }
const BEFORE_REF = arg("--before") || "1d3951c";
const OUT = resolve(arg("--out") || "docs/evidence/288");
const REUSE_MIRROR = flag("--reuse-mirror", null); // null => auto
const REUSE_BEFORE = flag("--reuse-before", null);

mkdirSync(OUT, { recursive: true });

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
  for (const name of ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]) {
    try { return execSync(`which ${name}`, { encoding: "utf8" }).trim(); } catch {}
  }
  return null;
}
const CHROME = resolveChromium();
if (!CHROME) { console.error("No Chromium found"); process.exit(1); }
console.log("Chromium:", CHROME);

const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
  ".mjs": "application/javascript", ".json": "application/json", ".geojson": "application/geo+json",
  ".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".wasm": "application/wasm", ".txt": "text/plain", ".csv": "text/csv",
};

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function sha256File(p) { return createHash("sha256").update(readFileSync(p)).digest("hex"); }
function pixelVariance(p) {
  const code = `import json,sys; from PIL import Image; import numpy as np; im=Image.open(sys.argv[1]).convert('RGB'); a=np.asarray(im,dtype=np.float64); print(float(a.var()))`;
  return parseFloat(execSync(`uv run python -c ${JSON.stringify(code)} ${JSON.stringify(p)}`, { encoding: "utf8" }).trim());
}
function dirtyTreeGuard() {
  const head = execSync("git rev-parse HEAD", { encoding: "utf8" }).trim();
  const raw = execSync("git status --porcelain --untracked-files=no", { encoding: "utf8" });
  const lines = raw.split("\n").filter(Boolean);
  const offending = lines.filter((line) => {
    const path = line.slice(3).replace(/^"|"$/g, "");
    return !(path.startsWith("web/out/") || path === "web/out" || path.startsWith("web/.next/") || path === "web/.next");
  });
  if (offending.length) {
    console.error("dirty-tree guard failed (tracked changes outside web/out, web/.next):");
    for (const l of offending) console.error(l);
    process.exit(1);
  }
  return { head, status_porcelain: raw };
}

const LIVE = "https://twin.papyrus-ai.net/showcase";

async function mirrorShowcase(dest) {
  const report = { reachable: false, mosaic_present: false, files: [], drives: [], area_status: 0, report_status: 0, tiles_200: 0, tiles_404: 0, mirrored_bytes: 0 };
  mkdirSync(dest, { recursive: true });
  let areaRes, reportRes;
  try {
    areaRes = await fetch(LIVE + "/area.json");
    reportRes = await fetch(LIVE + "/publish_report.json");
  } catch (e) { report.reachable = false; return report; }
  report.area_status = areaRes.status;
  report.report_status = reportRes.status;
  if (!areaRes.ok || !reportRes.ok) { report.reachable = false; return report; }
  report.reachable = true;
  const areaText = await areaRes.text();
  const reportText = await reportRes.text();
  const area = JSON.parse(areaText);
  const pubReport = JSON.parse(reportText);
  report.mosaic_present = !!(pubReport.layers && Object.keys(pubReport.layers).length);
  writeFileSync(join(dest, "area.json"), areaText);
  writeFileSync(join(dest, "publish_report.json"), reportText);
  report.bytes_area = areaText.length;
  report.bytes_report = reportText.length;
  report.mirrored_bytes += areaText.length + reportText.length;
  const drives = area.drives;
  report.drives = drives.map((d) => d.run_id);
  const runFiles = ["manifest.json", "twin.geojson", "profile.csv", "centrelines.geojson"];
  for (const d of drives) {
    const rid = d.run_id;
    mkdirSync(join(dest, rid), { recursive: true });
    for (const f of runFiles) {
      const r = await fetch(LIVE + "/" + rid + "/" + f);
      if (r.ok) { const b = Buffer.from(await r.arrayBuffer()); writeFileSync(join(dest, rid, f), b); report.mirrored_bytes += b.length; }
    }
    const layers = ["lidar", "ortho", "height", "coverage"];
    for (const layer of layers) {
      const metaUrl = LIVE + "/tiles/" + rid + "/" + layer + "/meta.json";
      const r = await fetch(metaUrl);
      if (!r.ok) continue;
      const metaText = await r.text();
      const meta = JSON.parse(metaText);
      const mdir = join(dest, "tiles", rid, layer);
      mkdirSync(mdir, { recursive: true });
      writeFileSync(join(mdir, "meta.json"), metaText);
      report.mirrored_bytes += metaText.length;
      const zmax = meta.zmax;
      const tasks = [];
      for (let z = 0; z <= zmax; z++) {
        const n = 1 << z;
        for (let x = 0; x < n; x++) {
          for (let y = 0; y < n; y++) tasks.push({ z, x, y });
        }
      }
      let idx = 0;
      const concurrency = 16;
      async function worker() {
        while (idx < tasks.length) {
          const t = tasks[idx++];
          const url = LIVE + "/tiles/" + rid + "/" + layer + "/" + t.z + "/" + t.x + "/" + t.y + ".webp";
          const r = await fetch(url);
          if (r.ok) {
            report.tiles_200++;
            const b = Buffer.from(await r.arrayBuffer());
            const dir = join(dest, "tiles", rid, layer, String(t.z), String(t.x));
            mkdirSync(dir, { recursive: true });
            writeFileSync(join(dir, t.y + ".webp"), b);
            report.mirrored_bytes += b.length;
          } else if (r.status === 404) {
            report.tiles_404++;
          }
        }
      }
      await Promise.all(Array.from({ length: concurrency }, () => worker()));
    }
  }
  return report;
}

function classify404(url) {
  try {
    const u = new URL(url);
    const p = u.pathname;
    if (p.startsWith("/showcase/tiles/")) return "unexpected_tile_404";
  } catch {}
  return "known_app_404";
}

function makeServer(rootOut, fixture) {
  return createServer((req, res) => {
    let url = req.url.split("?")[0];
    if (url === "/") url = "/index.html";
    if (url.startsWith("/showcase/")) {
      const rel = url.slice("/showcase/".length);
      const fpath = join(fixture, rel);
      if (!existsSync(fpath)) { res.statusCode = 404; res.end("not found"); return; }
      const ext = extname(fpath).toLowerCase();
      res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
      res.end(readFileSync(fpath));
      return;
    }
    const fpath = join(rootOut, url.slice(1));
    if (!existsSync(fpath) || statSync(fpath).isDirectory()) { res.statusCode = 404; res.end("not found"); return; }
    const ext = extname(fpath).toLowerCase();
    res.setHeader("Content-Type", MIME[ext] || "application/octet-stream");
    res.end(readFileSync(fpath));
  });
}

function dirSizeBytes(dir) {
  let total = 0;
  try {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) total += dirSizeBytes(p);
      else try { total += statSync(p).size; } catch {}
    }
  } catch {}
  return total;
}
function countFiles(dir, ext) {
  let n = 0;
  try {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) n += countFiles(p, ext);
      else if (p.endsWith(ext)) n++;
    }
  } catch {}
  return n;
}
function mirrorReportFromCache(mirrorDir) {
  const report = { reachable: true, mosaic_present: false, files: [], drives: [], area_status: 200, report_status: 200, tiles_200: 0, tiles_404: 0, mirrored_bytes: 0, reused: true };
  try {
    const area = JSON.parse(readFileSync(join(mirrorDir, "area.json"), "utf8"));
    report.drives = (area.drives || []).map((d) => d.run_id);
  } catch { report.reachable = false; return report; }
  try {
    const pub = JSON.parse(readFileSync(join(mirrorDir, "publish_report.json"), "utf8"));
    report.mosaic_present = !!(pub.layers && Object.keys(pub.layers).length);
  } catch {}
  report.tiles_200 = countFiles(mirrorDir, ".webp");
  report.mirrored_bytes = dirSizeBytes(mirrorDir);
  return report;
}

async function main() {
  const generatedAt = new Date().toISOString();
  const dirtyTree = dirtyTreeGuard();
  const mirrorDir = join("/tmp", "288-mirror");
  const areaPath = join(mirrorDir, "area.json");
  const canReuseMirror = existsSync(areaPath) && statSync(areaPath).size > 0;
  const reuseMirror = REUSE_MIRROR === null ? canReuseMirror : REUSE_MIRROR;
  let mirrorReport;
  if (reuseMirror && canReuseMirror) {
    console.log("reusing mirror:", mirrorDir);
    mirrorReport = mirrorReportFromCache(mirrorDir);
  } else {
    rmSync(mirrorDir, { recursive: true, force: true });
    mirrorReport = await mirrorShowcase(mirrorDir);
  }
  let venue, fixtureSrc, sourceLabel;
  let mirrorOk = mirrorReport.reachable;
  if (mirrorOk) {
    for (const d of mirrorReport.drives) {
      if (!existsSync(join(mirrorDir, "tiles", d, "lidar", "meta.json"))) { mirrorOk = false; break; }
    }
  }
  if (mirrorOk) {
    venue = "live-mirror: Seaport (" + mirrorReport.drives.length + " drives)";
    fixtureSrc = mirrorDir;
    sourceLabel = "live-mirror";
  } else {
    venue = "synthetic: committed fake showcase (live Seaport unreachable)";
    const synthDir = "/tmp/288-synth";
    rmSync(synthDir, { recursive: true, force: true });
    mkdirSync(synthDir, { recursive: true });
    execSync(`git archive ${BEFORE_REF} | tar -x -C ${synthDir}`, { stdio: "inherit" });
    execSync(`bash ${synthDir}/web/scripts/fake-showcase.sh`, { stdio: "inherit", cwd: synthDir });
    fixtureSrc = synthDir + "/web/public/showcase";
    sourceLabel = "synthetic";
  }

  const fixtureDir = join("/tmp", "288-fixture");
  rmSync(fixtureDir, { recursive: true, force: true });
  mkdirSync(fixtureDir, { recursive: true });
  const mosaicCmd = [
    "uv", "run", "python", "scripts/mosaic_fixture.py",
    "--src", fixtureSrc, "--out", fixtureDir, "--source", sourceLabel,
    "--tiles-200", String(mirrorOk ? mirrorReport.tiles_200 : 0),
    "--tiles-404", String(mirrorOk ? mirrorReport.tiles_404 : 0),
    "--mirrored-bytes", String(mirrorOk ? mirrorReport.mirrored_bytes : 0),
  ];
  execSync(mosaicCmd.map((x) => JSON.stringify(x)).join(" "), { stdio: "inherit", env: { ...process.env, PYTHONPATH: process.cwd() } });
  const fixtureShowcase = fixtureDir + "/showcase";
  const fixtureProvenance = JSON.parse(readFileSync(join(fixtureDir, "provenance.json"), "utf8"));
  const publishReport = JSON.parse(readFileSync(join(fixtureShowcase, "publish_report.json"), "utf8"));
  const fixtureArea = JSON.parse(readFileSync(join(fixtureShowcase, "area.json"), "utf8"));

  const beforeHash = execSync(`git rev-parse ${BEFORE_REF}`, { encoding: "utf8" }).trim();
  const baseDir = "/tmp/288-before-" + beforeHash;
  const beforeOut = baseDir + "/web/out/index.html";
  const canReuseBefore = existsSync(beforeOut);
  const reuseBefore = REUSE_BEFORE === null ? canReuseBefore : REUSE_BEFORE;
  if (reuseBefore && canReuseBefore) {
    console.log("reusing before build:", baseDir);
  } else {
    rmSync(baseDir, { recursive: true, force: true });
    mkdirSync(baseDir, { recursive: true });
    execSync(`git archive ${BEFORE_REF} | tar -x -C ${baseDir}`, { stdio: "inherit" });
    execSync("npm ci", { cwd: baseDir + "/web", stdio: "inherit" });
    execSync("npm run build", { cwd: baseDir + "/web", stdio: "inherit" });
  }
  const afterDir = process.cwd();
  rmSync(afterDir + "/web/out", { recursive: true, force: true });
  execSync("npm run build", { cwd: afterDir + "/web", stdio: "inherit" });

  const beforeServer = makeServer(baseDir + "/web/out", fixtureShowcase);
  const afterServer = makeServer(afterDir + "/web/out", fixtureShowcase);
  await new Promise((r) => beforeServer.listen(0, "127.0.0.1", r));
  await new Promise((r) => afterServer.listen(0, "127.0.0.1", r));
  const beforePort = beforeServer.address().port;
  const afterPort = afterServer.address().port;
  console.log("ports", beforePort, afterPort);

  const LAUNCH_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-dev-shm-usage", "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"];
  let browser = await chromium.launch({ executablePath: CHROME, headless: true, args: LAUNCH_ARGS });
  async function relaunchBrowser() { try { await browser.close(); } catch {} browser = await chromium.launch({ executablePath: CHROME, headless: true, args: LAUNCH_ARGS }); }

  async function rendererOf(page) {
    return page.evaluate(() => {
      const c = document.createElement("canvas");
      const gl = c.getContext("webgl2") || c.getContext("webgl");
      const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
    });
  }

  function zmaxByLayer() {
    const out = {};
    for (const layer of ["lidar", "ortho", "height", "coverage"]) {
      try {
        const m = JSON.parse(readFileSync(join(fixtureShowcase, "tiles", layer, "meta.json"), "utf8"));
        out[layer] = m.zmax;
      } catch {}
    }
    return out;
  }
  const zmaxLayers = zmaxByLayer();
  const extent = fixtureProvenance.extent;

  async function measureSide(baseURL) {
    let context;
    let page;
    try {
      for (const p of browser.contexts()) { try { await p.close(); } catch {} }
      context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
      page = await context.newPage();
      const pageErrors = [];
      const http404s = [];
      const requestedTileZByLayer = { lidar: [], ortho: [], height: [], coverage: [] };
      page.on("pageerror", (e) => pageErrors.push(String(e)));
      page.on("console", (m) => { if (m.type() === "error") pageErrors.push(m.text()); });

      const area = await (await fetch(baseURL + "/showcase/area.json")).json();
      const inter = (area.facilities || []).find((f) => f.type === "intersection") || (area.facilities || [])[0];
      const facilityId = inter ? inter.id : null;

      const cdp = await context.newCDPSession(page);
      await cdp.send("Network.enable");
      await cdp.send("Performance.enable");
      await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });

      const inflightRef = { n: 0 };
      const webpRef = { seen: false };
      const imgReq = new Map();
      const whole = { count: 0, bytes: 0 };
      const gestureWindow = { count: 0, bytes: 0 }; // combined zoom+pan, for context
      const zoomWindow = { count: 0, bytes: 0 };
      const panWindow = { count: 0, bytes: 0 };
      let trackGestureWindow = false;
      let trackZoomWindow = false;
      let trackPanWindow = false;

      cdp.on("Network.responseReceived", (p) => {
        const status = p.response && p.response.status;
        const url = p.response && p.response.url || "";
        if (status === 404) http404s.push({ url, classification: classify404(url) });
        const ct = (((p.response || {}).headers || {})["content-type"] || "").toLowerCase();
        const isImg = p.type === "Image" || ct.startsWith("image/") || /\.(webp|png|jpe?g|gif)(\?|$)/i.test(url);
        imgReq.set(p.requestId, { isImg, trackGestureWindow, trackZoomWindow, trackPanWindow });
        if (isImg) {
          whole.count++; inflightRef.n++;
          if (trackGestureWindow) gestureWindow.count++;
          if (trackZoomWindow) zoomWindow.count++;
          if (trackPanWindow) panWindow.count++;
        }
        if (/\.webp(\?|$)/i.test(url)) {
          webpRef.seen = true;
          const m = url.match(/\/tiles\/(lidar|ortho|height|coverage)\/(\d+)\//);
          if (m) requestedTileZByLayer[m[1]].push(parseInt(m[2], 10));
        }
      });
      cdp.on("Network.loadingFinished", (p) => {
        const info = imgReq.get(p.requestId);
        if (info && info.isImg) {
          const b = p.encodedDataLength || 0;
          whole.bytes += b;
          inflightRef.n = Math.max(0, inflightRef.n - 1);
          if (info.trackGestureWindow) gestureWindow.bytes += b;
          if (info.trackZoomWindow) zoomWindow.bytes += b;
          if (info.trackPanWindow) panWindow.bytes += b;
        }
        imgReq.delete(p.requestId);
      });
      cdp.on("Network.loadingFailed", (p) => {
        const info = imgReq.get(p.requestId);
        if (info && info.isImg) inflightRef.n = Math.max(0, inflightRef.n - 1);
        imgReq.delete(p.requestId);
      });

      async function settle(timeout = 10000) {
        const start = Date.now();
        let lastZero = Date.now();
        while (Date.now() - start < timeout) {
          if (inflightRef.n === 0) {
            if (Date.now() - lastZero >= 300) return;
          } else lastZero = Date.now();
          await sleep(50);
        }
      }

      async function settleUntil(minElapsedMs, afterMs, timeout = 10000) {
        const start = Date.now();
        let lastZero = inflightRef.n === 0 ? Date.now() : 0;
        while (Date.now() - start < timeout) {
          if (inflightRef.n === 0) {
            if (lastZero === 0) lastZero = Date.now();
            if (Date.now() - start >= minElapsedMs && Date.now() - lastZero >= afterMs) return;
          } else {
            lastZero = 0;
          }
          await sleep(50);
        }
      }

      function frameStats(entries) {
        const deltas = entries.map((e) => e.dt).filter((d) => Number.isFinite(d) && d >= 0);
        if (!deltas.length) return { median: null, p95: null, samples: 0 };
        const sorted = [...deltas].sort((a, b) => a - b);
        const median = sorted[Math.floor(sorted.length / 2)];
        const p95idx = Math.ceil(0.95 * sorted.length) - 1;
        const p95 = sorted[Math.max(0, p95idx)];
        return { median: Math.round(median * 100) / 100, p95: Math.round(p95 * 100) / 100, samples: deltas.length };
      }

      async function viewFingerprint() {
        try {
          const el = page.locator(".pan");
          const box = await el.boundingBox();
          if (!box) return null;
          const buf = await page.screenshot({ clip: { x: Math.max(0, box.x), y: Math.max(0, box.y), width: box.width, height: box.height }, type: "png" });
          return createHash("sha256").update(buf).digest("hex");
        } catch {
          return null;
        }
      }

      let facilityHow = null;
      let url = baseURL;
      if (facilityId) { url = baseURL + "?f=" + encodeURIComponent(facilityId); facilityHow = "query-param"; }
      else facilityHow = "area-fit";
      await page.goto(url, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(".pan", { timeout: 15000 });
      await settle(10000);

      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForSelector(".pan", { timeout: 15000 });
      await settle(10000);

      {
        const rs = Date.now();
        while (Date.now() - rs < 15000) {
          const st = await page.locator(".scale").textContent().catch(() => null);
          if (st && st.trim() && webpRef.seen) break;
          await sleep(200);
        }
      }

      const renderer = await rendererOf(page);

      const fpBefore = await viewFingerprint();
      trackGestureWindow = true;
      await page.evaluate(() => {
        window.__frames = [];
        window.__longtasks = [];
        let last = performance.now();
        window.__rec = true;
        const tick = (t) => {
          if (window.__rec) window.__frames.push({ t, dt: t - last });
          last = t;
          if (window.__rec) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
        try {
          const obs = new PerformanceObserver((list) => {
            for (const e of list.getEntries()) window.__longtasks.push({ startTime: e.startTime, duration: e.duration, name: e.name || "longtask" });
          });
          obs.observe({ entryTypes: ["longtask"] });
        } catch {}
      });

      const scaleBeforeZoom = (await page.locator(".scale").textContent().catch(() => null) || "").trim();
      const panBox0 = await page.locator(".pan").boundingBox().catch(() => null);
      const pcx = panBox0 ? panBox0.x + panBox0.width / 2 : 720;
      const pcy = panBox0 ? panBox0.y + panBox0.height / 2 : 450;

      // zoom_transition window
      trackZoomWindow = true;
      const zoomStart = await page.evaluate(() => performance.now());
      let lastClickPerf = zoomStart;
      for (let i = 0; i < 20; i++) {
        await page.click('[aria-label="Zoom in"]').catch(() => {});
        lastClickPerf = await page.evaluate(() => performance.now());
        await sleep(50);
      }
      await settleUntil(300, 300, 10000);
      let zoomEnd = await page.evaluate(() => performance.now());
      trackZoomWindow = false;

      let scaleAfterZoom = (await page.locator(".scale").textContent().catch(() => null) || "").trim();
      if (scaleAfterZoom === scaleBeforeZoom) {
        // fallback counts as part of zoom setup/transition; re-open transition tracking
        trackZoomWindow = true;
        const zoomFallbackStart = await page.evaluate(() => performance.now());
        await page.mouse.move(pcx, pcy);
        for (let i = 0; i < 20; i++) {
          await page.mouse.wheel(0, -120);
          lastClickPerf = await page.evaluate(() => performance.now());
          await sleep(50);
        }
        await sleep(500);
        await settleUntil(300, 300, 10000);
        const zoomFallbackEnd = await page.evaluate(() => performance.now());
        trackZoomWindow = false;
        // extend transition window to include fallback
        zoomEnd = Math.max(zoomEnd, zoomFallbackEnd);
        // keep zoomStart as first click; fallback start is after gap but easier to cover whole span
        void zoomFallbackStart;
        scaleAfterZoom = (await page.locator(".scale").textContent().catch(() => null) || "").trim();
      }
      const finalScaleText = scaleAfterZoom;
      const scalePx = await page.evaluate(() => { const i = document.querySelector(".scale i"); return i ? Math.round(i.getBoundingClientRect().width) : null; }).catch(() => null);

      // ensure fully settled before pan window (all tiles loaded)
      await settle(10000);

      // pan window
      const fpBeforeDrag = await viewFingerprint();
      let dragOk = false;
      let dragDelta = 0;
      trackPanWindow = true;
      const panStart = await page.evaluate(() => performance.now()).catch(() => 0);
      try {
        const b = await page.locator(".pan").boundingBox();
        if (b) {
          const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
          await page.mouse.move(cx, cy);
          for (let i = 0; i < 40; i++) {
            const dx = Math.round(Math.cos(i * 0.4) * 40);
            const dy = Math.round(Math.sin(i * 0.4) * 40);
            try {
              await page.mouse.wheel(dx, dy);
            } catch (e) {
              console.error("pan wheel failed:", e && e.message || e);
              break;
            }
            await sleep(250);
          }
          dragOk = true;
          dragDelta = 40;
        }
      } catch (e) {
        console.error("drag gesture failed:", e && e.message || e);
        dragOk = false;
      }
      const panEnd = await page.evaluate(() => performance.now()).catch(() => panStart + 10000);
      trackPanWindow = false;
      trackGestureWindow = false;

      let fpAfterDrag = null;
      try { fpAfterDrag = await viewFingerprint(); } catch {}
      try { await page.evaluate(() => { window.__rec = false; }); } catch {}

      let samples = { frames: [], longtasks: [] };
      try {
        samples = await page.evaluate(() => ({ frames: window.__frames || [], longtasks: window.__longtasks || [] }));
      } catch (e) {
        console.error("read samples failed:", e && e.message || e);
      }

      function inRange(arr, start, end) { return arr.filter((e) => e.t >= start && e.t <= end); }
      function inRangeLT(arr, start, end) { return arr.filter((e) => e.startTime >= start && e.startTime <= end); }

      let zoomFrames = inRange(samples.frames, zoomStart, zoomEnd);
      let panFrames = inRange(samples.frames, panStart, panEnd);
      let gestureFrames = inRange(samples.frames, zoomStart, panEnd);

      if (panFrames.length < 100) {
        try {
          await page.evaluate(async () => {
            window.__rec = true;
            const start = performance.now();
            while ((window.__frames || []).length < (window.__panNeed || 0) && performance.now() - start < 8000) {
              await new Promise((r) => requestAnimationFrame(r));
            }
            window.__rec = false;
          });
        } catch {}
      }
      // ensure minimum samples by topping up a short idle sampling after pan if needed (records into frames but we won't attribute to pan window)
      if (samples.frames.length < 100) {
        try {
          await page.evaluate(async () => {
            window.__rec = true;
            const start = performance.now();
            while ((window.__frames || []).length < 120 && performance.now() - start < 8000) {
              await new Promise((r) => requestAnimationFrame(r));
            }
            window.__rec = false;
          });
          samples = await page.evaluate(() => ({ frames: window.__frames || [], longtasks: window.__longtasks || [] }));
          gestureFrames = inRange(samples.frames, zoomStart, panEnd);
        } catch (e) { console.error("frame top-up failed:", e && e.message || e); }
      }

      const zoom_transition = frameStats(zoomFrames);
      const pan = frameStats(panFrames);
      const gestureStats = frameStats(gestureFrames);
      const panLongTasks = inRangeLT(samples.longtasks, panStart, panEnd)
        .map((t) => ({ duration: Math.round(t.duration * 100) / 100, startTime: Math.round(t.startTime * 100) / 100, name: t.name || "longtask" }))
        .sort((a, b) => b.duration - a.duration);
      pan.long_tasks = panLongTasks;

      if (pan.samples < 100) throw new Error(`pan rAF samples too few: ${pan.samples}`);

      const metrics = await cdp.send("Performance.getMetrics");
      const heapMetric = (metrics.metrics || []).find((m) => m.name === "JSHeapUsedSize");
      const heap = heapMetric ? heapMetric.value : null;

      await context.close();

      const maxRequestedZByLayer = {};
      for (const [k, arr] of Object.entries(requestedTileZByLayer)) {
        maxRequestedZByLayer[k] = arr.length ? Math.max(...arr) : null;
      }
      const scaleM = /([0-9.]+)\s*m/.exec(finalScaleText || "");
      const kPxPerM = (scalePx != null && scaleM) ? (scalePx / parseFloat(scaleM[1])) : null;
      const expectedMaxZ = kPxPerM != null ? Math.ceil(Math.log2((kPxPerM * extent * 1) / 256)) : null;

      return {
        facility: facilityId ? { id: facilityId, how: facilityHow } : null,
        renderer,
        zoom_transition,
        pan,
        frame_ms: gestureStats,
        whole: whole,
        gesture: gestureWindow,
        during_gesture: panWindow,
        heap,
        final_zoom: { scale_text: (finalScaleText || "").trim(), clicks: 20, scale_px: scalePx, k_px_per_m: kPxPerM },
        page_errors: pageErrors,
        http_404s: http404s,
        tile_requests: { requested_max_z_by_layer: maxRequestedZByLayer, zmax_by_layer: zmaxLayers, expected_max_z_at_final_k: expectedMaxZ },
        drag_delta: { before_fp: fpBeforeDrag, after_fp: fpAfterDrag, changed: fpBeforeDrag !== fpAfterDrag && fpBeforeDrag != null && fpAfterDrag != null, delta: (fpBeforeDrag !== fpAfterDrag && fpBeforeDrag != null && fpAfterDrag != null) ? 1 : 0, drag_ok: dragOk, zoom_changed: fpBefore !== fpBeforeDrag },
      };
    } catch (e) {
      try { if (context) await context.close(); } catch {}
      throw e;
    }
  }

  async function measureWithRetry(port, label) {
    let lastErr;
    for (let attempt = 0; attempt < 2; attempt++) {
      try { return await measureSide(`http://127.0.0.1:${port}`); }
      catch (e) {
        lastErr = e;
        console.error(`${label} attempt ${attempt} failed:`, e && e.stack || e);
        if (attempt === 0) await relaunchBrowser();
      }
    }
    throw lastErr;
  }

  const before = await measureWithRetry(beforePort, "before");
  const after = await measureWithRetry(afterPort, "after");
  if (before.whole.count === 0) throw new Error("before side image count is 0; counter broken");
  if (after.whole.count === 0) throw new Error("after side image count is 0; counter broken");

  // screenshots (after only)
  const shotCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const shotPage = await shotCtx.newPage();
  const shotCdp = await shotCtx.newCDPSession(shotPage);
  await shotCdp.send("Network.enable");
  await shotCdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  const shotInflight = { n: 0 };
  const shotImgReq = new Map();
  shotCdp.on("Network.responseReceived", (p) => {
    const ct = (((p.response || {}).headers || {})["content-type"] || "").toLowerCase();
    const url = (p.response && p.response.url) || "";
    const isImg = p.type === "Image" || ct.startsWith("image/") || /\.(webp|png|jpe?g|gif)(\?|$)/i.test(url);
    shotImgReq.set(p.requestId, isImg);
    if (isImg) shotInflight.n++;
  });
  shotCdp.on("Network.loadingFinished", (p) => { if (shotImgReq.get(p.requestId)) shotInflight.n = Math.max(0, shotInflight.n - 1); shotImgReq.delete(p.requestId); });
  shotCdp.on("Network.loadingFailed", (p) => { if (shotImgReq.get(p.requestId)) shotInflight.n = Math.max(0, shotInflight.n - 1); shotImgReq.delete(p.requestId); });
  async function shotSettle(timeout = 10000) {
    const start = Date.now(); let lastZero = Date.now();
    while (Date.now() - start < timeout) {
      if (shotInflight.n === 0) { if (Date.now() - lastZero >= 300) return; } else lastZero = Date.now();
      await sleep(50);
    }
  }

  const areaInfo = await (await fetch(`http://127.0.0.1:${afterPort}/showcase/area.json`)).json();
  const interF = (areaInfo.facilities || []).find((f) => f.type === "intersection") || (areaInfo.facilities || [])[0];
  const fid = interF ? interF.id : null;

  async function ensureVectorsOn(p) {
    for (const name of ["Markings", "Crosswalks", "Curbs"]) {
      const btn = p.locator("button.tg").filter({ hasText: name });
      const pressed = await btn.getAttribute("aria-pressed").catch(() => null);
      if (pressed !== "true") await btn.click().catch(() => {});
    }
  }
  async function setBackground(p, target) {
    for (const name of ["Height", "Lidar", "Orthoimage"]) {
      const btn = p.locator("button.tg").filter({ hasText: name });
      const pressed = await btn.getAttribute("aria-pressed").catch(() => null);
      if (name === target) { if (pressed !== "true") await btn.click().catch(() => {}); }
      else { if (pressed === "true") await btn.click().catch(() => {}); }
      await sleep(150);
    }
  }

  const screenshotFiles = [];
  async function takeShot(name) {
    await shotSettle(10000);
    const path = join(OUT, name);
    await shotPage.screenshot({ path });
    screenshotFiles.push(name);
  }

  // area view (no facility)
  await shotPage.goto(`http://127.0.0.1:${afterPort}`, { waitUntil: "domcontentloaded" });
  await shotPage.waitForSelector(".pan", { timeout: 15000 });
  await shotSettle(10000);
  await shotPage.click('[aria-label="Fit"]').catch(() => {});
  await shotSettle(10000);
  const layers = [
    { key: "lidar", label: "Lidar" },
    { key: "ortho", label: "Orthoimage" },
    { key: "height", label: "Height" },
  ];
  for (const L of layers) {
    await setBackground(shotPage, L.label);
    await ensureVectorsOn(shotPage);
    await shotSettle(10000);
    await takeShot(`after-${L.key}-area.png`);
  }

  // full zoom facility
  if (fid) {
    await shotPage.goto(`http://127.0.0.1:${afterPort}?f=${encodeURIComponent(fid)}`, { waitUntil: "domcontentloaded" });
    await shotPage.waitForSelector(".pan", { timeout: 15000 });
    await shotSettle(10000);
    for (let i = 0; i < 20; i++) { await shotPage.click('[aria-label="Zoom in"]').catch(() => {}); await sleep(80); }
    await shotSettle(10000);
  }
  for (const L of layers) {
    await setBackground(shotPage, L.label);
    await ensureVectorsOn(shotPage);
    await shotSettle(10000);
    await takeShot(`after-${L.key}-full.png`);
  }
  await shotCtx.close();

  // phone
  const phoneCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
  const phonePage = await phoneCtx.newPage();
  const phoneCdp = await phoneCtx.newCDPSession(phonePage);
  await phoneCdp.send("Network.enable");
  await phoneCdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  const phoneInflight = { n: 0 };
  const phoneImgReq = new Map();
  phoneCdp.on("Network.responseReceived", (p) => {
    const ct = (((p.response || {}).headers || {})["content-type"] || "").toLowerCase();
    const url = (p.response && p.response.url) || "";
    const isImg = p.type === "Image" || ct.startsWith("image/") || /\.(webp|png|jpe?g|gif)(\?|$)/i.test(url);
    phoneImgReq.set(p.requestId, isImg);
    if (isImg) phoneInflight.n++;
  });
  phoneCdp.on("Network.loadingFinished", (p) => { if (phoneImgReq.get(p.requestId)) phoneInflight.n = Math.max(0, phoneInflight.n - 1); phoneImgReq.delete(p.requestId); });
  phoneCdp.on("Network.loadingFailed", (p) => { if (phoneImgReq.get(p.requestId)) phoneInflight.n = Math.max(0, phoneInflight.n - 1); phoneImgReq.delete(p.requestId); });
  async function phoneSettle(timeout = 10000) {
    const start = Date.now(); let lastZero = Date.now();
    while (Date.now() - start < timeout) {
      if (phoneInflight.n === 0) { if (Date.now() - lastZero >= 300) return; } else lastZero = Date.now();
      await sleep(50);
    }
  }
  await phonePage.goto(`http://127.0.0.1:${afterPort}` + (fid ? "?f=" + encodeURIComponent(fid) : ""), { waitUntil: "domcontentloaded" });
  await phonePage.waitForSelector(".pan", { timeout: 15000 });
  await phoneSettle(10000);
  const phonePath = join(OUT, "after-lidar-phone.png");
  await phonePage.screenshot({ path: phonePath });
  screenshotFiles.push("after-lidar-phone.png");
  await phoneCtx.close();

  await browser.close();
  beforeServer.close();
  afterServer.close();

  // remove old misnamed phone shot if present
  try { if (existsSync(join(OUT, "after-phone.png"))) rmSync(join(OUT, "after-phone.png")); } catch {}

  const screenshots = screenshotFiles.map((name) => {
    const p = join(OUT, name);
    return { path: `docs/evidence/288/${name}`, sha256: sha256File(p), pixel_variance: pixelVariance(p) };
  });

  const commitsAfter = execSync("git rev-parse HEAD", { encoding: "utf8" }).trim();
  const afterNon404Errors = (after.page_errors || []).filter((e) => !/404|Failed to load resource/i.test(e));
  const afterUnexpected404s = (after.http_404s || []).filter((h) => h.classification === "unexpected_tile_404");
  const beforeKnownApp404s = (before.http_404s || []).filter((h) => h.classification === "known_app_404");
  const afterKnownApp404s = (after.http_404s || []).filter((h) => h.classification === "known_app_404");

  function tileZoomMatch(side) {
    const req = side.tile_requests || {};
    const byLayer = req.requested_max_z_by_layer || {};
    const zmax = req.zmax_by_layer || {};
    let ok = true;
    const details = {};
    for (const [layer, maxz] of Object.entries(byLayer)) {
      const mz = zmax[layer];
      const layerOk = maxz == null || (typeof mz === "number" && maxz <= mz);
      if (!layerOk) ok = false;
      details[layer] = { requested_max_z: maxz, zmax: mz, ok: layerOk };
    }
    return { ok, details, expected_max_z_at_final_k: req.expected_max_z_at_final_k };
  }
  const tzm = tileZoomMatch(after);

  const gateReasons = [];
  if (!(before.pan.samples >= 100 && after.pan.samples >= 100)) gateReasons.push(`pan.samples < 100: before=${before.pan.samples} after=${after.pan.samples}`);
  if (!(after.pan.p95 < before.pan.p95)) gateReasons.push(`pan p95 not improved: ${before.pan.p95} -> ${after.pan.p95}`);
  if (!(after.pan.median <= before.pan.median * 1.1)) gateReasons.push(`pan median regressed >10%: ${before.pan.median} -> ${after.pan.median}`);
  if (!(after.whole.count < before.whole.count)) gateReasons.push(`whole image count not reduced: ${before.whole.count} -> ${after.whole.count}`);
  if (!(before.whole.count > 0 && after.whole.count > 0)) gateReasons.push("whole counts not both >0");
  if (before.renderer !== after.renderer) gateReasons.push(`renderer mismatch: ${before.renderer} vs ${after.renderer}`);
  if (before.final_zoom.scale_text !== after.final_zoom.scale_text) gateReasons.push(`final zoom mismatch: "${before.final_zoom.scale_text}" vs "${after.final_zoom.scale_text}"`);
  const deckErrors = (after.page_errors || []).filter((e) => /deck:|TypeError|Error:/i.test(e));
  if (deckErrors.length) gateReasons.push(`after has deck/TypeError/Error entries: ${deckErrors.join(" | ")}`);
  if (!tzm.ok) gateReasons.push(`tile_zoom_match failed: ${JSON.stringify(tzm.details)}`);
  if (afterUnexpected404s.length) gateReasons.push(`unexpected tile 404s: ${afterUnexpected404s.map((x) => x.url).join(" | ")}`);
  if (!before.drag_delta || !before.drag_delta.changed) gateReasons.push(`drag_delta before not changed: ${JSON.stringify(before.drag_delta)}`);
  if (!after.drag_delta || !after.drag_delta.changed) gateReasons.push(`drag_delta after not changed: ${JSON.stringify(after.drag_delta)}`);

  const passed = gateReasons.length === 0;

  const fullResByLayer = {};
  for (const [layer, zmax] of Object.entries(tzm.details || {})) {
    fullResByLayer[layer] = {
      observed_z: zmax.requested_max_z,
      expected_z_at_max_k: tzm.expected_max_z_at_final_k,
      zmax: zmax.zmax,
    };
  }

  const panTopLongTasks = {
    before: (before.pan.long_tasks || []).slice(0, 10),
    after: (after.pan.long_tasks || []).slice(0, 10),
  };
  const metrics = {
    venue,
    generated_at: generatedAt,
    base_ref: BEFORE_REF,
    fixture_source: sourceLabel,
    commits: { before: beforeHash, after: commitsAfter },
    git_head: dirtyTree.head,
    git_status_porcelain: dirtyTree.status_porcelain,
    publish_report: { tile_version: publishReport.tile_version || null },
    scene: {
      extent: fixtureProvenance.extent,
      bbox: fixtureProvenance.bbox,
      zmax: fixtureProvenance.layers ? Object.fromEntries(Object.entries(fixtureProvenance.layers).map(([k, v]) => [k, v.zmax])) : zmaxLayers,
      facility: after.facility,
    },
    live: { showcase_reachable: mirrorReport.reachable, mosaic_present: mirrorReport.mosaic_present, area_status: mirrorReport.area_status, report_status: mirrorReport.report_status, tiles_200: mirrorReport.tiles_200, tiles_404: mirrorReport.tiles_404, mirrored_bytes: mirrorReport.mirrored_bytes },
    renderer: { before: before.renderer, after: after.renderer, match: before.renderer === after.renderer },
    whole: { before: before.whole, after: after.whole },
    gesture: { before: before.gesture, after: after.gesture },
    zoom_transition: {
      before: { median: before.zoom_transition.median, p95: before.zoom_transition.p95, samples: before.zoom_transition.samples },
      after: { median: after.zoom_transition.median, p95: after.zoom_transition.p95, samples: after.zoom_transition.samples },
      note: "not gated; setup/transition cost (zoom clicks to settle).",
    },
    pan: {
      before: { median: before.pan.median, p95: before.pan.p95, samples: before.pan.samples, image_count: before.during_gesture.count, image_bytes: before.during_gesture.bytes },
      after: { median: after.pan.median, p95: after.pan.p95, samples: after.pan.samples, image_count: after.during_gesture.count, image_bytes: after.during_gesture.bytes },
      long_tasks_top10: panTopLongTasks,
      gate_window: "10s wheel pan after full settle (ticket scenario).",
    },
    during_gesture: { before: before.during_gesture, after: after.during_gesture },
    frame_ms: { before: before.frame_ms, after: after.frame_ms },
    heap: { before: before.heap, after: after.heap },
    gpu_memory_bytes: null,
    gpu_memory_note: "not exposed by WEBGL_debug_renderer_info on SwiftShader",
    limitations: { full_res_by_layer: fullResByLayer },
    final_zoom: { before: before.final_zoom, after: after.final_zoom },
    tile_zoom_match: { before: tileZoomMatch(before), after: tzm },
    http_404s: { before: before.http_404s, after: after.http_404s, after_unexpected: afterUnexpected404s, before_known_app_404s: beforeKnownApp404s, after_known_app_404s: afterKnownApp404s },
    page_errors: { before: before.page_errors, after: after.page_errors, after_non_404: afterNon404Errors },
    drag_delta: { before: before.drag_delta, after: after.drag_delta },
    screenshots,
    fixture: { provenance: fixtureProvenance },
    comparison: {
      zoom_transition_p95_before: before.zoom_transition.p95,
      zoom_transition_p95_after: after.zoom_transition.p95,
      pan_p95_before: before.pan.p95,
      pan_p95_after: after.pan.p95,
      pan_median_before: before.pan.median,
      pan_median_after: after.pan.median,
      whole_count_before: before.whole.count,
      whole_count_after: after.whole.count,
      before_source: "measured",
    },
    gate: { passed, reasons: gateReasons, window: "pan" },
  };

  writeFileSync(join(OUT, "metrics.json"), JSON.stringify(metrics, null, 2));

  const fmtMs = (v) => v == null ? "n/a" : `${v} ms`;
  const fmtLT = (arr) => (arr && arr.length) ? arr.map((t) => `${t.duration}ms@${t.startTime} (${t.name})`).join("; ") : "none";
  const readme = [
    "# #288 evidence",
    "",
    `- Venue: ${venue}`,
    `- Command: \`rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before ${BEFORE_REF} --out docs/evidence/288\``,
    `- Base ref: ${BEFORE_REF} (${beforeHash})`,
    `- After commit (at run): ${commitsAfter}`,
    "",
    "## zoom_transition (not gated, setup)",
    `- median: ${fmtMs(before.zoom_transition.median)} -> ${fmtMs(after.zoom_transition.median)}`,
    `- p95: ${fmtMs(before.zoom_transition.p95)} -> ${fmtMs(after.zoom_transition.p95)}`,
    `- samples: ${before.zoom_transition.samples} -> ${after.zoom_transition.samples}`,
    "",
    "## pan (gated, 10s after settle)",
    `- median: ${fmtMs(before.pan.median)} -> ${fmtMs(after.pan.median)}`,
    `- p95: ${fmtMs(before.pan.p95)} -> ${fmtMs(after.pan.p95)}`,
    `- samples: ${before.pan.samples} -> ${after.pan.samples}`,
    `- pan image count/bytes: ${before.during_gesture.count}/${before.during_gesture.bytes} -> ${after.during_gesture.count}/${after.during_gesture.bytes}`,
    `- top pan long tasks (before): ${fmtLT(before.pan.long_tasks && before.pan.long_tasks.slice(0, 5))}`,
    `- top pan long tasks (after): ${fmtLT(after.pan.long_tasks && after.pan.long_tasks.slice(0, 5))}`,
    "",
    "## Context",
    `- whole image count (navigation): ${before.whole.count} -> ${after.whole.count}`,
    `- gesture (combined zoom+pan) image count: ${before.gesture.count} -> ${after.gesture.count}`,
    `- renderer: ${before.renderer} -> ${after.renderer} (match=${before.renderer === after.renderer})`,
    `- final scale text: "${before.final_zoom.scale_text}" -> "${after.final_zoom.scale_text}"`,
    `- drag_delta: before=${JSON.stringify(before.drag_delta && before.drag_delta.changed)} after=${JSON.stringify(after.drag_delta && after.drag_delta.changed)}`,
    `- 404s: after_unexpected=${afterUnexpected404s.length} after_known_app_404s=${afterKnownApp404s.length}`,
    "",
    "## Screenshots (after-only)",
    ...screenshots.map((s) => `- ${s.path} sha256=${s.sha256} variance=${s.pixel_variance}`),
    "",
    `Gate (pan window): ${passed ? "passed" : "failed"}`,
    ...(gateReasons.length ? ["Reasons:", ...gateReasons.map((r) => `- ${r}`)] : []),
    "",
  ].join("\n");
  writeFileSync(join(OUT, "README.md"), readme);

  const summary = [
    "# #288 measured before/after",
    "",
    `Venue: ${venue}`,
    "Before source: measured (fresh this run)",
    "After source: measured (fresh this run)",
    "Gate window: pan (10s after full settle). zoom_transition reported, not gated.",
    "",
    "zoom_transition (not gated):",
    `- median: ${fmtMs(before.zoom_transition.median)} -> ${fmtMs(after.zoom_transition.median)}`,
    `- p95: ${fmtMs(before.zoom_transition.p95)} -> ${fmtMs(after.zoom_transition.p95)} (samples ${before.zoom_transition.samples} -> ${after.zoom_transition.samples})`,
    "",
    "pan (gated):",
    `- median: ${fmtMs(before.pan.median)} -> ${fmtMs(after.pan.median)}`,
    `- p95: ${fmtMs(before.pan.p95)} -> ${fmtMs(after.pan.p95)} (samples ${before.pan.samples} -> ${after.pan.samples})`,
    `- images (pan window): ${before.during_gesture.count}/${before.during_gesture.bytes} -> ${after.during_gesture.count}/${after.during_gesture.bytes}`,
    `- top long tasks (after): ${fmtLT(after.pan.long_tasks && after.pan.long_tasks.slice(0, 5))}`,
    "",
    "Context:",
    `- whole image count: ${before.whole.count} -> ${after.whole.count}`,
    `- gesture (combined) image count: ${before.gesture.count} -> ${after.gesture.count}`,
    `- renderer: ${before.renderer === after.renderer ? "match" : "mismatch"} (${after.renderer})`,
    `- final scale text: "${after.final_zoom.scale_text}" (before "${before.final_zoom.scale_text}")`,
    `- drag_delta: before=${!!(before.drag_delta && before.drag_delta.changed)} after=${!!(after.drag_delta && after.drag_delta.changed)}`,
    `- 404s: unexpected_tile=${afterUnexpected404s.length} known_app=${afterKnownApp404s.length}`,
    "",
    `Gate (pan): ${passed ? "passed" : "failed"}.`,
    ...(gateReasons.length ? gateReasons.map((r) => `- ${r}`) : []),
    "",
    "Screenshots: see docs/evidence/288/README.md (sha256 + variance).",
    "",
  ].join("\n");
  writeFileSync(join(OUT, "summary.md"), summary);

  console.log("GATE", passed, gateReasons);
  if (!passed) process.exit(1);
}

main().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
