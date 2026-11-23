# #443 evidence

- Route: `/evaluations` (static export, `web/out`)
- Build: `[ -d web/node_modules ] || npm --prefix web ci; npm --prefix web run build`
- Capture: `LD_LIBRARY_PATH=/tmp/evals-443/root/usr/lib/x86_64-linux-gnu:/tmp/evals-443/root/lib/x86_64-linux-gnu:/tmp/evals-443/root/usr/lib:/tmp/evals-443/root/lib HOME=/tmp/evals-443/home CHROME_BIN=/home/oc/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome node web/scripts/shoot-evals.mjs`
- Viewports: desktop 1440x900, phone 390x844; deviceScaleFactor 1
- Browser: chromium /home/oc/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
- Desktop: desktop.png sha256=03cd8ed5f7334a4dda19aa3397fb6975b235f88c4fe13fd5969b616114259403
- Phone: phone.png sha256=fa5835cbbf7b58f685a53142273aee98ca16c008e821089c8d9717bef8aeec82
- Content: desktop.png and phone.png are full-page captures after overriding the page root
  (`#eval-page`; `.page` is CSS-module-hashed) and `html,body`: plain-language cards/glossary
  ("How to read this"), briefing header (pass bar, best run per headline metric, verdict),
  three full-width trend charts with axes (PSNR linear, road depth p95 log, LiDAR ground p50 log)
  with y ticks with units and x run dates, pass-bar labels where defined, readable ticket links,
  comparison table scrolling inside its card with sticky first column showing the human variant
  in "Latest run", and the run list with whole run dates. phone.png shows the header on one line
  with its single back link fully visible and no horizontal clipping.
- The top-bar link is verified from the built `web/out/index.html` and module D review; a home-page screenshot is omitted because the local home route has a pre-existing hydration error (`web/lib/summary.ts`), out of scope for #443.
- AC4 note (D3): the LiDAR ground p50 chart has no registry-defined threshold; its caption
  reads `no pass bar defined` and the briefing card reads `no bar`. The other two charts
  draw their pass bars.
- Numbers only; no imagery.
