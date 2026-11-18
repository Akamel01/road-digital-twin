# #288 measurement: needs human review (gate failed)

Gate failed on real measured run (no fabricated numbers).

## Failing pairs / conditions
- frame p95 (ms): 499.9 (before) -> 500 (after) — not improved.
- after page errors include: `deck: \`getLineDashArray\` has been removed. Use \`PathStyleExtension\` instead`
- unexpected HTTP 404s (after): `http://127.0.0.1:36077/showcase/status.json`, `http://127.0.0.1:36077/favicon.ico`, `http://127.0.0.1:36077/showcase/status.json`, `http://127.0.0.1:36077/dev`, `http://127.0.0.1:36077/latest`

Passing checks in same run: renderer match (SwiftShader), final scale match ("5 m"), whole 325->24 (>0), gesture 117->12 (>0), samples 156/144 (>=100), tile_zoom_match ok, 7 AFTER-only PNGs with sha256+variance present.

Source of truth: `docs/evidence/288/metrics.json`, `docs/evidence/288/README.md`.

## Log tail (`/tmp/288-measure.log`)
```
Chromium: /home/oc/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
reusing mirror: /tmp/288-mirror
fixture written to /tmp/288-fixture (15 drives, extent 555.2m)
reusing before build: /tmp/288-before-1d3951c7fbaba434250e8432aeb9acfa165ca5e9
...
○  (Static)  prerendered as static content

ports 39793 41151
page.screenshot: Target page, context or browser has been closed
    at main (/home/oc/.opencode-runs/Akamel01-road-digital-twin/288/worktree/web/scripts/measure-288.mjs:662:19)
GATE false [
  'frame p95 not improved: 499.9 -> 500',
  'after has deck/TypeError/Error entries: deck: `getLineDashArray` has been removed. Use `PathStyleExtension` instead',
  'unexpected 404s: http://127.0.0.1:36077/showcase/status.json | http://127.0.0.1:36077/favicon.ico | http://127.0.0.1:36077/showcase/status.json | http://127.0.0.1:36077/dev | http://127.0.0.1:36077/latest'
]
```

Note: screenshot capture hit a closed-page error near end of run, but 7 after PNGs were written and recorded in metrics (see timestamps/metrics.screenshots).
