# #443 evidence

- Route: `/evaluations` (static export, `web/out`)
- Build: `[ -d web/node_modules ] || npm --prefix web ci; npm --prefix web run build`
- Capture: `LD_LIBRARY_PATH=/tmp/evals-443/root/usr/lib/x86_64-linux-gnu:/tmp/evals-443/root/lib/x86_64-linux-gnu:/tmp/evals-443/root/usr/lib:/tmp/evals-443/root/lib HOME=/tmp/evals-443/home CHROME_BIN=/home/oc/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome node web/scripts/shoot-evals.mjs`
- Viewports: desktop 1440x900, phone 390x844, home-phone 390x844; deviceScaleFactor 1
- Browser: chromium /home/oc/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
- Desktop: desktop.png sha256=7e41d2d8ddf6563d43f7ef0ccd0248f5bc7babd7b501ef619f1eda6b5b651412
- Phone: phone.png sha256=6a3786cef4cecb8b57948c3dd9a152ac8aa8979c813c51fc13e3caca543409c1
- Home phone: home-phone.png sha256=8a5827dbc213a24a5a67dadce051d75451915462beccca82b1e23b9793cf955c
- Content: desktop.png and phone.png are full-page captures after overriding the page root
  (`#eval-page`; `.page` is CSS-module-hashed) and `html,body`: briefing header (pass
  bar, best run per headline metric, verdict), three trend charts (PSNR linear, road depth
  p95 log, LiDAR ground p50 log), comparison table, run list. phone.png also shows the
  header on one line with its single back link fully visible and no horizontal clipping. home-phone.png is the `/` page at
  390x844 showing the top bar with the Evaluations link fully visible, unclipped.
- AC4 note (D3): the LiDAR ground p50 chart has no registry-defined threshold; its caption
  reads `no pass bar defined` and the briefing card reads `no bar`. The other two charts
  draw their pass bars.
- Numbers only; no imagery.
