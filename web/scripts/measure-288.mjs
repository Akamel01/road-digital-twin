#!/usr/bin/env node
// #288 harness: measure pan performance (zoom→settle→10s pan) with crash-robust isolation.
// Modes:
//   (default) orchestrate: build/fixture/setup, run before+after as separate processes, combine, screenshots, docs.
//   --side before|after --out-json <path> [--build-dir <dir>] [--fixture <dir>] [--base-ref <ref>]
//   --combine --before-json <path> --after-json <path> [--out <dir>] [--fixture <dir>] [--build-dir <dir>] [--base-ref <ref>]
import { execSync, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, extname, resolve } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const __filename = fileURLToPath(import.meta.url);
const __dirname = fileURLToPath(new URL(".", import.meta.url));

// Ensure system libs for bundled/swiftshader chrome if present in common scratch locations.
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
function has(name) { return args.includes(name); }

const SIDE = arg("--side"); // before|after
const OUT_JSON = arg("--out-json");
const COMBINE = has("--combine");
const BEFORE_JSON = arg("--before-json");
const AFTER_JSON = arg("--after-json");
const BEFORE_REF = arg("--before") || arg("--base-ref") || "1d3951c";
const OUT = resolve(arg("--out") || "docs/evidence/288");
const REUSE_MIRROR = has("--reuse-mirror") ? true : (has("--no-reuse-mirror") ? false : null);
const REUSE_BEFORE = has("--reuse-before") ? true : (has("--no-reuse-before") ? false : null);
const BUILD_DIR = arg("--build-dir") ? resolve(arg("--build-dir")) : null;
const FIXTURE = arg("--fixture") ? resolve(arg("--fixture")) : null; // showcase dir
const SKIP_SCREENSHOTS = has("--skip-screenshots");

const LIVE = "https://twin.papyrus-ai.net/showcase";
const LAUNCH_ARGS = [
  "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
  "--disable-dev-shm-usage", "--disable-background-timer-throttling",
  "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
  "--disable-features=CalculateNativeWinOcclusion", "--disable-ipc-flooding-protection",
];
const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
  ".mjs": "application/javascript", ".json": "application/json", ".geojson": "application/geo+json",
  ".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".wasm": "application/wasm", ".txt": "text/plain", ".csv": "text/csv",
};

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function sh(cmd, opts = {}) { return execSync(cmd, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], ...opts }); }
function shin(cmd, opts = {}) { execSync(cmd, { stdio: "inherit", ...opts }); }
function sha256File(p) { return createHash("sha256").update(readFileSync(p)).digest("hex"); }
function pixelVariance(p) {
  const code = `import json,sys; from PIL import Image; import numpy as np; im=Image.open(sys.argv[1]).convert('RGB'); a=np.asarray(im,dtype=np.float64); print(float(a.var()))`;
  return parseFloat(execSync(`uv run python -c ${JSON.stringify(code)} ${JSON.stringify(p)}`, { encoding: "utf8" }).trim());
}

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

function dirtyTreeGuard() {
  const head = execSync("git rev-parse HEAD", { encoding: "utf8" }).trim();
  const raw = execSync("git status --porcelain --untracked-files=no", { encoding: "utf8" });
  const cwd = process.cwd().replace(/\\/g, "/");
  const outAbs = OUT.replace(/\\/g, "/").replace(/\/+$/, "");
  const relOut = outAbs.startsWith(cwd + "/") ? outAbs.slice(cwd.length + 1) : outAbs;
  const lines = raw.split("\n").filter(Boolean);
  const offending = lines.filter((line) => {
    const p = line.slice(3).replace(/^"|"$/g, "");
    if (p.startsWith("web/out/") || p === "web/out" || p.startsWith("web/.next/") || p === "web/.next") return false;
    if (p === relOut || p.startsWith(relOut + "/")) return false;
    if (p.startsWith("docs/evidence/288/") || p === "docs/evidence/288") return false;
    return true;
  });
  if (offending.length) {
    console.error("dirty-tree guard failed (tracked changes outside web/out, web/.next, docs/evidence/288):");
    for (const l of offending) console.error(l);
    process.exit(1);
  }
  return { head, status_porcelain: raw };
}

function classify404(url) {
  try {
    const p = new URL(url).pathname;
    if (p.startsWith("/showcase/tiles/")) return "unexpected_tile_404";
  } catch {}
  return "known_app_404";
}

function makeServer(rootOut, fixtureShowcase) {
  return createServer((req, res) => {
    let url = (req.url || "/").split("?")[0];
    if (url === "/") url = "/index.html";
    if (url.startsWith("/showcase/")) {
      const rel = url.slice("/showcase/".length);
      const fpath = join(fixtureShowcase, rel);
      if (!existsSync(fpath) || statSync(fpath).isDirectory()) { res.statusCode = 404; res.end("not found"); return; }
      res.setHeader("Content-Type", MIME[extname(fpath).toLowerCase()] || "application/octet-stream");
      res.end(readFileSync(fpath));
      return;
    }
    const fpath = join(rootOut, url.slice(1));
    if (!existsSync(fpath) || statSync(fpath).isDirectory()) { res.statusCode = 404; res.end("not found"); return; }
    res.setHeader("Content-Type", MIME[extname(fpath).toLowerCase()] || "application/octet-stream");
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
  const report = { reachable: true, mosaic_present: false, drives: [], area_status: 200, report_status: 200, tiles_200: 0, tiles_404: 0, mirrored_bytes: 0, reused: true };
  try { report.drives = (JSON.parse(readFileSync(join(mirrorDir, "area.json"), "utf8")).drives || []).map((d) => d.run_id); }
  catch { report.reachable = false; return report; }
  try { const pub = JSON.parse(readFileSync(join(mirrorDir, "publish_report.json"), "utf8")); report.mosaic_present = !!(pub.layers && Object.keys(pub.layers).length); } catch {}
  report.tiles_200 = countFiles(mirrorDir, ".webp");
  report.mirrored_bytes = dirSizeBytes(mirrorDir);
  return report;
}
async function mirrorShowcase(dest) {
  const report = { reachable: false, mosaic_present: false, drives: [], area_status: 0, report_status: 0, tiles_200: 0, tiles_404: 0, mirrored_bytes: 0 };
  mkdirSync(dest, { recursive: true });
  let areaRes, reportRes;
  try { areaRes = await fetch(LIVE + "/area.json"); reportRes = await fetch(LIVE + "/publish_report.json"); }
  catch { return report; }
  report.area_status = areaRes.status; report.report_status = reportRes.status;
  if (!areaRes.ok || !reportRes.ok) return report;
  report.reachable = true;
  const areaText = await areaRes.text();
  const reportText = await reportRes.text();
  const area = JSON.parse(areaText);
  let pubReport = {}; try { pubReport = JSON.parse(reportText); } catch {}
  report.mosaic_present = !!(pubReport.layers && Object.keys(pubReport.layers).length);
  writeFileSync(join(dest, "area.json"), areaText);
  writeFileSync(join(dest, "publish_report.json"), reportText);
  report.mirrored_bytes += areaText.length + reportText.length;
  report.drives = (area.drives || []).map((d) => d.run_id);
  const runFiles = ["manifest.json", "twin.geojson", "profile.csv", "centrelines.geojson"];
  for (const d of (area.drives || [])) {
    const rid = d.run_id;
    mkdirSync(join(dest, rid), { recursive: true });
    for (const f of runFiles) {
      try { const r = await fetch(LIVE + "/" + rid + "/" + f); if (r.ok) { const b = Buffer.from(await r.arrayBuffer()); writeFileSync(join(dest, rid, f), b); report.mirrored_bytes += b.length; } } catch {}
    }
    for (const layer of ["lidar", "ortho", "height", "coverage"]) {
      try {
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
        for (let z = 0; z <= zmax; z++) for (let x = 0; x < (1 << z); x++) for (let y = 0; y < (1 << z); y++) tasks.push({ z, x, y });
        let idx = 0;
        const worker = async () => {
          while (idx < tasks.length) {
            const t = tasks[idx++];
            try {
              const tr = await fetch(LIVE + "/tiles/" + rid + "/" + layer + "/" + t.z + "/" + t.x + "/" + t.y + ".webp");
              if (tr.ok) {
                report.tiles_200++;
                const b = Buffer.from(await tr.arrayBuffer());
                const dir = join(dest, "tiles", rid, layer, String(t.z), String(t.x));
                mkdirSync(dir, { recursive: true });
                writeFileSync(join(dir, t.y + ".webp"), b);
                report.mirrored_bytes += b.length;
              } else if (tr.status === 404) report.tiles_404++;
            } catch {}
          }
        };
        await Promise.all(Array.from({ length: 16 }, () => worker()));
      } catch {}
    }
  }
  return report;
}

async function ensureFixtureAndBuilds(preRunStatus) {
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
  if (mirrorOk) for (const d of mirrorReport.drives) if (!existsSync(join(mirrorDir, "tiles", d, "lidar", "meta.json"))) { mirrorOk = false; break; }
  if (mirrorOk) {
    venue = "live-mirror: Seaport (" + mirrorReport.drives.length + " drives)";
    fixtureSrc = mirrorDir; sourceLabel = "live-mirror";
  } else {
    venue = "synthetic: committed fake showcase (live Seaport unreachable)";
    const synthDir = "/tmp/288-synth";
    rmSync(synthDir, { recursive: true, force: true });
    mkdirSync(synthDir, { recursive: true });
    shin(`git archive ${BEFORE_REF} | tar -x -C ${synthDir}`);
    shin(`bash ${synthDir}/web/scripts/fake-showcase.sh`, { cwd: synthDir });
    fixtureSrc = synthDir + "/web/public/showcase"; sourceLabel = "synthetic";
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
  shin(mosaicCmd.map((x) => JSON.stringify(x)).join(" "), { env: { ...process.env, PYTHONPATH: process.cwd() } });
  const fixtureShowcase = fixtureDir + "/showcase";

  const beforeHash = execSync(`git rev-parse ${BEFORE_REF}`, { encoding: "utf8" }).trim();
  const baseDir = "/tmp/288-before-" + beforeHash;
  const beforeOut = baseDir + "/web/out/index.html";
  const canReuseBefore = existsSync(beforeOut);
  const reuseBefore = REUSE_BEFORE === null ? canReuseBefore : REUSE_BEFORE;
  if (reuseBefore && canReuseBefore) console.log("reusing before build:", baseDir);
  else {
    rmSync(baseDir, { recursive: true, force: true });
    mkdirSync(baseDir, { recursive: true });
    shin(`git archive ${BEFORE_REF} | tar -x -C ${baseDir}`);
    shin("npm ci", { cwd: baseDir + "/web" });
    shin("npm run build", { cwd: baseDir + "/web" });
  }
  const afterDir = process.cwd();
  rmSync(afterDir + "/web/out", { recursive: true, force: true });
  shin("npm run build", { cwd: afterDir + "/web" });

  return {
    venue, sourceLabel, mirrorReport, fixtureShowcase,
    fixtureDir, beforeHash, baseDir, afterDir,
    preRunStatus,
  };
}

// ---- measurement (single side, single browser process, one page) ----
async function measureSideOnce(buildOutDir, fixtureShowcase, sideLabel, CHROME) {
  const { chromium } = await import("playwright-core");
  const server = makeServer(buildOutDir, fixtureShowcase);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  let browser = null;
  try {
    browser = await chromium.launch({ executablePath: CHROME, headless: true, args: LAUNCH_ARGS });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    const pageErrors = [];
    const http404s = [];
    const requestedTileZByLayer = { lidar: [], ortho: [], height: [], coverage: [] };
    page.on("pageerror", (e) => pageErrors.push(String(e && e.stack || e)));
    page.on("console", (m) => { if (m.type() === "error") pageErrors.push(m.text()); });

    const area = JSON.parse(readFileSync(join(fixtureShowcase, "area.json"), "utf8"));
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
    const gestureWindow = { count: 0, bytes: 0 };
    const zoomWindow = { count: 0, bytes: 0 };
    const panWindow = { count: 0, bytes: 0 };
    let trackGesture = false, trackZoom = false, trackPan = false;

    cdp.on("Network.responseReceived", (p) => {
      const status = p.response && p.response.status;
      const url = (p.response && p.response.url) || "";
      if (status === 404) http404s.push({ url, classification: classify404(url) });
      const ct = (((p.response || {}).headers || {})["content-type"] || "").toLowerCase();
      const isImg = p.type === "Image" || ct.startsWith("image/") || /\.(webp|png|jpe?g|gif)(\?|$)/i.test(url);
      imgReq.set(p.requestId, { isImg, tg: trackGesture, tz: trackZoom, tp: trackPan });
      if (isImg) {
        whole.count++; inflightRef.n++;
        if (trackGesture) gestureWindow.count++;
        if (trackZoom) zoomWindow.count++;
        if (trackPan) panWindow.count++;
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
        if (info.tg) gestureWindow.bytes += b;
        if (info.tz) zoomWindow.bytes += b;
        if (info.tp) panWindow.bytes += b;
      }
      imgReq.delete(p.requestId);
    });
    cdp.on("Network.loadingFailed", (p) => {
      const info = imgReq.get(p.requestId);
      if (info && info.isImg) inflightRef.n = Math.max(0, inflightRef.n - 1);
      imgReq.delete(p.requestId);
    });

    async function settle(timeout = 10000, quiet = 300) {
      const start = Date.now();
      let lastZero = inflightRef.n === 0 ? Date.now() : 0;
      while (Date.now() - start < timeout) {
        if (inflightRef.n === 0) {
          if (lastZero === 0) lastZero = Date.now();
          if (Date.now() - lastZero >= quiet) return;
        } else lastZero = 0;
        await sleep(50);
      }
    }
    function frameStats(entries) {
      const deltas = entries.map((e) => e.dt).filter((d) => Number.isFinite(d) && d >= 0);
      if (!deltas.length) return { median: null, p95: null, samples: 0 };
      const sorted = [...deltas].sort((a, b) => a - b);
      const median = sorted[Math.floor(sorted.length / 2)];
      const p95 = sorted[Math.max(0, Math.ceil(0.95 * sorted.length) - 1)];
      return { median: Math.round(median * 100) / 100, p95: Math.round(p95 * 100) / 100, samples: deltas.length };
    }
    async function viewFingerprint() {
      try {
        const el = page.locator(".pan");
        const box = await el.boundingBox();
        if (!box) return null;
        const buf = await page.screenshot({ clip: { x: Math.max(0, box.x), y: Math.max(0, box.y), width: box.width, height: box.height }, type: "png" });
        return createHash("sha256").update(buf).digest("hex");
      } catch { return null; }
    }
    async function readLongTasks() {
      // PerformanceObserver longtask entries not directly readable; we collect in page
      return page.evaluate(() => (window.__longtasks || []).slice());
    }

    // Navigate (single page)
    const baseURL = `http://127.0.0.1:${port}`;
    const facilityHow = facilityId ? "query-param" : "area-fit";
    await page.goto(facilityId ? `${baseURL}?f=${encodeURIComponent(facilityId)}` : baseURL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".pan", { timeout: 20000 });
    await settle(15000, 300);
    // ensure webp/scale ready
    {
      const rs = Date.now();
      while (Date.now() - rs < 15000) {
        const st = await page.locator(".scale").textContent().catch(() => null);
        if (st && st.trim() && webpRef.seen) break;
        await sleep(200);
      }
    }

    const renderer = await page.evaluate(() => {
      const c = document.createElement("canvas");
      const gl = c.getContext("webgl2") || c.getContext("webgl");
      const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
    });

    // Install samplers
    await page.evaluate(() => {
      window.__frames = [];
      window.__longtasks = [];
      window.__rec = false;
      window.__panRec = false;
      window.__panFrames = [];
      let last = performance.now();
      const tick = (t) => {
        if (window.__rec) window.__frames.push({ t, dt: t - last });
        if (window.__panRec) window.__panFrames.push({ t, dt: t - last });
        last = t;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      try {
        const obs = new PerformanceObserver((list) => {
          for (const e of list.getEntries()) window.__longtasks.push({ startTime: e.startTime, duration: e.duration, name: e.name || "longtask" });
        });
        obs.observe({ entryTypes: ["longtask"] });
      } catch {}
    });

    const fpBefore = await viewFingerprint();
    const panBox0 = await page.locator(".pan").boundingBox();
    if (!panBox0) throw new Error("no .pan bbox");
    const pcx = panBox0.x + panBox0.width / 2;
    const pcy = panBox0.y + panBox0.height / 2;

    // --- zoom transition (reported, not gated) ---
    trackGesture = true; trackZoom = true;
    await page.evaluate(() => { window.__rec = true; });
    const zoomStart = await page.evaluate(() => performance.now());
    for (let i = 0; i < 20; i++) {
      await page.click('[aria-label="Zoom in"]').catch(() => {});
      await sleep(50);
    }
    await settle(15000, 300);
    const zoomEnd = await page.evaluate(() => performance.now());
    trackZoom = false;

    let finalScaleText = (await page.locator(".scale").textContent().catch(() => "")) || "";
    const scalePx = await page.evaluate(() => { const i = document.querySelector(".scale i"); return i ? Math.round(i.getBoundingClientRect().width) : null; }).catch(() => null);
    const fpAfterZoom = await viewFingerprint();

    // explicit settle 5s after full zoom, before pan window
    await sleep(5000);
    await settle(15000, 300);

    // --- pan window (gated) ---
    const fpBeforeDrag = await viewFingerprint();
    await page.evaluate(() => { window.__panFrames = []; window.__panRec = true; });
    trackPan = true;
    const panStart = await page.evaluate(() => performance.now());
    // 10s wheel pan
    const panSteps = 40; // 250ms apart => ~10s
    for (let i = 0; i < panSteps; i++) {
      const dx = Math.round(Math.cos(i * 0.4) * 40);
      const dy = Math.round(Math.sin(i * 0.4) * 40);
      await page.mouse.wheel(dx, dy);
      await sleep(250);
    }
    const panEnd = await page.evaluate(() => performance.now());
    trackPan = false;
    await page.evaluate(() => { window.__panRec = false; window.__rec = false; });
    trackGesture = false;

    const fpAfterDrag = await viewFingerprint();

    // read samples from page (one read, page still open)
    let samples;
    try {
      samples = await page.evaluate(() => ({ frames: window.__frames || [], panFrames: window.__panFrames || [], longtasks: window.__longtasks || [] }));
    } catch (e) {
      throw new Error(`read samples failed: ${e && e.message || e}`);
    }

    function inRangeLT(arr, start, end) { return (arr || []).filter((e) => e.startTime >= start && e.startTime <= end); }
    function inRange(arr, start, end) { return (arr || []).filter((e) => e.t >= start && e.t <= end); }

    const zoomFrames = inRange(samples.frames, zoomStart, zoomEnd);
    const panFrames = samples.panFrames || inRange(samples.frames, panStart, panEnd);
    const gestureFrames = inRange(samples.frames, zoomStart, panEnd);

    const zoom_transition = frameStats(zoomFrames);
    const pan = frameStats(panFrames);
    const gestureStats = frameStats(gestureFrames);
    const panLongTasks = inRangeLT(samples.longtasks, panStart, panEnd)
      .map((t) => ({ duration: Math.round(t.duration * 100) / 100, startTime: Math.round(t.startTime * 100) / 100, name: t.name || "longtask" }))
      .sort((a, b) => b.duration - a.duration);
    pan.long_tasks = panLongTasks;

    // heap
    let heap = null;
    try {
      const metrics = await cdp.send("Performance.getMetrics");
      const heapMetric = (metrics.metrics || []).find((m) => m.name === "JSHeapUsedSize");
      heap = heapMetric ? heapMetric.value : null;
    } catch {}

    // close page/context/browser cleanly
    try { await page.close({ runBeforeUnload: false }); } catch {}
    try { await context.close(); } catch {}

    const maxRequestedZByLayer = {};
    for (const [k, arr] of Object.entries(requestedTileZByLayer)) maxRequestedZByLayer[k] = arr.length ? Math.max(...arr) : null;

    // zmax/ext for expected calc
    let zmaxByLayer = {};
    try { for (const layer of ["lidar","ortho","height","coverage"]) zmaxByLayer[layer] = JSON.parse(readFileSync(join(fixtureShowcase,"tiles",layer,"meta.json"),"utf8")).zmax; } catch {}
    let extent = 0;
    try {
      const prov = JSON.parse(readFileSync(join(fixtureShowcase, "..", "provenance.json"), "utf8"));
      extent = prov.extent || 0;
    } catch {}
    const scaleM = /([0-9.]+)\s*m/.exec((finalScaleText || "").trim());
    const kPxPerM = (scalePx != null && scaleM) ? (scalePx / parseFloat(scaleM[1])) : null;
    const expectedMaxZ = (kPxPerM != null && extent) ? Math.ceil(Math.log2((kPxPerM * extent) / 256)) : null;

    return {
      side: sideLabel,
      facility: facilityId ? { id: facilityId, how: facilityHow } : null,
      renderer,
      zoom_transition,
      pan,
      frame_ms: gestureStats,
      whole,
      gesture: gestureWindow,
      during_gesture: panWindow,
      heap,
      final_zoom: { scale_text: (finalScaleText || "").trim(), clicks: 20, scale_px: scalePx, k_px_per_m: kPxPerM },
      page_errors: pageErrors,
      http_404s: http404s,
      tile_requests: { requested_max_z_by_layer: maxRequestedZByLayer, zmax_by_layer: zmaxByLayer, expected_max_z_at_final_k: expectedMaxZ },
      drag_delta: {
        changed: fpBeforeDrag !== fpAfterDrag && fpBeforeDrag != null && fpAfterDrag != null,
        zoom_changed: fpBefore !== fpAfterZoom && fpBefore != null && fpAfterZoom != null,
      },
    };
  } finally {
    try { if (browser) await browser.close(); } catch {}
    try { server.close(); } catch {}
  }
}

async function measureSideWithRetry(buildOutDir, fixtureShowcase, sideLabel) {
  const CHROME = resolveChromium();
  if (!CHROME) throw new Error("No Chromium found");
  let lastErr;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await measureSideOnce(buildOutDir, fixtureShowcase, sideLabel, CHROME);
      // sanity
      if (!(r.pan && r.pan.samples >= 100)) throw new Error(`pan rAF samples too few: ${r.pan ? r.pan.samples : 0}`);
      if (r.whole.count === 0) throw new Error(`${sideLabel} side image count is 0`);
      r.chrome = CHROME;
      r.crashed_attempts = attempt;
      return r;
    } catch (e) {
      lastErr = e;
      console.error(`[${sideLabel}] attempt ${attempt} failed:`, e && (e.stack || e.message || String(e)));
      if (attempt === 0) console.error(`[${sideLabel}] relaunching (fresh browser) and retrying once...`);
    }
  }
  throw lastErr;
}

// ---- side subcommand ----
async function runSide() {
  if (!SIDE || !OUT_JSON) { console.error("--side and --out-json required"); process.exit(2); }
  const fixtureShowcase = FIXTURE;
  if (!fixtureShowcase || !existsSync(join(fixtureShowcase, "area.json"))) { console.error("missing --fixture showcase dir"); process.exit(2); }
  const buildOut = BUILD_DIR || (SIDE === "before" ? null : resolve("web/out"));
  // resolve build out
  let outDir = buildOut;
  if (SIDE === "before" && !outDir) {
    const beforeHash = execSync(`git rev-parse ${BEFORE_REF}`, { encoding: "utf8" }).trim();
    outDir = join("/tmp", "288-before-" + beforeHash, "web", "out");
  }
  if (!outDir || !existsSync(join(outDir, "index.html"))) {
    console.error(`missing build out for ${SIDE}: ${outDir}`);
    process.exit(2);
  }
  const result = await measureSideWithRetry(outDir, fixtureShowcase, SIDE);
  mkdirSync(resolve(OUT_JSON, ".."), { recursive: true });
  writeFileSync(OUT_JSON, JSON.stringify(result, null, 2));
  console.log(`WROTE ${OUT_JSON} pan.samples=${result.pan.samples} pan.p95=${result.pan.p95}`);
}

// ---- screenshots (separate run/context/browser) ----
async function takeScreenshots(buildOutDir, fixtureShowcase, outDir) {
  const CHROME = resolveChromium();
  if (!CHROME) throw new Error("No Chromium found for screenshots");
  const { chromium } = await import("playwright-core");
  const server = makeServer(buildOutDir, fixtureShowcase);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  let browser = null;
  const files = [];
  try {
    browser = await chromium.launch({ executablePath: CHROME, headless: true, args: LAUNCH_ARGS });
    // desktop context
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable"); await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    const inflight = { n: 0 }; const imgReq = new Map();
    cdp.on("Network.responseReceived", (p) => {
      const ct = (((p.response||{}).headers||{})["content-type"]||"").toLowerCase();
      const url = (p.response&&p.response.url)||"";
      const isImg = p.type === "Image" || ct.startsWith("image/") || /\.(webp|png|jpe?g|gif)(\?|$)/i.test(url);
      imgReq.set(p.requestId, isImg); if (isImg) inflight.n++;
    });
    cdp.on("Network.loadingFinished", (p)=>{ if (imgReq.get(p.requestId)) inflight.n=Math.max(0,inflight.n-1); imgReq.delete(p.requestId); });
    cdp.on("Network.loadingFailed", (p)=>{ if (imgReq.get(p.requestId)) inflight.n=Math.max(0,inflight.n-1); imgReq.delete(p.requestId); });
    const settle = async (timeout=15000)=>{ const s=Date.now(); let lz=inflight.n===0?Date.now():0; while(Date.now()-s<timeout){ if(inflight.n===0){ if(lz===0) lz=Date.now(); if(Date.now()-lz>=300) return; } else lz=0; await sleep(50);} };

    const areaInfo = JSON.parse(readFileSync(join(fixtureShowcase, "area.json"), "utf8"));
    const interF = (areaInfo.facilities || []).find((f) => f.type === "intersection") || (areaInfo.facilities || [])[0];
    const fid = interF ? interF.id : null;
    async function ensureVectorsOn() {
      for (const name of ["Markings", "Crosswalks", "Curbs"]) {
        const btn = page.locator("button.tg").filter({ hasText: name });
        const pressed = await btn.getAttribute("aria-pressed").catch(() => null);
        if (pressed !== "true") await btn.click().catch(() => {});
      }
    }
    async function setBackground(target) {
      for (const name of ["Height", "Lidar", "Orthoimage"]) {
        const btn = page.locator("button.tg").filter({ hasText: name });
        const pressed = await btn.getAttribute("aria-pressed").catch(() => null);
        if (name === target) { if (pressed !== "true") await btn.click().catch(() => {}); }
        else { if (pressed === "true") await btn.click().catch(() => {}); }
        await sleep(150);
      }
    }
    async function takeShot(name) { await settle(15000); const pth = join(outDir, name); await page.screenshot({ path: pth }); files.push(name); }

    await page.goto(`http://127.0.0.1:${port}`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".pan", { timeout: 20000 }); await settle(15000);
    await page.click('[aria-label="Fit"]').catch(()=>{}); await settle(15000);
    const layers = [{key:"lidar",label:"Lidar"},{key:"ortho",label:"Orthoimage"},{key:"height",label:"Height"}];
    for (const L of layers) { await setBackground(L.label); await ensureVectorsOn(); await takeShot(`after-${L.key}-area.png`); }
    if (fid) {
      await page.goto(`http://127.0.0.1:${port}?f=${encodeURIComponent(fid)}`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector(".pan", { timeout: 20000 }); await settle(15000);
      for (let i=0;i<20;i++){ await page.click('[aria-label="Zoom in"]').catch(()=>{}); await sleep(80); }
      await settle(15000);
    }
    for (const L of layers) { await setBackground(L.label); await ensureVectorsOn(); await takeShot(`after-${L.key}-full.png`); }
    await context.close();

    // phone
    const pctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
    const ppage = await pctx.newPage();
    await ppage.goto(`http://127.0.0.1:${port}` + (fid ? `?f=${encodeURIComponent(fid)}` : ""), { waitUntil: "domcontentloaded" });
    await ppage.waitForSelector(".pan", { timeout: 20000 }); await sleep(5000);
    await ppage.screenshot({ path: join(outDir, "after-lidar-phone.png") }); files.push("after-lidar-phone.png");
    await pctx.close();
  } finally {
    try { if (browser) await browser.close(); } catch {}
    try { server.close(); } catch {}
  }
  return files.map((name) => ({ path: `docs/evidence/288/${name}`, sha256: sha256File(join(outDir, name)), pixel_variance: pixelVariance(join(outDir, name)) }));
}

// ---- combine / report ----
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
function fmtMs(v){ return v==null ? "n/a" : `${v} ms`; }
function fmtLT(arr){ return (arr&&arr.length)?arr.map((t)=>`${t.duration}ms@${t.startTime} (${t.name})`).join("; "):"none"; }

async function doCombine(before, after, ctx) {
  const { venue, sourceLabel, mirrorReport, fixtureShowcase, beforeHash, commitsAfter, preRunStatus, dirtyNow } = ctx;
  let publishReport = {}; let fixtureProvenance = {}; let zmaxLayers = {};
  try { publishReport = JSON.parse(readFileSync(join(fixtureShowcase, "publish_report.json"), "utf8")); } catch {}
  try { fixtureProvenance = JSON.parse(readFileSync(join(ctx.fixtureDir, "provenance.json"), "utf8")); } catch {}
  try { for (const l of ["lidar","ortho","height","coverage"]) zmaxLayers[l]=JSON.parse(readFileSync(join(fixtureShowcase,"tiles",l,"meta.json"),"utf8")).zmax; } catch {}

  const tzm = tileZoomMatch(after);
  const afterUnexpected404s = (after.http_404s||[]).filter((h)=>h.classification==="unexpected_tile_404");
  const beforeKnownApp404s = (before.http_404s||[]).filter((h)=>h.classification==="known_app_404");
  const afterKnownApp404s = (after.http_404s||[]).filter((h)=>h.classification==="known_app_404");
  const afterNon404Errors = (after.page_errors||[]).filter((e)=>!/404|Failed to load resource/i.test(e));
  const deckErrors = (after.page_errors||[]).filter((e)=>/deck:|TypeError|\bError:/i.test(e));

  const gateReasons = [];
  if (!(before.pan.samples >= 100 && after.pan.samples >= 100)) gateReasons.push(`pan.samples < 100: before=${before.pan.samples} after=${after.pan.samples}`);
  if (!(after.pan.p95 < before.pan.p95)) gateReasons.push(`pan p95 not improved: ${before.pan.p95} -> ${after.pan.p95}`);
  if (!(after.pan.median <= before.pan.median * 1.1)) gateReasons.push(`pan median regressed >10%: ${before.pan.median} -> ${after.pan.median}`);
  if (!(after.whole.count < before.whole.count)) gateReasons.push(`whole image count not reduced: ${before.whole.count} -> ${after.whole.count}`);
  if (!(before.whole.count > 0 && after.whole.count > 0)) gateReasons.push("whole counts not both >0");
  if (before.renderer !== after.renderer) gateReasons.push(`renderer mismatch: ${before.renderer} vs ${after.renderer}`);
  if (before.final_zoom.scale_text !== after.final_zoom.scale_text) gateReasons.push(`final zoom mismatch: "${before.final_zoom.scale_text}" vs "${after.final_zoom.scale_text}"`);
  if (deckErrors.length) gateReasons.push(`after has deck/TypeError/Error entries: ${deckErrors.join(" | ")}`);
  if (!tzm.ok) gateReasons.push(`tile_zoom_match failed: ${JSON.stringify(tzm.details)}`);
  if (afterUnexpected404s.length) gateReasons.push(`unexpected tile 404s: ${afterUnexpected404s.map((x)=>x.url).join(" | ")}`);

  const passed = gateReasons.length === 0;

  const fullResByLayer = {};
  for (const [layer, d] of Object.entries(tzm.details||{})) fullResByLayer[layer] = { observed_z: d.requested_max_z, expected_z_at_max_k: tzm.expected_max_z_at_final_k, zmax: d.zmax };

  // screenshots: reuse committed if pixels unchanged? "reuse committed screenshots if the pixels are unchanged; regenerate if needed."
  // Easier to regenerate in separate run/context after measurement (and we can compare hashes with existing if desired). Regenerate.
  mkdirSync(OUT, { recursive: true });
  let screenshots = [];
  if (!SKIP_SCREENSHOTS) {
    try {
      console.log("taking screenshots (separate browser run)...");
      screenshots = await takeScreenshots(resolve("web/out"), fixtureShowcase, OUT);
      try { if (existsSync(join(OUT, "after-phone.png"))) rmSync(join(OUT, "after-phone.png")); } catch {}
    } catch (e) {
      console.error("screenshot pass failed:", e && (e.stack||e.message||String(e)));
      // try to keep existing screenshots metadata
      try {
        const names = ["after-lidar-area.png","after-ortho-area.png","after-height-area.png","after-lidar-full.png","after-ortho-full.png","after-height-full.png","after-lidar-phone.png"];
        screenshots = names.filter((n)=>existsSync(join(OUT,n))).map((n)=>({ path:`docs/evidence/288/${n}`, sha256: sha256File(join(OUT,n)), pixel_variance: pixelVariance(join(OUT,n)) }));
      } catch {}
      gateReasons.push(`screenshot pass failed: ${e && e.message || e}`);
    }
  }

  // recompute passed in case screenshot failure added reason? screenshot failure isn't in listed gate but don't claim pass
  const passedFinal = gateReasons.length === 0;

  const panTop = { before: (before.pan.long_tasks||[]).slice(0,10), after: (after.pan.long_tasks||[]).slice(0,10) };
  const metrics = {
    venue, generated_at: new Date().toISOString(), base_ref: BEFORE_REF, fixture_source: sourceLabel,
    commits: { before: beforeHash, after: commitsAfter },
    git_head: (dirtyNow || preRunStatus || {}).head || commitsAfter,
    git_status_porcelain_pre_run: (preRunStatus || {}).status_porcelain || "",
    git_status_porcelain_now: (dirtyNow || {}).status_porcelain || "",
    publish_report: { tile_version: publishReport.tile_version || null },
    scene: { extent: fixtureProvenance.extent, bbox: fixtureProvenance.bbox, zmax: fixtureProvenance.layers ? Object.fromEntries(Object.entries(fixtureProvenance.layers).map(([k,v])=>[k,v.zmax])) : zmaxLayers, facility: after.facility },
    live: { showcase_reachable: mirrorReport.reachable, mosaic_present: mirrorReport.mosaic_present, area_status: mirrorReport.area_status, report_status: mirrorReport.report_status, tiles_200: mirrorReport.tiles_200, tiles_404: mirrorReport.tiles_404, mirrored_bytes: mirrorReport.mirrored_bytes },
    renderer: { before: before.renderer, after: after.renderer, match: before.renderer === after.renderer },
    whole: { before: before.whole, after: after.whole },
    gesture: { before: before.gesture, after: after.gesture },
    zoom_transition: {
      before: { median: before.zoom_transition.median, p95: before.zoom_transition.p95, samples: before.zoom_transition.samples, image_count: before.zoomWindow ? before.zoomWindow.count : (before.gesture.count), image_bytes: before.zoomWindow ? before.zoomWindow.bytes : undefined },
      after: { median: after.zoom_transition.median, p95: after.zoom_transition.p95, samples: after.zoom_transition.samples, image_count: after.zoomWindow ? after.zoomWindow.count : (after.gesture.count), image_bytes: after.zoomWindow ? after.zoomWindow.bytes : undefined },
      note: "not gated; measured over zoom clicks/setup (20 clicks) to settle before pan window",
    },
    pan: {
      before: { median: before.pan.median, p95: before.pan.p95, samples: before.pan.samples, image_count: before.during_gesture.count, image_bytes: before.during_gesture.bytes },
      after: { median: after.pan.median, p95: after.pan.p95, samples: after.pan.samples, image_count: after.during_gesture.count, image_bytes: after.during_gesture.bytes },
      long_tasks_top10: panTop,
      gate_window: "10s wheel pan after full zoom (20 clicks) + 5s settle",
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
      zoom_transition_p95_before: before.zoom_transition.p95, zoom_transition_p95_after: after.zoom_transition.p95,
      pan_p95_before: before.pan.p95, pan_p95_after: after.pan.p95,
      pan_median_before: before.pan.median, pan_median_after: after.pan.median,
      whole_count_before: before.whole.count, whole_count_after: after.whole.count,
      before_source: "measured",
    },
    gate: { passed: passedFinal, reasons: gateReasons, window: "pan" },
  };
  writeFileSync(join(OUT, "metrics.json"), JSON.stringify(metrics, null, 2));

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
    `- top pan long tasks (before): ${fmtLT((before.pan.long_tasks||[]).slice(0,5))}`,
    `- top pan long tasks (after): ${fmtLT((after.pan.long_tasks||[]).slice(0,5))}`,
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
    ...screenshots.map((s)=>`- ${s.path} sha256=${s.sha256} variance=${s.pixel_variance}`),
    "",
    `Gate (pan window): ${passedFinal ? "passed" : "failed"}`,
    ...(gateReasons.length ? ["Reasons:", ...gateReasons.map((r)=>`- ${r}`)] : []),
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
    `- top long tasks (after): ${fmtLT((after.pan.long_tasks||[]).slice(0,5))}`,
    "",
    "Context:",
    `- whole image count: ${before.whole.count} -> ${after.whole.count}`,
    `- gesture (combined) image count: ${before.gesture.count} -> ${after.gesture.count}`,
    `- renderer: ${before.renderer === after.renderer ? "match" : "mismatch"} (${after.renderer})`,
    `- final scale text: "${after.final_zoom.scale_text}" (before "${before.final_zoom.scale_text}")`,
    `- drag_delta: before=${!!(before.drag_delta && before.drag_delta.changed)} after=${!!(after.drag_delta && after.drag_delta.changed)}`,
    `- 404s: unexpected_tile=${afterUnexpected404s.length} known_app=${afterKnownApp404s.length}`,
    "",
    `Gate (pan): ${passedFinal ? "passed" : "failed"}.`,
    ...(gateReasons.length ? gateReasons.map((r)=>`- ${r}`) : []),
    "",
    "Screenshots: see docs/evidence/288/README.md (sha256 + variance).",
    "",
  ].join("\n");
  writeFileSync(join(OUT, "summary.md"), summary);

  if (passedFinal) {
    try { rmSync(join(OUT, "need-human.md")); } catch {}
  }

  console.log("GATE", passedFinal, gateReasons);
  console.log(`PAN before median/p95/samples=${before.pan.median}/${before.pan.p95}/${before.pan.samples} after=${after.pan.median}/${after.pan.p95}/${after.pan.samples}`);
  console.log(`ZOOM before median/p95/samples=${before.zoom_transition.median}/${before.zoom_transition.p95}/${before.zoom_transition.samples} after=${after.zoom_transition.median}/${after.zoom_transition.p95}/${after.zoom_transition.samples}`);
  return { passed: passedFinal, gateReasons, metrics, screenshots };
}

// ---- orchestration ----
async function runOrchestrate() {
  const preRunStatus = dirtyTreeGuard();
  mkdirSync(OUT, { recursive: true });
  const ctx = await ensureFixtureAndBuilds(preRunStatus);
  const { fixtureShowcase, beforeHash, baseDir } = ctx;

  // Run sides as separate node invocations (halves per-process memory / isolates crashes)
  const beforeJson = "/tmp/288-before.json";
  const afterJson = "/tmp/288-after.json";
  try { rmSync(beforeJson); } catch {}
  try { rmSync(afterJson); } catch {}

  const node = process.execPath;
  function runSideProc(side, jsonPath, buildDir) {
    const a = [__filename, "--side", side, "--out-json", jsonPath, "--fixture", fixtureShowcase, "--build-dir", buildDir, "--before", BEFORE_REF];
    console.log("spawn:", node, a.join(" "));
    const r = spawnSync(node, a, { stdio: "inherit", env: process.env, cwd: process.cwd() });
    if (r.error) throw r.error;
    if (r.status !== 0) throw new Error(`side ${side} process exited ${r.status}`);
    if (!existsSync(jsonPath)) throw new Error(`side ${side} produced no json`);
    return JSON.parse(readFileSync(jsonPath, "utf8"));
  }

  let before, after;
  try {
    before = runSideProc("before", beforeJson, join(baseDir, "web", "out"));
  } catch (e) {
    console.error("BEFORE side failed:", e && (e.stack||e.message||String(e)));
    throw e;
  }
  try {
    after = runSideProc("after", afterJson, join(process.cwd(), "web", "out"));
  } catch (e) {
    console.error("AFTER side failed:", e && (e.stack||e.message||String(e)));
    throw e;
  }

  const dirtyNow = { head: execSync("git rev-parse HEAD", {encoding:"utf8"}).trim(), status_porcelain: execSync("git status --porcelain --untracked-files=no", {encoding:"utf8"}) };
  const commitsAfter = dirtyNow.head;
  const res = await doCombine(before, after, { ...ctx, commitsAfter, dirtyNow });
  if (!res.passed) process.exit(1);
}

async function runCombine() {
  if (!BEFORE_JSON || !AFTER_JSON) { console.error("--before-json and --after-json required"); process.exit(2); }
  const before = JSON.parse(readFileSync(BEFORE_JSON, "utf8"));
  const after = JSON.parse(readFileSync(AFTER_JSON, "utf8"));
  const fixtureShowcase = FIXTURE || join("/tmp","288-fixture","showcase");
  const fixtureDir = join("/tmp","288-fixture");
  const beforeHash = execSync(`git rev-parse ${BEFORE_REF}`, { encoding: "utf8" }).trim();
  const mirrorReport = mirrorReportFromCache(join("/tmp","288-mirror"));
  const venue = mirrorReport.reachable ? `live-mirror: Seaport (${(mirrorReport.drives||[]).length} drives)` : "unknown";
  const preRunStatus = { head: beforeHash, status_porcelain: "" };
  const dirtyNow = { head: execSync("git rev-parse HEAD", {encoding:"utf8"}).trim(), status_porcelain: execSync("git status --porcelain --untracked-files=no", {encoding:"utf8"}) };
  const res = await doCombine(before, after, { venue, sourceLabel: "live-mirror", mirrorReport, fixtureShowcase, fixtureDir, beforeHash, commitsAfter: dirtyNow.head, preRunStatus, dirtyNow });
  if (!res.passed) process.exit(1);
}

(async () => {
  try {
    if (SIDE) await runSide();
    else if (COMBINE) await runCombine();
    else await runOrchestrate();
  } catch (e) {
    console.error(e && (e.stack || e.message || String(e)));
    process.exit(1);
  }
})();
