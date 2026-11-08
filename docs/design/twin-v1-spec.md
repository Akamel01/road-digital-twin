# Twin v1 design spec

Status: revision 2, 2026-11-07, after the EGM review of revision 1. Due date: 2026-11-12.

This spec is the one current statement of v1. It replaces the v1 items in the decision records ([0001](../decisions/0001-scope-and-order.md), [0002](../decisions/0002-digital-twin.md), [0003](../decisions/0003-risk-engine.md)), which stay as history. Supporting documents:
- [consolidated review of the decisions](../reviews/2026-11-07-decisions/consolidated_review_report.md);
- [review of revision 1 of this spec](../reviews/2026-11-07-spec/intermediate_zoom_out_report.md);
- [related work](../research/related-work.md).

Citation keys such as `[kilani-2021-urban-isd]` are entries in [sources.yaml](../research/sources.yaml).

**Terms.**
- **Operator:** Ahmed Kamel, the project owner. He sets the methodology and is the only admin.
- **The box:** the operator's Linux workstation, which also hosts Papyrus production services. It has 28 CPU cores, an RTX 4070 SUPER with 12 GB (partly used by ollama), and, on 2026-11-07, 35 GB of free disk; a new SSD is pending.
- **Mission Control:** the operator's drone-survey product (`Akamel01/drone-survey`). Its `web/` app sets the visual style.

## 1. Problem

A road safety audit is done by a qualified auditor who inspects the road, often in person, against a checklist. Because each audit takes so long, agencies audit a selection of facilities chosen by screening, not every facility. A measurable 3D model of the road (a "twin") could move the geometry and sight-distance checks to a desk. Those are the checks v1 targets, and they would then be possible on every facility. To be trusted, the twin has to give measurements with stated error, not just pictures.

Sight-distance work on lidar point clouds exists (for example [kilani-2021-urban-isd], [gonzalez-gomez-2019-sight-distance]). The related-work search found no source that combines a 3D road twin with a formal audit (related work, section 7).

v1's purpose is narrower: **show recruiters for AV safety roles a working pipeline that turns AV sensor logs into measured road geometry, with stated error.** It also gives the operator a control panel to tune and evaluate that pipeline.

Success signal: a reviewer can trace one reported number, such as a crosswalk's P95 error, back through the run's parameters and stage outputs to the raw sweeps, all from the UI.

## 2. Goals and non-goals

### Goals (v1, 2026-11-12)

1. **One nuScenes mini scene in Boston, rebuilt as a measurable twin.** nuScenes mini is CC BY-NC-SA 4.0. The twin includes:
   - a georeferenced point cloud, split into ground and non-ground;
   - 3D lane markings and crosswalks extracted from the lidar;
   - curb lines found from height steps.
2. **A vertical profile** along one approach to an intersection. It is descriptive (R1) and flagged invalid when the pose quality check fails.
3. **Intersection sight distance (ISD)** at that intersection, using a named method with editable parameters. Each leg reports "indeterminate" when it lacks scan coverage or valid height.
4. **Plan-view accuracy** of the extracted markings, crosswalks and curbs against the nuScenes HD map. Reported as P50 and P95 distance in metres, plus coverage. Each element names its reference, and curbs are labelled "map-conditioned".
5. **Drawings:** a plan sheet and a profile sheet, each in DXF and PDF.
6. **A web UI** at `twin.papyrus-ai.net`:
   - **Public views:** a pinned showcase run with plan, profile, ISD, accuracy and downloads.
   - **Developer panel:** anyone can view it, but only the operator can act. The operator can:
     - choose each stage's method from the registered set;
     - edit every parameter;
     - switch optional stages on or off;
     - run, or re-run from a stage;
     - compare two runs.
   - Stage order is fixed (decision 23, revised 2026-11-07).
7. **Every run is kept and can be re-run.** Its parameters, method choices, code version, lockfile hash, seeds and outputs are stored together.

**Priority rule (operator, 2026-11-07):** controls are cut last. Three items are never cut, because they keep the stated error honest:
- the `height_valid` flag;
- ISD "indeterminate";
- the curb "map-conditioned" label.

### Non-goals (v1)

- AuditorAI integration. Later integration will read the output files and manifest; v1 doesn't freeze their schema.
- Gaussian splatting or any learned reconstruction; an interactive 3D viewer.
- Cameras-only (v1.1), Vancouver lidar-only (v1.1), drone (v2), Singapore scenes.
- Signs, signals, poles, sidewalks, cross-section drawings, crest-curve stopping sight distance.
- Any claim about vertical or absolute georeference accuracy (R1).
- Free reordering of stages; 3D occupancy ray-casting for ISD (v1.1).
- The risk engine (decision record 0003 sets direction only).

## 3. Proposed architecture

```text
[0 select]    (setup, not a pipeline stage) list Boston mini scenes with an intersection;
              ground density + paint contrast go/no-go; operator picks one
nuScenes mini (box: /data/nuscenes)
      ▼
[1 load]      sweeps, 2D poses, 3D boxes (+ vehicle.parked attribute), HD map
      ▼
[2 mask]      remove points inside annotated boxes → masked cloud; keep removed
              parked-vehicle points as their own artifact
      ▼
[3 align]     ICP on masked sweeps → relative 6-DoF refinement (z, pitch, roll consistent)
      ▼
[4 ground]    aggregate, voxel-downsample, split ground / non-ground, fit surface;
              QA: ground-z disagreement where sweeps overlap → height_valid flag
      ▼
[5 features]  markings + crosswalks (intensity), curbs (height step, optional) → 3D polylines
      ▼
[6 profile]   (optional) ground z along approach centreline
[7 isd]       (optional) sight lines per leg, with and without parked vehicles
[8 accuracy]  (optional) features vs HD map → P50/P95 + coverage
      ▼
[9 outputs]   LAZ, GeoJSON (3D), DXF, PDF, manifest.json
      ▼
run store (box: /data/twin-runs/<run-id>/) ──► control API (FastAPI, box) ◄── developer panel
                │                                 Cloudflare Tunnel + Access
                └── twin publish <run-id> ──► static showcase files ──► public views (Pages)
```

**Pipeline definition.**
- Stages run in the fixed order shown. Each stage has a registry of methods and a static `requires` list.
- Optional stages are profile, ISD and accuracy, plus curbs within features.
- The runner rejects a run in which an enabled stage needs a disabled one.
- The panel cannot upload code. It only chooses among registered methods; for example, ground can be `ransac-tiles` or `csf`.

**Run store.**
- Each run is one folder holding `pipeline.yaml`, `params.yaml`, `manifest.json` and one sub-folder per stage.
- The manifest records:
  - git SHA, a dirty-tree flag and the lockfile hash;
  - seeds (numpy and Open3D);
  - the data version (`v1.0-mini` plus map expansion v1.3);
  - EPSG, units and licence;
  - timings, stage status and `height_valid`.
- Runs are never overwritten.
- Re-running from stage *k* hard-links stages 1 to *k−1* from the parent run.
- Compare covers parameters and metrics.

**Control API.** FastAPI on the box, reached through a Cloudflare Tunnel.
- **Access:** all write routes, and the live developer panel, sit behind Cloudflare Access, restricted to the operator's Google account. CORS allows only `twin.papyrus-ai.net`, with credentials.
- **Runs:** one run at a time, queued with a lock file. A stale lock is cleared when its process ID is gone. Cancel stops the run between stages.
- **Inputs:** parameters are checked against a schema and loaded with `yaml.safe_load`.
- **File routes:** reject `..` and absolute paths.
- **Shell:** there is no shell access.

**Static showcase.**
- `twin publish <run-id>` copies one chosen run's public outputs into the Pages build: plan raster, GeoJSON, a downsampled LAZ, PDFs, DXFs and manifest.
- Every file stays under the Pages per-file limit (25 MiB).
- Public views read only these files, so the demo stays up when the box is busy or down.

**Georeference.**
- The Boston map origin's latitude and longitude, as in nuscenes-devkit `export_poses.py`, convert map coordinates to UTM zone 19N (EPSG:32619).
- The origin is approximate, so the absolute georeference error is unknown. It is separate from the plan accuracy against the HD map, which shares the same frame.

**UI.**
- Next.js static export in the Mission Control style. The design tokens are copied from drone-survey `web/`, with a note of where they came from.
- **Plan:** one top-down raster image under the file limit, with vector overlays.
- **Profile:** a chart.

**Data licence.**
- The code is Apache-2.0.
- Derived outputs carry CC BY-NC-SA 4.0 from nuScenes and are never committed to git. The manifest and the footer say so.
- The site is labelled "non-commercial research demo".

## 4. Alternatives considered

| Option | Rejected for v1 because |
|---|---|
| Gaussian splatting (DrivingGaussian, Street Gaussians, gsplat) | Doesn't measure geometry. The best-fit repos have no licence or a registration licence (related work, section 1). Needs GPU time shared with ollama. |
| Stacking sweeps on the dataset poses | nuScenes poses are 2D plus yaw, with z always 0 ([nuscenes-devkit#721](https://github.com/nutonomy/nuscenes-devkit/issues/721)). The stack would come out flat. |
| Pose from a per-sweep ground-plane fit, or a pose graph | Ground-plane fits bias z on cambered or sloped roads, and a pose graph is more work than one short scene needs. KISS-ICP is an existing, MIT-licensed package. |
| Learned vector mapper (MapTR, MIT) | Predicts 2D map elements from cameras, and no paper reports height error (related work, section 5). Classic extraction outputs polylines straight from measured points, so every vertex traces back to lidar returns. |
| Draping HD-map polygons onto the ground | The accuracy check would then compare the map with itself. |
| Symmetric Chamfer distance for accuracy | Penalises reference length that the scan never covered. A one-way distance from extracted to reference, plus a separate coverage figure, keeps the two apart. |
| Crest-curve stopping sight distance | Needs a valid vertical profile, which v1 can't validate (R1). ISD at an intersection depends mainly on plan geometry. |
| Fully static site | A static site can't run, re-run or compare runs. The operator needs those (goal 6). |
| Custom auth (Papyrus token check, rate limiter) | Cloudflare Access gives Google sign-in and blocks unauthenticated requests at the edge, with no code to maintain. |
| A tracking tool for runs (MLflow) | A heavy service for one scene and one user. A folder per run plus a manifest covers v1. |
| Potree / COPC 3D streaming viewer | A 3D viewer isn't a v1 goal. |
| Lyft Level 5 as the v1 source | Its pose degrees of freedom are unconfirmed, and switching costs a day the schedule doesn't have. It stays in the pool for v1.1. |

## 5. Methods and parameters (operator-directed)

- **Select (setup):** for each candidate scene, measure:
  - ground points per m² on the road;
  - the intensity contrast between the top 5% and the median of road points.

  Go/no-go thresholds are parameters. On no-go for markings, the run reports markings as "not extractable at this density", and the accuracy stage covers crosswalks and curbs only.
- **Mask:** remove points inside annotated boxes, placed with the 2D poses. Boxes with the `vehicle.parked` attribute go to a separate parked-vehicle artifact.
- **Align:** the KISS-ICP pipeline on masked sweeps, over a window of up to the full scene (about 20 s; default 20 s). This makes z, pitch and roll consistent *between* sweeps. It doesn't recover absolute height. If ICP fails, fall back to the dataset poses and set `height_valid=false`.
- **Ground:** RANSAC plane per 5 m tile (default) or a cloth-simulation filter (CSF; check its licence when it is added).
  - Report the ground-fit RMSE.
  - QA: P95 of the ground-z disagreement between points from different sweeps in the same 0.5 m cell.
  - If that P95 is above the threshold (default 0.10 m), `height_valid=false`.
- **Markings and crosswalks:** threshold the intensity of ground points (percentile per tile), cluster, then fit polylines. Crosswalks are clustered stripes, reported as polygons. This is the classic mobile-mapping approach ([guan-2014-road-markings-mls]). Its feasibility at 32-beam density is unproven; the select step tests it.
- **Curbs (optional):** a height step of 0.08–0.25 m at the edge of the fitted ground surface, chained into polylines. The search window is the ground edge. Because of how curbs are scored, curb accuracy is still labelled "map-conditioned" (see Accuracy).
- **ISD:**
  - Method: AASHTO case B (stop control). Driver eye height 1.08 m, object height 1.08 m, design speed as a parameter. The alternative preset is the Transportation Association of Canada (TAC) guide (eye height 1.05 m, object height 1.30 m).
  - For each leg, a sight line runs from the eye point to the object point.
  - A point blocks the line if it is above the ground surface, below the line, and within 0.3 m of it horizontally.
  - The leg is "indeterminate" if any 2 m stretch of the line has fewer ground points than a coverage threshold, or if `height_valid=false`.
  - It is computed twice: without and with the parked-vehicle artifact.
- **Accuracy:** one-way distance from each extracted vertex to its reference. The references are:
  - lane markings: `lane_divider` and `road_divider` (map polylines, not painted edges);
  - crosswalks: `ped_crossing`;
  - curbs: the `drivable_area` boundary. This is a proxy, so curb accuracy is labelled "map-conditioned".

  Report:
  - P50 and P95 in metres;
  - coverage: the share of reference length within a 1.0 m matching buffer of an extracted element.

  No pass/fail threshold is set in v1.

## 6. Risks and limits

| # | Risk or limit | Mitigation |
|---|---|---|
| R1 | No independent height reference exists for nuScenes, and the absolute georeference error is unknown. | The profile is descriptive. Height-dependent outputs follow `height_valid`. A Vancouver ALS height check comes in v1.1, where the City of Vancouver LiDAR 2022 states 0.081 m vertical accuracy at 95% (opendata.vancouver.ca, `lidar-2022`). |
| R2 | ICP drifts or fails. | Mask moving objects first, check the ground-z disagreement, fall back to dataset poses with `height_valid=false`, and show "indeterminate (pose)" in the UI. |
| R3 | Boston mini has no intersection with dense enough lidar. | The select step decides on day 1, with the no-go branch defined in section 5. |
| R4 | Extracted markings are noisy. | Report P50 and P95 with coverage, as measured. |
| R5 | 5 days is short. | Cut order if late: (1) curbs, (2) DXF (PDF stays), (3) the profile sheet. Never cut: the three honesty items and the controls. |
| R6 | The API runs on a shared production machine. | Cloudflare Access, one run at a time, a CPU cap on the container, no shell, schema-checked parameters. A run does not start if free disk is below 10 GB. Public views never touch the box. |
| R7 | nuScenes is non-commercial and the site is on a company domain. | "Non-commercial research demo" label, attribution, and no paid features on the site. |
| R8 | Scale. v1 handles one scene, one run at a time, on one shared machine, and the run store grows without limit. | These limits are accepted for v1, and the free-disk check above guards the machine. Scaling to a network (a batch queue, retention, more workers) is out of scope until after v1.1. |

## 7. Acceptance criteria

- **Select step:** `twin select` lists the Boston mini scenes with an intersection, their density and contrast, and a go/no-go for each.
- **Run:** a run on the chosen scene finishes on the box CPU in under 30 minutes and writes every output listed in section 3. The time is estimated from the T1 fixture and confirmed in T4.
- **Manifest:** contains the SHA, the dirty-tree flag, the lockfile hash, seeds, data version, EPSG 32619, units (m), licence, method choices, parameters, per-stage timings and status, and `height_valid`.
- **Repeatability:** running the same parameters twice gives P50 and P95 within 0.02 m of each other.
- **Drawings:** the plan and profile sheets pass `ezdxf` audit and open as PDFs. Each has a scale bar, north arrow (plan only), source line and licence line.
- **Profile:** shows ground z against distance along the approach. It is labelled descriptive, and shows "indeterminate (pose)" when `height_valid=false`.
- **Accuracy panel:** shows P50, P95 and coverage per element, names each reference layer, and labels curbs "map-conditioned".
- **ISD:**
  - each leg shows the available and required distance, or "indeterminate";
  - shown with and without parked vehicles;
  - a fixture test confirms that a canopy point above the sight line doesn't block it.
- **Security:**
  - a POST without Access credentials gets 401 or 403;
  - a file route rejects `..`;
  - a pipeline with a disabled required stage is rejected.
- **Controls:**
  - signed out, the developer panel is visible with its controls disabled;
  - signed in, the operator can change one parameter, re-run from that stage, and see the comparison with the parent run.
- **Public views:**
  - they load from the static files with the box unreachable;
  - at 375 px and 1280 px widths there is no horizontal scroll, every view can be reached, and no control is clipped;
  - the footer shows the licence and the "non-commercial research demo" label.

## Detailed Implementation Plan

[operator] tickets are methodology the operator reviews line by line. [scaffold] tickets are built by agents.

Dependencies:
- T1 first.
- T2 and T3 in parallel after T1.
- T9 after T3.
- T4 after T2 and T3.
- T5 after T4, then T6 and T7 after T5.
- T8 after T5 (its profile sheet after T6).
- T10 after T9.
- T11 last.

- **T1 [scaffold]: package and CI.**
  - `twin/` package with `pyproject.toml` and `uv.lock`, on Python 3.11.
  - Dependencies: numpy, open3d (MIT), kiss-icp (MIT), laspy, pyproj, shapely, ezdxf, matplotlib, nuscenes-devkit (Apache-2.0), fastapi.
  - pytest and ruff in GitHub Actions.
  - A small fixture built from a few sweeps of one mini scene, downloaded in CI and not committed.
- **T2 [scaffold]: data and select.**
  - `scripts/get_nuscenes_mini.sh` downloads nuScenes mini and map expansion v1.3 to `/data/nuscenes` on the box.
  - `twin select` lists Boston intersection scenes with density, contrast and go/no-go.
  - The operator picks the scene.
- **T3 [scaffold]: runner and run store.**
  - Stage registry with method choices and `requires`.
  - Run folders, manifest, hard-link re-run, lock-file queue with stale-lock recovery, cancel between stages.
  - CLI: `twin run` and `twin publish`.
- **T4 [operator]: stages 1–3** (load, mask, align), with a runtime measurement.
- **T5 [operator]: stages 4–5** (ground with the QA check, features).
- **T6 [operator]: stages 6–7** (profile, ISD with the blocking band and coverage proxy).
- **T7 [operator]: stage 8** (accuracy).
- **T8 [scaffold]: stage 9** (outputs): LAZ, GeoJSON, DXF and PDF sheets, plan raster, downsampled showcase LAZ.
- **T9 [scaffold]: control API.**
  - The routes in section 3, with Access, CORS, schema validation, path checks and compare.
  - Cloudflare Tunnel and Access configuration. The operator approves the DNS record and Access policy.
- **T10 [scaffold]: UI.** Public views (static files) and the developer panel (live API). The brief includes:
  - the intent of each view;
  - drone-survey `web/` as the reference skeleton;
  - banned patterns;
  - a screenshot self-review against the public-view criteria in section 7.

  Until T8 lands, it uses fixture runs.
- **T11 [scaffold]: deploy.** Pages project, tunnel, API container with a CPU cap, `twin publish` of the showcase run, and a smoke test of section 7.

**Order to 2026-11-12:**

| Day | Work |
|---|---|
| 1 | T1, then T2 and T3; scene choice; Access decision |
| 2 | T4, T9 |
| 3 | T5, T10 |
| 4 | T6, T7, T8 |
| 5 | T11, fixes |
