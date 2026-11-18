// web/scripts/measure-288.mjs
import { spawn, execSync } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, writeFileSync, mkdirSync, rmSync, existsSync, readdirSync, statSync } from "node:fs";
import { join, extname, resolve } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
const __dirname = fileURLToPath(new URL(".", import.meta.url));
process.env.LD_LIBRARY_PATH = ["/tmp/scratchpad","/tmp/chromelibs/lib/x86_64-linux-gnu","/tmp/chromelibs/usr/lib/x86_64-linux-gnu","/tmp/scratchpad/chromelibs2/lib/x86_64-linux-gnu","/tmp/scratchpad/chromelibs2/usr/lib/x86_64-linux-gnu", process.env.LD_LIBRARY_PATH].filter(Boolean).join(":");

const args = process.argv.slice(2);
function arg(name){ const i=args.indexOf(name); return i>=0?args[i+1]:null; }
const BEFORE_REF = arg("--before") || "1d3951c";
const OUT = resolve(arg("--out") || "docs/evidence/288");

mkdirSync(OUT, {recursive:true});

function resolveChromium(){
  if(process.env.CHROME_BIN && existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  if(process.env.CHROME && existsSync(process.env.CHROME)) return process.env.CHROME;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || join(homedir(),".cache","ms-playwright");
  try {
    const dirs = readdirSync(base).filter(d=>d.startsWith("chromium-"));
    for(const d of dirs){
      for(const sub of ["chrome-linux64","chrome-linux"]){
        const cand = join(base,d,sub,"chrome");
        if(existsSync(cand)) return cand;
      }
    }
  } catch{}
  for(const name of ["chromium","chromium-browser","google-chrome","google-chrome-stable"]){
    try { return execSync(`which ${name}`, {encoding:"utf8"}).trim(); } catch{}
  }
  return null;
}
const CHROME = resolveChromium();
if(!CHROME){ console.error("No Chromium found. Run: npx playwright install chromium (or set CHROME_BIN=/path/to/chrome)"); process.exit(1); }
console.log("Chromium:", CHROME);

const MIME = {
  ".html":"text/html; charset=utf-8",".css":"text/css",".js":"application/javascript",
  ".mjs":"application/javascript",".json":"application/json",".geojson":"application/geo+json",
  ".webp":"image/webp",".png":"image/png",".svg":"image/svg+xml",".ico":"image/x-icon",
  ".woff2":"font/woff2",".wasm":"application/wasm",".txt":"text/plain",".csv":"text/csv",
};

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
const LIVE = "https://twin.papyrus-ai.net/showcase";

async function mirrorShowcase(dest){
  const report = { reachable:false, mosaic_present:false, files:[], drives:[], area_status:0, report_status:0 };
  mkdirSync(dest,{recursive:true});
  let areaRes, reportRes;
  try {
    areaRes = await fetch(LIVE+"/area.json");
    reportRes = await fetch(LIVE+"/publish_report.json");
  } catch(e){ report.reachable=false; return report; }
  report.area_status = areaRes.status;
  report.report_status = reportRes.status;
  if(!areaRes.ok || !reportRes.ok){ report.reachable=false; return report; }
  report.reachable=true;
  const areaText = await areaRes.text();
  const reportText = await reportRes.text();
  const area = JSON.parse(areaText);
  const pubReport = JSON.parse(reportText);
  report.mosaic_present = !!(pubReport.layers && Object.keys(pubReport.layers).length);
  writeFileSync(join(dest,"area.json"), areaText);
  writeFileSync(join(dest,"publish_report.json"), reportText);
  report.bytes_area = areaText.length;
  report.bytes_report = reportText.length;
  const drives = area.drives;
  report.drives = drives.map(d=>d.run_id);
  const runFiles = ["manifest.json","twin.geojson","profile.csv","centrelines.geojson"];
  for(const d of drives){
    const rid = d.run_id;
    mkdirSync(join(dest,rid),{recursive:true});
    for(const f of runFiles){
      const r = await fetch(LIVE+"/"+rid+"/"+f);
      if(r.ok){ const b=Buffer.from(await r.arrayBuffer()); writeFileSync(join(dest,rid,f), b); }
    }
    const layers = ["lidar","ortho","height","coverage"];
    for(const layer of layers){
      const metaUrl = LIVE+"/tiles/"+rid+"/"+layer+"/meta.json";
      const r = await fetch(metaUrl);
      if(!r.ok) continue;
      const metaText = await r.text();
      const meta = JSON.parse(metaText);
      const mdir = join(dest,"tiles",rid,layer);
      mkdirSync(mdir,{recursive:true});
      writeFileSync(join(mdir,"meta.json"), metaText);
      const zmax = meta.zmax;
      const tasks = [];
      for(let z=0; z<=zmax; z++){
        const n = 1<<z;
        for(let x=0; x<n; x++){
          for(let y=0; y<n; y++){
            tasks.push({z,x,y});
          }
        }
      }
      let idx=0;
      const concurrency=16;
      async function worker(){
        while(idx < tasks.length){
          const t = tasks[idx++];
          const url = LIVE+"/tiles/"+rid+"/"+layer+"/"+t.z+"/"+t.x+"/"+t.y+".webp";
          const r = await fetch(url);
          if(r.ok){
            const b = Buffer.from(await r.arrayBuffer());
            const dir = join(dest,"tiles",rid,layer,String(t.z),String(t.x));
            mkdirSync(dir,{recursive:true});
            writeFileSync(join(dir,t.y+".webp"), b);
          }
        }
      }
      const workers = Array.from({length:concurrency},()=>worker());
      await Promise.all(workers);
    }
  }
  return report;
}

async function main(){
  const mirrorDir = join("/tmp","288-mirror");
  rmSync(mirrorDir,{recursive:true,force:true});
  const mirrorReport = await mirrorShowcase(mirrorDir);
  let venue, fixtureSrc, sourceLabel;
  let mirrorOk = mirrorReport.reachable;
  if(mirrorOk){
    for(const d of mirrorReport.drives){
      if(!existsSync(join(mirrorDir,"tiles",d,"lidar","meta.json"))){ mirrorOk=false; break; }
    }
  }
  if(mirrorOk){
    venue = "live-mirror: Seaport ("+mirrorReport.drives.length+" drives)";
    fixtureSrc = mirrorDir;
    sourceLabel = "live-mirror";
  } else {
    venue = "synthetic: committed fake showcase (live Seaport unreachable)";
    const baseDir = "/tmp/288-before";
    rmSync(baseDir,{recursive:true,force:true});
    mkdirSync(baseDir,{recursive:true});
    execSync(`git archive ${BEFORE_REF} | tar -x -C ${baseDir}`, {stdio:"inherit"});
    execSync(`bash ${baseDir}/web/scripts/fake-showcase.sh`, {stdio:"inherit", cwd:baseDir});
    fixtureSrc = baseDir+"/web/public/showcase";
    sourceLabel = "synthetic";
  }

  const fixtureDir = join("/tmp","288-fixture");
  rmSync(fixtureDir,{recursive:true,force:true});
  mkdirSync(fixtureDir,{recursive:true});
  execSync(`uv run python scripts/mosaic_fixture.py --src ${fixtureSrc} --out ${fixtureDir} --source ${sourceLabel}`, {stdio:"inherit", env:{...process.env, PYTHONPATH: process.cwd()}});
  const fixtureShowcase = fixtureDir+"/showcase";

  const baseDir = "/tmp/288-before";
  if(!existsSync(baseDir+"/web/node_modules")){
    rmSync(baseDir,{recursive:true,force:true});
    mkdirSync(baseDir,{recursive:true});
    execSync(`git archive ${BEFORE_REF} | tar -x -C ${baseDir}`, {stdio:"inherit"});
  }
  if(!existsSync(baseDir+"/web/out")){
    execSync("npm ci", {cwd:baseDir+"/web", stdio:"inherit"});
    execSync("npm run build", {cwd:baseDir+"/web", stdio:"inherit"});
  }
  const afterDir = process.cwd();
  if(!existsSync(afterDir+"/web/out")){
    execSync("npm ci", {cwd:afterDir+"/web", stdio:"inherit"});
    execSync("npm run build", {cwd:afterDir+"/web", stdio:"inherit"});
  }

  function makeServer(rootOut, fixture){
    return createServer((req,res)=>{
      let url = req.url.split("?")[0];
      if(url==="/") url="/index.html";
      if(url.startsWith("/showcase/")){
        const rel = url.slice("/showcase/".length);
        const fpath = join(fixture, rel);
        if(!existsSync(fpath)){ res.statusCode=404; res.end("not found"); return; }
        const ext = extname(fpath).toLowerCase();
        res.setHeader("Content-Type", MIME[ext]||"application/octet-stream");
        res.end(readFileSync(fpath));
        return;
      }
      const fpath = join(rootOut, url.slice(1));
      if(!existsSync(fpath) || statSync(fpath).isDirectory()){ res.statusCode=404; res.end("not found"); return; }
      const ext = extname(fpath).toLowerCase();
      res.setHeader("Content-Type", MIME[ext]||"application/octet-stream");
      res.end(readFileSync(fpath));
    });
  }

  const beforeServer = makeServer(baseDir+"/web/out", fixtureShowcase);
  const afterServer = makeServer(afterDir+"/web/out", fixtureShowcase);
  await new Promise(r=>beforeServer.listen(0,"127.0.0.1",r));
  await new Promise(r=>afterServer.listen(0,"127.0.0.1",r));
  const beforePort = beforeServer.address().port;
  const afterPort = afterServer.address().port;
  console.log("ports", beforePort, afterPort);

  const LAUNCH_ARGS = ["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader","--disable-dev-shm-usage","--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"];
  const browser = await chromium.launch({executablePath: CHROME, headless:true, args: LAUNCH_ARGS});

  async function rendererOf(page){
    return page.evaluate(() => {
      const c=document.createElement("canvas");
      const gl=c.getContext("webgl2")||c.getContext("webgl");
      const ext=gl.getExtension("WEBGL_debug_renderer_info");
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
    });
  }

  async function settle(page, inflightRef, timeout=10000){
    const start=Date.now();
    let lastZero=Date.now();
    while(Date.now()-start < timeout){
      if(inflightRef.n===0){
        if(Date.now()-lastZero >= 300) return;
      } else lastZero=Date.now();
      await sleep(50);
    }
  }

  async function measureSide(baseURL){
    const context = await browser.newContext({viewport:{width:1440,height:900}, deviceScaleFactor:1});
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(String(e)));
    page.on('console', m => { if(m.type()==='error') pageErrors.push(m.text()); });

    // area data
    const area = await (await fetch(baseURL+"/showcase/area.json")).json();
    const inter = (area.facilities||[]).find(f=>f.type==="intersection") || (area.facilities||[])[0];
    const facilityId = inter ? inter.id : null;

    // CDP
    const cdp = await context.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Performance.enable');
    await cdp.send('Network.setCacheDisabled', {cacheDisabled:true});

    const imgReq = new Map();
    const whole = {count:0, bytes:0};
    const gesture = {count:0, bytes:0};
    let current = whole;
    const inflightRef = {n:0};
    cdp.on('Network.responseReceived', p => {
      const ct = ((p.response.headers||{})['content-type']||'').toLowerCase();
      const isImg = p.type === 'Image' || ct.includes('image');
      imgReq.set(p.requestId, isImg);
      if(isImg){ whole.count++; inflightRef.n++; if(current===gesture) gesture.count++; }
    });
    cdp.on('Network.loadingFinished', p => {
      const isImg = imgReq.get(p.requestId);
      if(isImg){ whole.bytes += (p.encodedDataLength||0); inflightRef.n=Math.max(0,inflightRef.n-1); if(current===gesture) gesture.bytes += (p.encodedDataLength||0); }
      imgReq.delete(p.requestId);
    });
    cdp.on('Network.loadingFailed', p => {
      if(imgReq.get(p.requestId)){ inflightRef.n=Math.max(0,inflightRef.n-1); }
      imgReq.delete(p.requestId);
    });

    // open facility via query param
    let facilityHow = null;
    let url = baseURL;
    if(facilityId){ url = baseURL + "?f=" + encodeURIComponent(facilityId); }
    await page.goto(url, {waitUntil:'domcontentloaded'});
    await page.waitForSelector('.pan', {timeout:15000});
    const box = await page.locator('.pan').boundingBox();
    if(!box || box.width===0 || box.height===0){
      // try click facility polygon
      facilityHow = "area-fit (canvas not ready)";
    } else {
      facilityHow = facilityId ? "query-param" : "area-fit";
    }
    await settle(page, inflightRef, 10000);

    // reload with caches disabled (already), wait settle
    await page.reload({waitUntil:'domcontentloaded'});
    await page.waitForSelector('.pan', {timeout:15000});
    await settle(page, inflightRef, 10000);

    // zoom to full resolution: click zoom in 15 times
    for(let i=0;i<15;i++){
      await page.click('[aria-label="Zoom in"]').catch(()=>{});
      await sleep(80);
    }
    await settle(page, inflightRef, 10000);

    // renderer
    const renderer = await rendererOf(page);

    // gesture window: start gesture counter
    const gestureStart = {count:gesture.count, bytes:gesture.bytes};
    gesture.count = 0; gesture.bytes = 0; // reset gesture to measure during window only
    // but whole keeps counting; gesture separate
    current = gesture;
    // rAF sampling 10s
    const rafPromise = page.evaluate(() => new Promise(resolve => {
      const out=[]; let last=performance.now(); const start=last;
      function frame(t){ if(out.length>0) out.push(t-last); last=t; if(t-start < 10000) requestAnimationFrame(frame); else resolve(out); }
      requestAnimationFrame(frame);
    }));
    // circular drag
    const dragPromise = (async () => {
      const b = await page.locator('.pan').boundingBox();
      if(!b) return;
      const cx=b.x+b.width/2, cy=b.y+b.height/2;
      const r=Math.min(360, 0.4*Math.min(b.width,b.height));
      await page.mouse.move(cx+r, cy);
      await page.mouse.down();
      const steps=60;
      for(let i=0;i<=steps;i++){
        const ang=(i/steps)*2*Math.PI;
        await page.mouse.move(cx+Math.cos(ang)*r, cy+Math.sin(ang)*r);
        await sleep(10000/steps);
      }
      await page.mouse.up();
    })();
    await Promise.all([rafPromise, dragPromise]);
    current = whole; // stop gesture counting (whole still counted via always? we increment whole always regardless; current only gates gesture)
    // Actually current no longer matters for whole; gesture increments only when current===gesture, which we turned off.

    const deltas = await rafPromise;
    // median + p95 nearest rank
    const sorted = [...deltas].sort((a,b)=>a-b);
    const median = sorted.length? sorted[Math.floor(sorted.length/2)] : 0;
    const p95idx = Math.ceil(0.95*sorted.length) - 1;
    const p95 = sorted.length? sorted[Math.max(0,p95idx)] : 0;

    // heap
    const metrics = await cdp.send('Performance.getMetrics');
    const heapMetric = (metrics.metrics||[]).find(m=>m.name==='JSHeapUsedSize');
    const heap = heapMetric ? heapMetric.value : null;

    // final zoom evidence
    const scaleText = await page.locator('.scale').textContent().catch(()=>null);

    // page errors
    const errors = [...pageErrors];

    await context.close();

    return {
      facility: facilityId ? {id:facilityId, how:facilityHow} : null,
      renderer,
      frame_ms: {median: Math.round(median*100)/100, p95: Math.round(p95*100)/100, samples: deltas.length},
      whole: {count: whole.count, bytes: whole.bytes},
      gesture: {count: gesture.count, bytes: gesture.bytes},
      heap,
      final_zoom: {scale_text: (scaleText||'').trim(), clicks:15},
      page_errors: errors,
    };
  }

  const before = await measureSide(`http://127.0.0.1:${beforePort}`);
  const after = await measureSide(`http://127.0.0.1:${afterPort}`);

  // screenshots (after only)
  const shotCtx = await browser.newContext({viewport:{width:1440,height:900}, deviceScaleFactor:1});
  const shotPage = await shotCtx.newPage();
  const shotErrors=[];
  shotPage.on('pageerror', e=>shotErrors.push(String(e)));
  const area = await (await fetch(`http://127.0.0.1:${afterPort}/showcase/area.json`)).json();
  const inter = (area.facilities||[]).find(f=>f.type==="intersection") || (area.facilities||[])[0];
  const fid = inter ? inter.id : null;

  async function ensureVectorsOn(p){
    for(const name of ['Markings','Crosswalks','Curbs']){
      const btn = p.locator('button.tg').filter({hasText:name});
      const pressed = await btn.getAttribute('aria-pressed').catch(()=>null);
      if(pressed !== 'true') await btn.click().catch(()=>{});
    }
  }
  async function setBackground(p, target){
    for(const name of ['Height','Lidar','Orthoimage']){
      const btn = p.locator('button.tg').filter({hasText:name});
      const pressed = await btn.getAttribute('aria-pressed').catch(()=>null);
      if(name===target){ if(pressed!=='true') await btn.click().catch(()=>{}); }
      else { if(pressed==='true') await btn.click().catch(()=>{}); }
      await sleep(150);
    }
  }
  async function waitCanvas(p){ await p.waitForSelector('.pan',{timeout:15000}); await sleep(1500); }

  // area view
  await shotPage.goto(`http://127.0.0.1:${afterPort}` + (fid? '?f='+fid : ''), {waitUntil:'domcontentloaded'});
  // actually area view should be no facility for area screenshots; use base
  await shotPage.goto(`http://127.0.0.1:${afterPort}`, {waitUntil:'domcontentloaded'});
  await waitCanvas(shotPage);
  // fit all
  await shotPage.click('[aria-label="Fit"]').catch(()=>{});
  await sleep(1000);

  const layers = [
    {key:'lidar', label:'Lidar'},
    {key:'ortho', label:'Orthoimage'},
    {key:'height', label:'Height'},
  ];
  for(const L of layers){
    await setBackground(shotPage, L.label);
    await ensureVectorsOn(shotPage);
    await sleep(1500);
    await shotPage.screenshot({path: join(OUT, `after-${L.key}-area.png`)});
  }

  // full zoom: open facility
  if(fid){
    await shotPage.goto(`http://127.0.0.1:${afterPort}?f=${encodeURIComponent(fid)}`, {waitUntil:'domcontentloaded'});
    await waitCanvas(shotPage);
    for(let i=0;i<15;i++){ await shotPage.click('[aria-label="Zoom in"]').catch(()=>{}); await sleep(80); }
    await sleep(1500);
  }
  for(const L of layers){
    await setBackground(shotPage, L.label);
    await ensureVectorsOn(shotPage);
    await sleep(1500);
    await shotPage.screenshot({path: join(OUT, `after-${L.key}-full.png`)});
  }

  // phone
  const phoneCtx = await browser.newContext({viewport:{width:390,height:844}, deviceScaleFactor:1});
  const phonePage = await phoneCtx.newPage();
  await phonePage.goto(`http://127.0.0.1:${afterPort}` + (fid? '?f='+encodeURIComponent(fid) : ''), {waitUntil:'domcontentloaded'});
  await phonePage.waitForSelector('.pan',{timeout:15000});
  await sleep(2000);
  await phonePage.screenshot({path: join(OUT, 'after-phone.png')});
  await phoneCtx.close();

  await shotCtx.close();
  await browser.close();
  beforeServer.close();
  afterServer.close();

  // metrics
  const beforeRenderer = before.renderer;
  const afterRenderer = after.renderer;
  const rendererMatch = beforeRenderer === afterRenderer;

  const metrics = {
    venue,
    live: { showcase_reachable: mirrorReport.reachable, mosaic_present: mirrorReport.mosaic_present, area_status: mirrorReport.area_status, report_status: mirrorReport.report_status, bytes_area: mirrorReport.bytes_area, bytes_report: mirrorReport.bytes_report },
    commits: { before: BEFORE_REF, after: execSync("git rev-parse HEAD",{encoding:"utf8"}).trim() },
    renderer: { before: beforeRenderer, after: afterRenderer, match: rendererMatch },
    facility: after.facility,
    whole: { before: before.whole, after: after.whole },
    gesture: { before: before.gesture, after: after.gesture },
    heap: { before: before.heap, after: after.heap },
    frame_ms: { before: before.frame_ms, after: after.frame_ms },
    final_zoom: { before: before.final_zoom, after: after.final_zoom },
    page_errors: { before: before.page_errors, after: after.page_errors },
    limitations: { full_res_by_layer: "displayed level vs published zmax at MAX_K (see docs)" },
    comparison: {
      frame_p95_before: before.frame_ms.p95, frame_p95_after: after.frame_ms.p95,
      whole_count_before: before.whole.count, whole_count_after: after.whole.count,
    },
  };

  const gateReasons = [];
  let passed = true;
  if(!(after.frame_ms.p95 < before.frame_ms.p95)){ passed=false; gateReasons.push(`frame p95 not improved: ${before.frame_ms.p95} -> ${after.frame_ms.p95}`); }
  if(!(after.whole.count < before.whole.count)){ passed=false; gateReasons.push(`whole image count not reduced: ${before.whole.count} -> ${after.whole.count}`); }
  if(!rendererMatch){ passed=false; gateReasons.push(`renderer mismatch: ${beforeRenderer} vs ${afterRenderer}`); }
  const zoomMatch = before.final_zoom.scale_text === after.final_zoom.scale_text;
  if(!zoomMatch){ passed=false; gateReasons.push(`final zoom mismatch: "${before.final_zoom.scale_text}" vs "${after.final_zoom.scale_text}"`); }
  if(before.heap && after.heap && after.heap > 1.25*before.heap){ passed=false; gateReasons.push(`heap exceeded 1.25x: ${before.heap} -> ${after.heap}`); }
  if(before.page_errors.length || after.page_errors.length){ passed=false; gateReasons.push(`page errors: before=${before.page_errors.length} after=${after.page_errors.length}`); }

  metrics.gate = { passed, reasons: gateReasons };
  writeFileSync(join(OUT,"metrics.json"), JSON.stringify(metrics,null,2));
  console.log("Wrote", join(OUT,"metrics.json"));
  console.log("GATE", passed, gateReasons);

  if(!passed){
    const nh = `# Need human — #288 measurement gate failed\n\nVenue: ${venue}\n\nFailing pairs:\n${gateReasons.map(r=>"- "+r).join("\n")}\n\nBefore: frame p95 ${before.frame_ms.p95} ms, images ${before.whole.count} (${before.whole.bytes} B), heap ${before.heap}, renderer ${beforeRenderer}\nAfter:  frame p95 ${after.frame_ms.p95} ms, images ${after.whole.count} (${after.whole.bytes} B), heap ${after.heap}, renderer ${afterRenderer}\n`;
    writeFileSync(join(OUT,"need-human.md"), nh);
    process.exit(1);
  }
  process.exit(0);
}

main().catch(e=>{ console.error(e); process.exit(1); });
