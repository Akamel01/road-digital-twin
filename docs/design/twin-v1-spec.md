# Twin v1 design spec

Status: draft for review, 2026-11-07. Due date: 2026-11-12.
This spec is the one current statement of v1, and it replaces the v1 items in the decision records ([0001](../decisions/0001-scope-and-order.md), [0002](../decisions/0002-digital-twin.md), [0003](../decisions/0003-risk-engine.md)). Those records stay as history. The review that led to this spec is in [docs/reviews/2026-11-07-decisions](../reviews/2026-11-07-decisions/consolidated_review_report.md). The sources are in [related work](../research/related-work.md).

## 1. Problem

A road safety audit is run by a qualified auditor who inspects the road, often in person, and works through a checklist. This takes too long to do on every facility in a network. Agencies therefore audit a small sample, chosen by screening steps. Locations that the screening misses are never audited.

A measurable 3D model of the road (a "twin") could let much of the checking happen at a desk, on every facility. For that to be trusted, the twin has to give measurements with stated error, not just pictures.

The literature search found sight-distance work on lidar point clouds (for example [kilani-2021-urban-isd], [gonzalez-gomez-2019-sight-distance]). It found no source that combines a 3D road twin with a formal audit (related work, section 7).

v1 is one step toward that goal. Its purpose is narrower: **show recruiters for AV safety roles a working, honest pipeline that turns AV sensor logs into measured road geometry, with its error stated.** It must also give the operator a control panel to tune and evaluate that pipeline.

## 2. Goals and non-goals

### Goals (v1, 2026-11-12)

1. **One nuScenes scene, rebuilt as a measurable twin.** The scene comes from nuScenes mini, which is CC BY-NC-SA 4.0. The twin has:
   - a georeferenced ground and non-ground point cloud;
   - 3D lane markings and crosswalks extracted from the lidar;
   - curb lines detected from height steps.
2. **A vertical profile** along one approach to an intersection, reported as descriptive (see section 6, risk R1).
3. **Intersection sight distance (ISD)** at that intersection, checked against a named method with editable parameters. Where the scan can't decide, the result is "indeterminate".
4. **Accuracy in plan view.** The extracted markings, crosswalks and curb lines are compared with the nuScenes HD map. The result is reported as P50 and P95 distance error in metres, with the reference named for each element.
5. **Drawings:** a plan sheet and a profile sheet, in both DXF and PDF.
6. **A web UI** at `twin.papyrus-ai.net`:
   - public views: plan, profile, ISD, accuracy, downloads;
   - a developer panel that anyone can view, but only the operator can use. The operator can edit parameters, edit the pipeline (enable, disable or reorder stages, and pick each stage's method), run or re-run, and compare two runs.
7. **Every run is kept and reproducible.** The parameters, pipeline definition, code version, input data version and outputs are stored together.

**Priority rule (operator, 2026-11-07):** when time runs short, the controls win over polish. The developer panel's control features are cut last.

### Non-goals (v1)

- AuditorAI integration. The output files and manifest are the implicit contract for later; there is no frozen schema.
- Gaussian splatting or any learned reconstruction; an interactive 3D viewer.
- Cameras-only reconstruction (v1.1), Vancouver lidar-only (v1.1), drone (v2).
- Signs, signals, poles, crest-curve stopping sight distance.
- A claim about vertical accuracy (no independent height reference exists for nuScenes; R1).
- The risk engine (decision 0003 is direction only).

## 3. Proposed architecture

```
nuScenes mini (box: /data/nuscenes)
      │
      ▼
[1 load]      scene sweeps, 2D poses, 3D boxes, HD map, map origin
      ▼
[2 align]     ICP refines each sweep's pose to 6 DoF (fixes z, pitch, roll)
      ▼
[3 aggregate] mask annotated road users, stack sweeps, voxel-downsample
      ▼
[4 ground]    split ground and non-ground; fit ground surface
      ▼
[5 features]  lane markings + crosswalks (intensity on ground points),
              curbs (height step at ground edge) → 3D polylines
      ▼
[6 profile]   ground z along the approach centreline → profile
[7 isd]       sight-line rays over non-ground points → ISD per leg
      ▼
[8 accuracy]  features vs HD map → P50/P95 per element
      ▼
[9 outputs]   LAZ, GeoJSON (3D), DXF, PDF, manifest.json
      ▼
run store (box: /data/twin-runs/<run-id>/)  ──►  control API (FastAPI, box)
                                                  │  Cloudflare Tunnel
                                                  ▼
                                    UI (static Next.js, Cloudflare Pages)
```

**Pipeline definition.** The pipeline is a YAML file listing the stages in order. Each entry names its method and parameters. Every stage is a Python function that reads the previous stage's files and writes its own. The developer panel edits this file and the parameters. It can't upload code, so changing a method means choosing among methods already registered for that stage (for example, ground: `ransac-tiles` or `csf`).

**Run store.** Each run lives in its own folder holding:
- `pipeline.yaml` and `params.yaml`;
- `manifest.json`, recording the git SHA, data version, EPSG, units, licence, timings and per-stage status;
- one sub-folder per stage.

Runs are never overwritten. A re-run from stage *k* copies stages 1 to *k−1* from the parent run.

**Control API.** FastAPI on the box:
- one worker process, one run at a time, queued by a file lock;
- `GET` routes are public: runs, a run, its files, and a compare view;
- `POST` routes need a Papyrus account token with the admin role: create a run, re-run from a stage, save the pipeline and parameters, cancel;
- parameters are validated against a schema, there is no shell access, and requests are rate-limited.

**Georeference.** The nuScenes map frame is local. The map origin's latitude and longitude for each location (as in nuscenes-devkit `export_poses.py`) are used to convert to UTM, EPSG:32619 for Boston. The EPSG code is written into every output.

**UI.** Next.js static export, using the Mission Control style (design tokens copied from drone-survey `web/`, with a provenance note).
- **Plan view:** a raster top-down render of the point cloud as map tiles, with vector overlays.
- **Profile view:** a chart.
- **Data loading:** it reads run files through the API.
- **Developer panel:** it shows read-only controls when signed out and live controls for the admin.

**Data licence.**
- Code: Apache-2.0.
- Derived outputs (point clouds, drawings, GeoJSON): CC BY-NC-SA 4.0, inherited from nuScenes. They are never committed to git. The manifest and the UI footer state this.
- The site is labelled "non-commercial research demo", with no paid features near it.

## 4. Alternatives considered

| Option | Rejected for v1 because |
|---|---|
| Gaussian splatting (DrivingGaussian, Street Gaussians, gsplat) | It isn't a measurement. The strongest-fit repos have no licence or a registration licence (related work, section 1). It needs GPU time the box shares with ollama. |
| Stacking sweeps on the dataset poses alone | nuScenes poses are 2D plus heading, with z always 0 ([nuscenes-devkit#721](https://github.com/nutonomy/nuscenes-devkit/issues/721)). Stacked clouds would come out flat, and the profile would be wrong. ICP refinement is added. |
| Learned vector mapper (MapTR, MIT licence) | It predicts 2D map elements from cameras, and no paper reports height error (related work, section 5). Classic lidar extraction is simpler to explain and to check. |
| Draping HD-map polygons onto the ground as the features | The accuracy check would then compare the map with itself. The map is used only as the reference. |
| Crest-curve stopping sight distance | The nuScenes scenes are mostly flat urban roads, and there is no independent height reference. ISD at an intersection uses mostly plan geometry. |
| Fully static site | The operator wants live controls (decision 22). |
| Potree / COPC 3D streaming viewer | A 3D viewer isn't a v1 goal. Raster tiles stay within the Cloudflare per-file limit. |
| Lyft Level 5 as the v1 source | Not checked: whether Lyft poses are 6 DoF. It stays in the pool for v1.1. |

## 5. Methods and parameters (operator-directed)

- **ICP:** point-to-plane alignment of each sweep to a local map built from the earlier sweeps, as in KISS-ICP (MIT). Report the mean residual and the ratio of final to initial z drift.
- **Ground:** RANSAC plane per 5 m tile (the default) or a cloth-simulation filter. Report the ground-fit RMSE.
- **Lane markings and crosswalks:** threshold the intensity of ground points (a percentile per tile), cluster, then fit polylines. Crosswalks are clustered stripes, reported as polygons. This follows the classic MLS approach ([guan-2014-road-markings-mls]).
- **Curbs:** a height step of 0.08–0.25 m between the road surface and the adjoining surface, within 1 m of the drivable-area edge, chained into polylines.
- **ISD:** AASHTO case B (stop control), with eye height 1.08 m and object height 1.08 m and the design speed as a parameter. TAC presets are available too. Rays run from the driver's eye to the object along each leg. Any non-ground point inside the sight triangle above the line of sight blocks it. The result is computed twice, with and without the masked parked vehicles. A leg whose ray leaves the scan's coverage is reported as "indeterminate".
- **Accuracy:** each extracted element is compared with its HD-map reference:
  - lane markings with `lane_divider` and `road_divider`;
  - crosswalks with `ped_crossing`;
  - curbs with the `drivable_area` boundary, which is a proxy.

  Report the P50 and P95 plan distance in metres, and the share of the reference length covered. No pass/fail threshold is set in v1. The 20 cm target becomes a figure to report, not a gate.

## 6. Risks and limits

| # | Risk | Mitigation |
|---|---|---|
| R1 | Height is unvalidated: no independent z reference exists for nuScenes. | The profile is labelled descriptive. Report ICP z-drift and ground RMSE. Vancouver ALS (0.081 m vertical at 95%) validates height in v1.1, on Vancouver data. |
| R2 | ICP drift or failure on a 20 s scene. | Use a short window (<20 s, which Motional's maintainer says aggregates well). Fall back to the dataset poses, with a warning in the manifest. |
| R3 | No usable intersection in nuScenes mini. | Stage 0 lists the mini scenes with an intersection (`road_segment.is_intersection`) and their coverage. The operator picks one before the build. |
| R4 | The extracted markings are noisy, so the accuracy figures look poor. | Report them honestly, with per-element coverage. The point of the demo is the stated error, not a perfect number. |
| R5 | 5 days is short. | Parallel tickets. Cut order, if late: curbs, then DXF (PDF stays), then compare-runs. Controls are cut last (priority rule). |
| R6 | A public API that triggers work on a shared production box. | Admin-only POST routes, one run at a time, a CPU cap on the container, no shell, schema-checked parameters, rate limiting. Disk is checked before each run, and the run is held below 10 GB free. |
| R7 | nuScenes non-commercial terms on a company domain. | "Non-commercial research demo" label, attribution, no paid features. Optionally confirm with Motional. |
| R8 | opencode models are down. | Haiku subagents do the work, with Claude reviewing (temporary). |

## 7. Acceptance criteria

- A run on the chosen scene finishes on the box CPU in under 30 minutes and writes every output listed in section 3.
- The manifest records the git SHA, data version, EPSG 32619, units (m), licence, parameters, per-stage timings and status.
- The plan sheet opens in a DXF viewer (`ezdxf` audit passes) and as a PDF, with a scale bar, north arrow, source line and licence line.
- The accuracy panel shows P50 and P95 per element type, plus coverage, and names each reference layer.
- ISD shows the available sight distance per leg against the required distance, or "indeterminate", with and without parked vehicles.
- Signed out, the developer panel is visible but its controls are disabled. Signed in as admin, the operator can change one parameter, re-run from that stage, and see the comparison with the parent run.
- The UI works at 375 px and 1280 px widths and passes a screenshot self-review at both widths.

## Detailed Implementation Plan

Tickets marked [operator] are methodology the operator reviews line by line; [scaffold] tickets are built by agents. Dependencies are listed as "after". T2, T3 and T9 can run in parallel.

- **T1 [scaffold]: package and CI.**
  - `twin/` package with a `pyproject.toml`; Python 3.11; dependencies: numpy, open3d (MIT), kiss-icp (MIT), laspy, pyproj, shapely, ezdxf, matplotlib, nuscenes-devkit (Apache-2.0), fastapi;
  - pytest and ruff in GitHub Actions;
  - a fixture made from a few sweeps of one mini scene, downloaded in CI and not committed.
- **T2 [scaffold]: data.**
  - `scripts/get_nuscenes_mini.sh` downloads to `/data/nuscenes` on the box, plus the map expansion;
  - stage 0, `twin list-scenes`, lists mini scenes with an intersection and their lidar coverage, as a table for the operator to choose from.
  - After T1.
- **T3 [scaffold]: run store and pipeline runner.**
  - YAML pipeline, stage registry, run folders, manifest, re-run from stage *k*, file-lock queue, CLI `twin run`.
  - After T1.
- **T4 [operator]: align and aggregate** (stages 1–3). After T2, T3.
- **T5 [operator]: ground and features** (stages 4–5). After T4.
- **T6 [operator]: profile and ISD** (stages 6–7). After T5.
- **T7 [operator]: accuracy** (stage 8). After T5.
- **T8 [scaffold]: outputs** (stage 9): LAZ, GeoJSON, DXF and PDF sheets, top-down raster tiles. After T5; profile sheet after T6.
- **T9 [scaffold]: control API**: routes from section 3, Papyrus admin-token check, schema validation, compare endpoint, Cloudflare Tunnel config (operator approves the DNS record). After T3.
- **T10 [scaffold]: UI** in the Mission Control style: public views and the developer panel (parameter editor, pipeline editor, run, re-run, compare). Brief follows the briefing lessons: intent per view, reference skeleton (drone-survey `web/`), banned patterns, screenshot self-review. After T9; uses fixture run files until T8 lands.
- **T11 [scaffold]: deploy**: Pages project, tunnel, API container with a CPU cap, smoke test of the acceptance criteria. After T8–T10.

**Order to 2026-11-12:**
- Day 1: T1–T3, plus scene choice.
- Day 2: T4 and T9.
- Day 3: T5 and T10.
- Day 4: T6–T8.
- Day 5: T11, then fixes.
