// web/scripts/profile-288.mjs — AFTER-only profiler for #288
import { execSync } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, extname, resolve } from "node:path";
import { homedir } from "node:os";
import { chromium } from "playwright-core";

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
const OUT = resolve(arg("--out") || "/tmp/288-profile");
mkdirSync(OUT, { recursive: true });

function resolveChromium() {
  if (process.env.CHROME_BIN && existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  if (process.env.CHROME && existsSync(process.env.CHROME)) return process.env.CHROME;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || join(homedir(), ".cache", "ms-playwright");
  try {
    const dirs = readdirSync(base).filter((d) => d.startsWith("chromium-"));
    for (const d of dirs) for (const sub of ["chrome-linux64", "chrome-linux"]) {
      const cand = join(base, d, sub, "chrome");
      if (existsSync(cand)) return cand;
    }
  } catch {}
  for (const name of ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]) {
    try { return execSync(`which ${name}`, { encoding: "utf8" }).trim(); } catch {}
  }
  return null;
}
const CHROME = resolveChromium();
if (!CHROME) { console.error("No Chromium found"); process.exit(1); }

const MIME = {
  ".html":"text/html; charset=utf-8",".css":"text/css",".js":"application/javascript",
  ".mjs":"application/javascript",".json":"application/json",".geojson":"application/geo+json",
  ".webp":"image/webp",".png":"image/png",".svg":"image/svg+xml",".ico":"image/x-icon",
  ".woff2":"font/woff2",".wasm":"application/wasm",".txt":"text/plain",".csv":"text/csv",
};
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

function makeServer(rootOut, fixture) {
  return createServer((req, res) => {
    let url = req.url.split("?")[0];
    if (url === "/") url = "/index.html";
    if (url.startsWith("/showcase/")) {
      const fpath = join(fixture, url.slice("/showcase/".length));
      if (!existsSync(fpath) || statSync(fpath).isDirectory()) { res.statusCode = 404; res.end("not found"); return; }
      res.setHeader("Content-Type", MIME[extname(fpath).toLowerCase()] || "application/octet-stream");
      res.end(readFileSync(fpath)); return;
    }
    const fpath = join(rootOut, url.slice(1));
    if (!existsSync(fpath) || statSync(fpath).isDirectory()) { res.statusCode = 404; res.end("not found"); return; }
    res.setHeader("Content-Type", MIME[extname(fpath).toLowerCase()] || "application/octet-stream");
    res.end(readFileSync(fpath));
  });
}

function dirtyTreeGuard() {
  const raw = execSync("git status --porcelain --untracked-files=no", { encoding: "utf8" });
  const offending = raw.split("\n").filter(Boolean).filter((line) => {
    const path = line.slice(3).replace(/^"|"$/g, "");
    return !(path.startsWith("web/out/") || path === "web/out" || path.startsWith("web/.next/") || path === "web/.next");
  });
  if (offending.length) { console.error("dirty-tree guard failed:"); for (const l of offending) console.error(l); process.exit(1); }
}

async function main() {
  dirtyTreeGuard();
  const mirrorDir = "/tmp/288-mirror";
  const fixtureDir = "/tmp/288-fixture";
  const fixtureShowcase = join(fixtureDir, "showcase");
  if (!existsSync(join(mirrorDir, "area.json"))) throw new Error("missing /tmp/288-mirror");
  if (!existsSync(join(fixtureShowcase, "area.json"))) {
    execSync(["uv","run","python","scripts/mosaic_fixture.py","--src",mirrorDir,"--out",fixtureDir,"--source","live-mirror","--tiles-200","0","--tiles-404","0","--mirrored-bytes","0"].map(x=>JSON.stringify(x)).join(" "), { stdio: "inherit", env: { ...process.env, PYTHONPATH: process.cwd() } });
  }
  const afterOut = resolve("web/out");
  if (!existsSync(join(afterOut, "index.html"))) execSync("npm run build", { cwd: "web", stdio: "inherit" });

  const server = makeServer(afterOut, fixtureShowcase);
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  console.log("after port", port, "chrome", CHROME);

  const LAUNCH_ARGS = ["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader","--disable-dev-shm-usage","--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"];
  const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: LAUNCH_ARGS });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Performance.enable");

  const traceChunks = [];
  cdp.on("Tracing.dataCollected", (e) => traceChunks.push(...(e.value || [])));
  let tracingDone;
  const tracingComplete = new Promise((r) => { tracingDone = r; });
  cdp.on("Tracing.tracingComplete", () => tracingDone());

  const area = JSON.parse(readFileSync(join(fixtureShowcase, "area.json"), "utf8"));
  const inter = (area.facilities || []).find((f) => f.type === "intersection") || (area.facilities || [])[0];
  const facilityId = inter ? inter.id : null;
  const url = `http://127.0.0.1:${port}` + (facilityId ? `?f=${encodeURIComponent(facilityId)}` : "");

  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".pan", { timeout: 15000 });
  await page.waitForTimeout(3000);

  await page.evaluate(() => {
    window.__PROFILE_288 = true;
    window.__renders = 0;
    window.__longtasks = [];
    window.__frames = [];
    try {
      const obs = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          let attribution = [];
          try {
            if (e.attribution) attribution = Array.from(e.attribution).map((a) => ({
              name: a.name, containerType: a.containerType, containerName: a.containerName, containerSrc: a.containerSrc
            }));
          } catch {}
          window.__longtasks.push({ startTime: e.startTime, duration: e.duration, name: e.name, attribution });
        }
      });
      obs.observe({ entryTypes: ["longtask"] });
    } catch {}
    let last = performance.now();
    window.__rec = true;
    const tick = (t) => { window.__frames.push(t - last); last = t; if (window.__rec) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });

  await cdp.send("Tracing.start", {
    categories: "devtools.timeline,disabled-by-default-devtools.timeline,blink.user_timing,v8,disabled-by-default-v8.gc",
    options: "sampling-frequency=10000",
  });

  const panBox = await page.locator(".pan").boundingBox();
  const pcx = panBox ? panBox.x + panBox.width / 2 : 720;
  const pcy = panBox ? panBox.y + panBox.height / 2 : 450;
  for (let i = 0; i < 20; i++) { await page.click('[aria-label="Zoom in"]').catch(() => {}); await sleep(50); }
  await page.waitForTimeout(1500);
  await page.mouse.move(pcx, pcy);
  for (let i = 0; i < 40; i++) {
    const dx = Math.round(Math.cos(i * 0.4) * 40);
    const dy = Math.round(Math.sin(i * 0.4) * 40);
    await page.mouse.wheel(dx, dy);
    await sleep(120);
  }
  await page.waitForTimeout(1500);

  await page.evaluate(() => { window.__rec = false; });
  await cdp.send("Tracing.end");
  await tracingComplete;

  const result = await page.evaluate(() => {
    const entries = performance.getEntriesByType("measure").map((e) => ({ name: e.name, duration: e.duration, startTime: e.startTime }));
    return { renders: window.__renders || 0, longtasks: window.__longtasks || [], frames: window.__frames || [], measures: entries };
  });

  writeFileSync(join(OUT, "trace.json"), JSON.stringify({ traceEvents: traceChunks }));

  const byName = new Map();
  for (const ev of traceChunks) {
    const dur = ev.dur || 0; if (!dur || dur <= 0) continue;
    const key = `${ev.name || "unknown"}|${ev.cat || ""}`;
    const cur = byName.get(key) || { name: ev.name || "unknown", cat: ev.cat || "", count: 0, total_dur_us: 0, max_dur_us: 0 };
    cur.count++; cur.total_dur_us += dur; cur.max_dur_us = Math.max(cur.max_dur_us, dur);
    byName.set(key, cur);
  }
  const topTrace = [...byName.values()].sort((a,b)=>b.total_dur_us-a.total_dur_us).slice(0,30).map(e => ({...e,total_ms:+(e.total_dur_us/1000).toFixed(2),max_ms:+(e.max_dur_us/1000).toFixed(2)}));

  const frames = result.frames || [];
  const sf = [...frames].sort((a,b)=>a-b);
  const p95 = sf.length ? sf[Math.min(sf.length-1, Math.ceil(0.95*sf.length)-1)] : null;
  const med = sf.length ? sf[Math.floor(sf.length/2)] : null;

  const measureAgg = (() => {
    const m = new Map();
    for (const e of result.measures) { const c = m.get(e.name)||{name:e.name,count:0,total:0,max:0}; c.count++; c.total+=e.duration; c.max=Math.max(c.max,e.duration); m.set(e.name,c); }
    return [...m.values()].sort((a,b)=>b.total-a.total).slice(0,50).map(e=>({...e,total:+e.total.toFixed(2),max:+e.max.toFixed(2)}));
  })();

  const summary = {
    renders: result.renders,
    longtask_count: result.longtasks.length,
    longtasks_top20: [...result.longtasks].sort((a,b)=>b.duration-a.duration).slice(0,20),
    frame: { samples: frames.length, median_ms: med, p95_ms: p95 },
    measures_count: result.measures.length,
    measures_top50_by_total: measureAgg,
    top_trace_events: topTrace,
  };
  writeFileSync(join(OUT, "profile.json"), JSON.stringify(summary, null, 2));
  writeFileSync(join(OUT, "longtasks.json"), JSON.stringify(result.longtasks, null, 2));
  writeFileSync(join(OUT, "measures.json"), JSON.stringify(result.measures, null, 2));

  console.log(JSON.stringify({
    renders: summary.renders,
    longtasks: summary.longtask_count,
    frame: summary.frame,
    top20_longtasks: summary.longtasks_top20.map(t=>({d:+t.duration.toFixed(1),s:+t.startTime.toFixed(1),a:t.attribution})),
    top_trace: topTrace.slice(0,12),
    top_measures: measureAgg.slice(0,15),
  }, null, 2));

  await context.close(); await browser.close(); server.close();
}

main().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
