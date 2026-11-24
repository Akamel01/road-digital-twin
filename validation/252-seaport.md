# Seaport validation — issue #252

Study area: `seaport` (`AREA = "seaport"`). Runbook: execute on the box with Seaport data. Commands and metric list below.

## Prerequisites
- nuScenes `v1.0-trainval` data root (e.g. `/data/nuscenes/v1.0-trainval`).
- Run store (e.g. `/data/twin-runs`), with `areas/seaport.json` already defined.
- `TWIN_RUNS` / `--store` pointing at the store.

## Commands
```bash
# 1. Cross-drive registration (default chained-icp)
twin area merge seaport --store /data/twin-runs

# 1a. Preserve chained baseline before joint variant overwrites areas/seaport-merged
cp -a /data/twin-runs/areas/seaport-merged /data/twin-runs/areas/seaport-merged-baseline

# 1b. Joint pose-graph variant (M03/M04) — overwrites areas/seaport-merged
twin area merge seaport --store /data/twin-runs --method joint-pose-graph --heights

# 2. Area twin build (recon-core manifest) — assembles areas/seaport-twin
twin area build seaport --store /data/twin-runs

# 3. G2-only go/no-go (merged record carries align metrics only)
twin eval areas/seaport-merged --store /data/twin-runs

# 4. Accuracy stage (all + held-out) — written by area build into the twin run
#    all + held-out metrics: areas/seaport-twin/9_accuracy/accuracy.json
#    twin area build also writes areas/seaport-twin/gates.json / gates.md (includes G5)
twin eval areas/seaport-twin --store /data/twin-runs

# 5. G1 determinism rerun (must be identical) on the twin run
twin eval areas/seaport-twin --store /data/twin-runs --rerun areas/seaport-twin

# 6. Method-change comparison against preserved baseline dir
twin eval areas/seaport-twin --store /data/twin-runs --baseline /data/twin-runs/areas/seaport-merged-baseline
```

Notes:
- `areas/seaport-merged` contains align/merge outputs and metrics only; it has no `9_accuracy/` directory.
- `areas/seaport-twin` is the assembled twin run; accuracy artifacts and G5 gate results live there.
- Preserve the chained baseline directory before running the joint variant, since both merge methods write `areas/seaport-merged`.

## Metrics to record
- G2 cross-drive ground agreement (ground-class points only):
  - `align.cross_drive_ground_p95_m` (median over pairs) — gate ≤ 0.20 m (ratchet to 0.05 m)
  - `align.cross_drive_ground_p95_worst_m`
  - `align.cross_drive_ground_p95_registered_m`
  - `n_drives`, `n_skipped`, per-drive `layer_cells_dropped`
- Accuracy (G5), all and held-out (`*_all` keys alongside gated held-out):
  - `accuracy.elements.markings.matched_p95_m` (≤ 0.30 m), `.false_positive_rate` (≤ 0.10), `.coverage` (≥ 0.70)
  - `accuracy.elements.crosswalks.matched_p95_m` (≤ 0.50 m), `.false_positive_rate`, `.coverage`
  - `accuracy.elements.curbs.matched_p95_m` (≤ 0.50 m), `.false_positive_rate`, `.coverage`
- Alignment diagnostics (joint method): `method`, `convergence`, fallback (`fallback_reason`, `n_anchors`, `n_drives_with_overlap`, elapsed), `anchor_residuals`, `pair_residuals`
- Split counts: `n_total`, `n_anchor`, `n_heldout`, `counts_by_layer`
- Runtime: `runtime.total_min` (G6, ≤ 30 min)
- Determinism: `determinism.n_differing_metrics` (G1, ≤ 0)

