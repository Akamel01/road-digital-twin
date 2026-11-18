# #288 measurement — needs human

## Status
AC1 is **not** claimed. AC2 is **not** claimed.

## What is committed
- `scripts/mosaic_fixture.py` — measurement fixture (composites per-drive tiles into per-layer mosaics).
- `web/scripts/measure-288.mjs` — harness scaffold (Chromium resolution, mirror, fixture build, serve, build). The CDP orchestration (screenshots, orbit, frame-time/heap measurement, gate) is **not implemented**; the script exits non-zero without a real measurement.
- `web/eslint.config.mjs` — ignores `scripts/**`.

## Blocker
The measurement harness requires a full CDP-based browser driver (screenshots, rAF sampling, heap profiling, orbit gesture, tile-settle detection) which was not implemented in this run. No measured before/after pairs exist; no numbers were invented.

## Measured pairs
None. (No `metrics.json` produced.)

## Reproduction
1. `npx playwright install chromium` (or set `CHROME_BIN`).
2. Implement the CDP section of `web/scripts/measure-288.mjs` per `.autoforge/plans/plan.md` §5 M7.
3. `node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`.
