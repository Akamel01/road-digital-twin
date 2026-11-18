# #288 measurement: needs human review (gate failed)

Gate failed on real measured run (no fabricated numbers).

## Failing pairs / conditions
- frame p95 (ms): 400 (before) -> 983.3 (after), samples 460/318 (>=100) — not improved.

## Passing checks in same run
- no `getLineDashArray` in after page errors (`page_errors.after_non_404` empty)
- 404 classification: unexpected tile 404s = 0; known app 404s = 5 after (`/showcase/status.json`, `/favicon.ico`, `/dev`, `/latest`) classified and not failed on
- drag_delta changed: before=true after=true (canvas/pan screenshot fingerprint changed during wheel gesture on both sides)
- frame-time window started before 20 zoom-in clicks and covered 10 s wheel pan (40 steps every 250 ms)
- renderer match (SwiftShader), final scale "5 m" both sides, tile_zoom_match ok
- whole image count: 258 -> 54 (>0 both sides)
- gesture window image count: 50 -> 34 (>0 both sides)
- 7 AFTER-only PNGs with sha256+variance in `docs/evidence/288/README.md`

Source of truth: `docs/evidence/288/metrics.json`, `docs/evidence/288/README.md`, `docs/evidence/288/summary.md`.
Log: `/tmp/288-measure.log` (includes earlier after-attempt-0 page-closed retry; final GATE false only for frame p95).
