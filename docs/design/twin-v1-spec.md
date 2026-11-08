# Twin v1 design spec

Status: revision 4, 2026-11-08. Revision 3 followed the EGM implementation-readiness review; revision 4 adds the wayfinder decisions 34–41 (area scope, facilities, colour stage, UI layout, API host, tiled rasters). Due 2026-11-12.

This spec is the one current statement of v1. It replaces the v1 items in the decision records ([0001](../decisions/0001-scope-and-order.md), [0002](../decisions/0002-digital-twin.md), [0003](../decisions/0003-risk-engine.md)), which stay as history.

Reviews and research:
- [decisions review](../reviews/2026-11-07-decisions/consolidated_review_report.md)
- [spec review](../reviews/2026-11-07-spec/consolidated_review_report.md)
- [related work](../research/related-work.md)

Citation keys such as `[kilani-2021-urban-isd]` are entries in [sources.yaml](../research/sources.yaml).

**Terms**

- **Operator:** Ahmed Kamel, project owner. They set the methodology and are the only admin.
- **The box:** the operator's Linux workstation, which also hosts Papyrus production.
  - 28 CPU cores.
  - RTX 4070 SUPER with 12 GB, which ollama shares.
  - 35 GB free disk on 2026-11-07, with an SSD to be added.
- **Mission Control:** the operator's drone-survey product (`Akamel01/drone-survey`). Its `web/` app sets the visual style.
- **Keyframe:** a nuScenes sample at 2 Hz, with annotated boxes. **Sweep:** a lidar scan at about 20 Hz. Only keyframes have boxes.
- **Drive:** one nuScenes scene, about 20 s of driving. **Area:** all the Boston drives in nuScenes mini, shown together. **Facility:** an intersection, segment or access point, defined from the HD map (decision 40). Full glossary: [CONTEXT.md](../../CONTEXT.md).

## 1. Problem

A road safety audit is done by a qualified auditor who inspects the road, often in person, against a checklist. Each audit costs that time, so agencies audit selected facilities, chosen by screening, rather than all of them.

A measurable 3D model of the road (a "twin") could move the geometry and sight-distance checks to a desk, and make them possible on every facility. That only helps if the twin gives measurements with a stated error, not just pictures.

- Sight-distance work on lidar point clouds already exists ([kilani-2021-urban-isd], [gonzalez-gomez-2019-sight-distance]).
- The related-work search found no source that joins a 3D road twin to a formal audit (related work, section 7).

v1 has a narrower purpose: **show recruiters for AV safety roles a working pipeline that turns AV sensor logs into measured road geometry, with stated error.** It also gives the operator a control panel to tune and evaluate that pipeline.

The success signal: from the UI, a reviewer can trace one reported number back to the raw sweeps, through the run's parameters and stage outputs. An example is the P95 error for crosswalks.

## 2. Goals and non-goals

### Goals (v1, 2026-11-12)

1. **The Boston drives in nuScenes mini, each rebuilt as a measurable twin and shown together as one area** (decision 35). Each drive is a separate run; the area view places them in one frame (EPSG:32619). Merging overlapping drives into one cloud is v1.1 (#14). nuScenes mini is licensed CC BY-NC-SA 4.0. Each twin has:
   - a georeferenced point cloud, split into ground and non-ground;
   - 3D lane markings and crosswalks extracted from the lidar;
   - curb lines found from height steps.
1a. **Facilities** (decision 40): every intersection, segment and access point in the area, from the HD map, with a stable ID and an OpenStreetMap street name. A facility whose core is less than 50% observed is listed as "not scanned enough", with no metrics.
2. **Vertical profiles** along each intersection approach, each segment and each access point. They are descriptive only (R1), and flagged invalid when height quality fails.
3. **Sight distance in 3D**, using a named method with editable parameters: ISD per intersection leg (AASHTO Case B) and exit ISD left and right at each access point. A leg shows "indeterminate" when it lacks scan coverage or valid height.
4. **Plan-view accuracy** of the extracted markings, crosswalks and curbs against the nuScenes HD map. Each element reports P50 and P95 distance in metres, plus coverage, and names its reference layer. Curbs are labelled "map-conditioned".
5. **Drawings:** a plan sheet and a profile sheet, each in DXF and PDF.
5a. **True-colour 2D and 3D** (decision 32): a 5 cm orthoimage and RGB points from the six cameras, made by the optional `colour` stage (decisions 36 and 38). Ground no camera saw stays transparent, labelled "unobserved".
6. **A web UI** at `twin.papyrus-ai.net`, in two parts.
   - **Public views:** a pinned showcase (one run per drive), navigated area → facility → element, with plan, profile, ISD, accuracy and downloads. Layout: the approved mockup (decision 34).
   - **Developer panel:** anyone can view it; only the operator can act. The operator can:
     - choose each stage's method from the registered set;
     - edit every parameter;
     - switch optional stages on or off;
     - run, or re-run from any stage;
     - compare two runs.

   The stage order is fixed (decision 25).
7. **Every run is kept and can be re-run.** Its parameters, method choices, code version, lockfile hash, seeds and outputs are stored together.

**Priority rule (operator, 2026-11-07):** the controls are cut last. Three items are never cut, because they keep the stated error honest:
- the `height_valid` flag;
- ISD "indeterminate";
- the curb "map-conditioned" label.

### Non-goals (v1)

- **AuditorAI integration.** Later integration reads the output files and manifest. v1 doesn't freeze their schema for that use.
- **Other methods and views:** Gaussian splatting or any learned reconstruction; an interactive 3D viewer.
- **Other sources:** cameras-only and Vancouver lidar-only (both v1.1); drone (v2); Singapore scenes.
- **Other features:** signs, signals, poles, sidewalks, cross-section drawings, crest-curve stopping sight distance, twin-derived access points (v1.1).
- **Accuracy claims** about height or absolute georeferencing (R1).
- **Pipeline and ISD extensions:** free reordering of stages; 3D occupancy ray-casting for ISD (v1.1); a TAC ISD preset (v1.1, once its values are cited).
- **The risk engine.** Decision record 0003 sets its direction only.

## 3. Architecture

```text
[select]      setup, not a pipeline stage: list the Boston mini drives,
              road density + paint contrast go/no-go per drive; a run is one drive
nuScenes mini (box: /data/nuscenes)
      ▼
[1 load]      sweeps, 2D poses, keyframe boxes interpolated to each sweep, HD map layers,
              facilities from the map (+ OSM street names, cached)
      ▼
[2 mask]      remove points inside boxes → masked cloud; parked-vehicle points kept apart
      ▼
[3 align]     KISS-ICP on masked sweeps, anchored to dataset x/y/yaw → 6-DoF poses
      ▼
[4 ground]    aggregate, voxel-downsample, split ground / non-ground, grid surface;
              QA: ground-z disagreement between sweeps → height_valid
      ▼
[5 features]  markings + crosswalks (intensity); curbs (height step, optional)
      ▼
[6 colour]    (optional) camera colour: per-image depth buffer, median of best 5 views
              → orthoimage + RGB points
[7 profile]   (optional) ground z along each facility's centreline
[8 isd]       (optional) 3D sight lines per leg / exit, without and with parked vehicles
[9 accuracy]  (optional) features vs HD map → P50/P95 + coverage, per element and facility
      ▼
[10 outputs]  LAZ, GeoJSON (3D), DXF, PDF
      ▼
run store (box: /data/twin-runs/<run-id>/) ──► control API (twin-api.papyrus-ai.net, `twin` tunnel)
                │                                 write routes behind Cloudflare Access
                └── twin publish <run-id>… ──► static showcase files ──► public views (Pages)
```

**Pipeline.**
- Stages run in the order shown.
- Each stage has a registry of methods and a static `requires` list (section 4).
- Optional stages: colour, profile, ISD and accuracy. Curbs within features is also optional.
- The runner rejects a run where an enabled stage needs a disabled one.
- The panel only chooses among registered methods. It cannot upload code.

**Run store.**
- Each run is one folder holding `pipeline.yaml`, `params.yaml`, `manifest.json` and one folder per stage.
- Runs are never overwritten.
- A re-run from stage *k* hard-links the parent run's outputs for stages 1 to *k−1*.

**Control API.** FastAPI on the box at `twin-api.papyrus-ai.net`, reached through its own Cloudflare Tunnel named `twin` (Librarian's production tunnel is never touched). Zero Trust team `papyrus`, 24 h sessions; the panel has a sign-in button (decision 39).
- **Read routes (`/api/r/*`):** public. A signed-out viewer can see the live panel, the runs and their files.
- **Write routes (`/api/w/*`):** behind a Cloudflare Access application limited to the operator's Google account. FastAPI also checks the `Cf-Access-Jwt-Assertion` JWT against the team's public keys, so a request that skips Access is still refused.
- **CORS:** the Access application's CORS settings and FastAPI's both allow only `https://twin.papyrus-ai.net`, with credentials.
- **Runs:** one at a time, held by a `filelock` lock.
  - Cancel stops a run between stages.
  - A run doesn't start when the box has less than 10 GB free.
  - The container is capped at 8 CPUs.
- **Input handling:** parameters are checked against the schema and loaded with `yaml.safe_load`. File routes reject `..` and absolute paths. There is no shell access.

**Static showcase.**
- `twin publish <run-id>…` copies the public files of one run per drive into the Pages build, plus an area index (`area.json`: drives, facilities, best-covered run per facility):
  - plan rasters (lidar intensity, orthoimage, coverage), as 256 px WebP tile pyramids (decision 41);
  - GeoJSON;
  - a downsampled LAZ;
  - PDFs and DXFs;
  - manifest.
- Each file is at most 25 MiB, and the build holds fewer than 20,000 files (Pages limits).
- Public views read only these files, so the demo stays up when the box is busy or down.

**Georeference.**
- The Boston map origin comes from nuscenes-devkit `export_poses.py`.
- A local transverse Mercator projection is centred on that origin (`+proj=tmerc +lat_0=<lat> +lon_0=<lon> +k=1`). pyproj transforms from it to UTM zone 19N (EPSG:32619).
- Adding map offsets straight onto UTM coordinates is not used. It would ignore grid convergence of about 1.3° at Boston, roughly 20 m of error per km.
- The origin is approximate, so the absolute georeference error is unknown. That error is separate from plan accuracy against the HD map, which shares the same frame.

**Facilities across drives.** Facility IDs come from HD-map tokens, so the same facility has the same ID in every run. When several drives cover a facility, the area view shows the run with the highest core coverage and lists the others. Nothing is averaged across drives in v1.

**UI** (decision 34; reference: `prototypes/plan-view/index.html`).
- A Next.js static export in the Mission Control style. Design tokens are copied from drone-survey `web/`, with a note of where they came from.
- **Navigation:** area → facility → element. Breadcrumbs in the top bar; Esc goes up one level.
- **Map:** full width; pan and zoom over tiled rasters with vector overlays. Stroke widths stay constant on screen.
- **Map panel** (top-left, collapsible): layer toggles (lidar, orthoimage, markings, crosswalks, curbs) and one analysis at a time: accuracy (features coloured by error), safety (sight lines), coverage (observed / unobserved).
- **Profile strip:** under the map, for the open facility.
- **Right column:** the pipeline summary card (all steps compact; expands on demand, shrinking the inspector to a bar) and the inspector (area claims and facility index; facility tables and downloads; element trace).
- **Legal caption:** always visible in a corner.
- No page scroll at 1440×900. Phone and tablet layouts: #11, at the end of v1.

**Data licence.**
- The code is Apache-2.0.
- Derived outputs carry nuScenes' CC BY-NC-SA 4.0 and are never committed. The manifest and the site footer state this.
- The site is labelled "non-commercial research demo".

## 4. Contracts

T0 writes these as pydantic models in `twin/contracts.py` and exports JSON Schemas to `schemas/`. Every other ticket builds against them.

### Stages

| # | Stage | Methods | Requires | Outputs (in `<run>/<n>_<stage>/`) |
|---|---|---|---|---|
| 1 | load | `nuscenes` | (none) | `points.npz` (x, y, z, intensity, sweep), `poses.json` (dataset 4×4 per sweep), `boxes.json` (per sweep, interpolated, `parked` flag), `reference.geojson` (map layers, run CRS), `facilities.geojson` (core, legs, eye points, `id`, `type`, `name`, `map_tokens`), `cameras.json` (keyframe images, intrinsics, extrinsics, timestamps) |
| 2 | mask | `boxes` | load | `points.npz`, `parked.npz` |
| 3 | align | `kiss-icp`, `dataset-poses` | mask | `poses.json` (refined 4×4 per sweep), `qa.json` (x/y drift vs dataset, fallback used) |
| 4 | ground | `ransac-tiles`, `csf` | align | `ground.laz`, `nonground.laz`, `surface.npz` (0.5 m grid: z, count), `qa.json` (`rmse_m`, `z_disagreement_p95_m`, `height_valid`) |
| 5 | features | `intensity` (+ curbs `height-step`) | ground | `markings.geojson`, `crosswalks.geojson`, `curbs.geojson` (3D; properties `id`, `kind`, `n_points`) |
| 6 | colour | `zbuffer-topk` | mask, align, ground, features | `ortho.png` + `ortho.pgw` (5 cm, RGBA; alpha 0 = unobserved), `rgb.npz` (per point RGB + `observed`), `qa.json` (`edge_offset_p95_m`, `views_median`, `height_valid` copied) |
| 7 | profile | `centreline` | ground | `profile.csv` (`facility`, `s_m`, `z_m`, `n`), `centrelines.geojson` |
| 8 | isd | `aashto-b` | ground, mask | `isd.json`: per facility and leg/exit `required_m`, `available_m`, `available_with_parked_m`, `status` (`ok`, `short` or `indeterminate`), `reason` |
| 9 | accuracy | `one-way` | features, load | `accuracy.json`: per element and per facility `reference_layer`, `p50_m`, `p95_m`, `coverage`, `n`, `label` |
| 10 | outputs | `dxf-pdf` | features | `twin.laz` (RGB when colour ran), `twin.geojson`, `plan.dxf`, `plan.pdf`, `profile.dxf`, `profile.pdf` (if profile is enabled) |

Notes:
- **Stage interface:** `run(ctx: StageContext, params: <Stage>Params) -> StageResult`.
- **Stage status:** `pending`, `running`, `ok`, `skipped`, `failed` or `cancelled`.
- **Height validity:** `height_valid` lives in `ground/qa.json`. Colour, profile and ISD read it from there.
- **Facility coverage:** `observed_core` (0–1) per facility is written by ground into `qa.json`; below 0.5 the facility is "not scanned enough" and later stages skip it.
- **Turning curbs off** (`features.curbs.enabled: false`) leaves no curb file. Accuracy and outputs then skip curbs, and no stage requires them.

### Parameters (`params.yaml`, keyed by stage)

| Key | Default | Range |
|---|---|---|
| `select.min_density_pts_m2` | 50 | 1–1000 |
| `select.min_contrast` | 1.5 | 1.0–10 |
| `mask.box_margin_m` | 0.3 | 0–1 |
| `align.window_s` | 20 | 2–20 |
| `align.voxel_m` | 0.5 | 0.1–2 |
| `ground.voxel_m` | 0.05 | 0.02–0.5 |
| `ground.tile_m` | 5 | 1–20 |
| `ground.ransac_dist_m` | 0.05 | 0.01–0.3 |
| `ground.csf_cloth_m` | 0.5 | 0.1–2 |
| `ground.qa_cell_m` | 0.5 | 0.1–2 |
| `ground.qa_max_p95_m` | 0.10 | 0.01–1 |
| `features.intensity_pct` | 95 | 50–99.9 |
| `features.cluster_eps_m` | 0.3 | 0.05–2 |
| `features.min_points` | 20 | 3–1000 |
| `features.curbs.enabled` | true | bool |
| `features.curbs.step_min_m` | 0.08 | 0.02–0.3 |
| `features.curbs.step_max_m` | 0.25 | 0.1–0.5 |
| `colour.gsd_m` | 0.05 | 0.02–0.5 |
| `colour.zbuf_scale` | 0.25 | 0.1–1 |
| `colour.zbuf_tol_m` | 0.2 | 0.05–1 |
| `colour.min_depth_m` | 1.0 | 0.5–5 |
| `colour.top_k` | 5 | 1–12 |
| `colour.max_range_m` | 12 | 3–50 |
| `profile.sample_m` | 1.0 | 0.1–10 |
| `isd.case` | `B1` | `B1` (left turn), `B2` (right turn), `B3` (crossing) |
| `isd.time_gap_s` | 7.5 | 4–12 |
| `isd.design_speed_kmh` | 50 | 20–100 |
| `isd.eye_height_m` | 1.08 | 0.5–3 |
| `isd.object_height_m` | 1.08 | 0.2–3 (per-situation presets pending #15) |
| `isd.eye_setback_m` | 4.4 | 2–10 (used where the map has no stop line) |
| `isd.band_m` | 0.3 | 0.05–1 |
| `isd.coverage_window_m` | 2 | 0.5–10 |
| `isd.coverage_min_pts` | 20 | 1–1000 |
| `accuracy.buffer_m` | 1.0 | 0.1–5 |
| `facilities.min_observed` | 0.5 | 0–1 |
| `seed` | 0 | int |

`pipeline.yaml` holds, for each stage, `method` and `enabled`.

**Re-run rule:** a re-run from stage *k* may change only the parameters and methods of stage *k* and later stages. If a change touches an earlier stage *j*, the request is refused with "re-run from stage *j*".

### Manifest (`manifest.json`)

- `run_id` (`YYYYMMDD-HHMMSS-<6 hex>`), `parent` (`{run_id, from_stage}` or null)
- `code`: `git_sha`, `dirty`, `lockfile_sha256`
- `data`: `nuscenes_version` (`v1.0-mini`), `map_version` (`1.3`), `scene_token`, `osm_names` (Overpass query date, ODbL)
- `crs`: `epsg` (32619), `units` (`m`), `licence`
- `pipeline` and `params`, copied in full
- `stages[]`: `name`, `method`, `status`, `started`, `seconds`, `files[]`
- `metrics`: accuracy P50/P95/coverage per element and facility; ISD available and required per leg; ground `rmse_m` and `z_disagreement_p95_m`; `height_valid`; colour `edge_offset_p95_m`; `observed_core` per facility

**Compare** shows the differences in `pipeline`, `params` and `metrics` between two manifests.

### API routes

| Route | Use |
|---|---|
| `GET /api/r/registry` | stages, methods, parameter schema |
| `GET /api/r/runs`, `GET /api/r/runs/{id}` | run list, manifest |
| `GET /api/r/runs/{id}/files/{path}` | one stage output |
| `GET /api/r/compare?a=&b=` | differences between two runs |
| `POST /api/w/runs` | new run; body `{scene_token, pipeline, params}` |
| `POST /api/w/runs/{id}/rerun` | body `{from_stage, pipeline, params}` |
| `POST /api/w/runs/{id}/cancel` | stop between stages |

### CLI

- `twin select [--min-density N]`: prints a table of scenes. Exits 0.
- `twin run --scene <token> [--pipeline f] [--params f]`: prints the run ID. Exits 0 on success, 1 if a stage failed, 2 if the input is invalid.
- `twin rerun <run-id> --from <stage> [--params f]`: starts a re-run from that stage.
- `twin publish <run-id>... --out web/public/showcase`: copies the public files of one run per drive, tiles the rasters and writes `area.json`.
- `twin fake-run --out <dir>`: writes a synthetic run that matches the contracts, for UI and outputs work.

## 5. Alternatives considered

| Option | Rejected for v1 because |
|---|---|
| Gaussian splatting (DrivingGaussian, Street Gaussians, gsplat) | It doesn't measure geometry. The best-fit repos have no licence or a registration licence (related work, section 1). It needs GPU time shared with ollama. |
| Stacking sweeps on the dataset poses | nuScenes poses are 2D plus yaw, with z always 0 ([nuscenes-devkit#721](https://github.com/nutonomy/nuscenes-devkit/issues/721)). The stack would come out flat. |
| Pose from a ground-plane fit per sweep, or a pose graph | A ground-plane fit biases z on cambered or sloped roads, and a pose graph is more work than one short scene needs. KISS-ICP is an existing, MIT-licensed package with a nuScenes loader. |
| Learned vector mapper (MapTR, MIT) | It predicts 2D map elements from cameras, and no paper reports its height error (related work, section 5). Classic extraction outputs polylines from measured points, so each point traces back to the lidar. |
| Draping HD-map polygons onto the ground | The accuracy check would then compare the map with itself. |
| Symmetric Chamfer distance for accuracy | It penalises reference length the scan never covered. A one-way distance plus a separate coverage figure keeps the two apart. |
| Crest-curve stopping sight distance | It needs a valid vertical profile, which v1 can't validate (R1). ISD at an intersection depends mainly on plan geometry. |
| Fully static site | It can't run, re-run or compare (goal 6). |
| Custom auth (Papyrus token check, rate limiter) | Cloudflare Access gives Google sign-in and blocks requests at the edge, with no auth code to maintain. |
| Run-tracking tool (MLflow) | Too heavy for one scene and one user. A folder per run plus a manifest covers v1. |
| Potree / COPC 3D streaming viewer | A 3D viewer isn't a v1 goal. |
| Lyft Level 5 as the v1 source | Its pose degrees of freedom are unconfirmed, and a switch costs a day. It stays in the pool for v1.1. |

## 6. Methods (operator-directed)

**Select (setup).** Run per drive. Uses keyframe lidar points inside `drivable_area` that lie within 0.3 m of the lowest 5th percentile of z in each 5 m cell. For each scene it reports:
- points per m²;
- the ratio of the top-5% intensity to the median intensity.

If a scene fails the markings threshold, its runs report markings as "not extractable at this density". Accuracy then covers crosswalks and curbs only.

**Facilities (in load).** As decision 40:
- **Intersection:** a `road_segment` with `is_intersection`, plus each leg out to the leg's required sight distance, stopping at the next facility. Eye point on the map's stop line, else `isd.eye_setback_m` back from the core edge.
- **Segment:** consecutive non-intersection `road_segment`s between two intersections, merged.
- **Access point:** where a `carpark_area` meets the drivable area; labelled "map-derived".
- **ID:** type letter + the first 4 hex of SHA-1 over the sorted map tokens (`I-3fa9`); collisions extend the hash.
- **Name:** street names from one OpenStreetMap Overpass query for the area, cached under `/data/osm/`; ODbL attribution in the footer. Without the cache, the ID is shown.

**Load and mask.**
- Boxes exist only on keyframes. For each instance, its centre, size and yaw are interpolated linearly to each sweep timestamp between two keyframes. Boxes are not extrapolated outside that span.
- `parked` comes from the attribute on the nearest keyframe, because that attribute can change along an instance.
- Points inside a box widened by `mask.box_margin_m` are removed. Parked-vehicle points go to `parked.npz`.

**Align.**
- KISS-ICP runs on the masked sweeps over `align.window_s`, the whole scene by default (about 20 s). nuScenes has no per-point timestamps, so deskewing is off.
- KISS-ICP is odometry from the first sweep, so its trajectory is anchored to the dataset trajectory by a rigid fit in x, y and yaw (Umeyama).
- The result keeps KISS-ICP's relative z, pitch and roll between sweeps, and so makes them consistent. It does not recover absolute height.
- The x/y difference from the dataset poses is reported as drift.
- If ICP fails, the stage falls back to the dataset poses and sets `height_valid=false`.

**Ground.**
- `ransac-tiles` runs Open3D `segment_plane` in each tile.
- `csf` uses the cloth simulation filter (`cloth-simulation-filter` on PyPI, Apache-2.0).
- Both report ground-fit RMSE.
- QA computes the P95 of ground-z disagreement between points from different sweeps in the same `ground.qa_cell_m` cell. If it exceeds `ground.qa_max_p95_m`, the stage sets `height_valid=false`.

**Colour** (decisions 36 and 38; research: [camera-ground-projection](../research/camera-ground-projection.md)).
- One pose per keyframe image: the refined sweep poses interpolated to the image time, times the camera extrinsic.
- Occlusion: a depth buffer per image at `zbuf_scale` resolution from all points plus the boxes at the image time; a point is visible within `zbuf_tol_m`. Points nearer than `min_depth_m` are ignored.
- Each ground cell and point takes the per-channel median of its `top_k` views with the smallest footprint within `max_range_m`.
- QA: the P95 offset between painted edges in the orthoimage and the lidar markings. With `height_valid=false` the orthoimage is still made, labelled "indeterminate (height)".

**Markings and crosswalks.**
- Ground points above the `features.intensity_pct` intensity percentile in each tile are kept.
- They are clustered with DBSCAN, and polylines are fitted to the clusters.
- Crosswalks are reported as polygons around clustered stripes.
- This follows the classic mobile-mapping approach ([guan-2014-road-markings-mls]). Whether it works at 32-beam density is unproven; select tests it.

**Curbs (optional).**
- Found as height steps between `step_min_m` and `step_max_m` at the edge of the ground surface, then chained into polylines.
- Curbs are scored against the `drivable_area` boundary, so they are labelled "map-conditioned".

**ISD.** AASHTO Case B (stop control), in 3D against the twin's surface. Intersections: one line per leg. Access points: exit lines left and right.
- **Sub-case and gap:** set by `isd.case` and `isd.time_gap_s`. The default is B1 for a passenger car, 7.5 s.
- **Required distance:** 0.278 × `design_speed_kmh` × `time_gap_s`.
- **Heights:** eye and object height default to 1.08 m. Per-situation target heights (car, headlights, pedestrian, cyclist) wait on research #15.
- **Sight line:** each leg has one, from the eye point to the object point at the required distance.
- **Blocking:** a point blocks the line if it lies above the ground surface, below the line, and within `isd.band_m` of it horizontally. So canopy above the line doesn't block.
- **Indeterminate:** a leg is indeterminate if any `coverage_window_m` stretch has fewer than `coverage_min_pts` ground points, or if `height_valid=false`.
- **Parked vehicles:** each leg is computed twice, without and with `parked.npz`.

**Accuracy.**
- Measures the one-way distance from each extracted vertex to its reference layer, read through `NuScenesMap`.
- Lane markings use `lane_divider` and `road_divider`. Both are map lines, not painted edges; `road_divider` is a median line and a weaker reference.
- Crosswalks use `ped_crossing`.
- Curbs use the `drivable_area` boundary, labelled "map-conditioned".
- Coverage is the share of reference length within `accuracy.buffer_m` of an extracted element, computed with shapely.
- Results are P50 and P95 in metres, per element and per facility (elements inside the facility). No pass/fail threshold is set in v1.

**Outputs.**
- `laspy[lazrs]` writes LAZ, with the CRS set via `header.add_crs()`.
- Rasters for publishing are cut into 256 px WebP tile pyramids (decision 41), so every file stays far under 25 MiB; the run keeps the full PNG and world file.
- ezdxf writes DXF. The PDF is drawn from the same DXF with the ezdxf `drawing` add-on (matplotlib backend).

## 7. Risks and limits

| # | Risk or limit | Mitigation |
|---|---|---|
| R1 | No independent height reference exists for nuScenes, and the absolute georeference error is unknown. | The profile is descriptive only. Height-dependent outputs follow `height_valid`. A check against Vancouver airborne lidar comes in v1.1: City of Vancouver LiDAR 2022 states 0.081 m vertical accuracy at 95% (opendata.vancouver.ca, `lidar-2022`). |
| R2 | ICP drifts or fails. | Masking first, anchoring to dataset x/y/yaw, the ground-z QA check, and the fallback to dataset poses. When height fails, the UI shows "indeterminate (height)". |
| R3 | No Boston mini intersection has enough lidar density. | Select decides on day 1. The no-go branch is in section 6. |
| R10 | Few drives overlap, so facilities have thin coverage. | Facilities below 50% observed are listed as "not scanned enough", never hidden. |
| R11 | OpenStreetMap names don't match the HD map. | Names are display only; IDs come from the map. Unmatched facilities show their ID. |
| R4 | Extracted markings are noisy. | P50 and P95 with coverage are reported as measured. |
| R5 | Five days is short. | If late, cut in this order (decision 31): (1) the profile sheet, (2) DXF (the PDF stays), (3) the colour stage, (4) ISD. Never cut reconstruction (point cloud, ground, markings, crosswalks, curbs), the controls or the three honesty items. |
| R6 | The API runs on a shared production machine. | Access on write routes, one run at a time, an 8-CPU cap, no shell, schema-checked parameters, and the 10 GB free-disk check. Public views never touch the box. |
| R7 | nuScenes is non-commercial, and the site is on a company domain. | A "non-commercial research demo" label, attribution, and no paid features. |
| R8 | Scale: about 8 drives as separate runs, one run at a time, one shared machine, and an unbounded run store. | Accepted for v1; the free-disk check guards the machine. A batch queue, retention and more workers wait until after v1.1. |
| R9 | nuscenes-devkit lists support only up to about Python 3.9. | T1 tests the install on 3.11 on day 1. If it fails, fall back to 3.10, or vendor the map API. |

## 8. Acceptance criteria

- **Select:** `twin select` lists the Boston mini drives, with density, contrast and go/no-go for each.
- **Facilities:** every facility in the area has a stable ID across two runs; facilities under 50% observed show "not scanned enough".
- **Colour:** the orthoimage shows no colour where no camera saw the ground; `edge_offset_p95_m` is reported.
- **Run:** a run on one drive finishes on the box CPU in under 30 minutes. It writes every output in section 4. The time is estimated in T4 and measured on the full run in T11.
- **Manifest:** validates against `schemas/manifest.schema.json`.
- **Repeatability:** two runs with the same parameters give accuracy P50 and P95 within 0.02 m for each element.
- **Drawings:**
  - The plan and profile DXFs pass `ezdxf` audit.
  - The PDFs open.
  - Each sheet has a scale bar, a source line and a licence line. The plan also has a north arrow.
- **Profile:** shows ground z against distance along the approach, labelled descriptive. It shows "indeterminate (height)" when `height_valid=false`.
- **Accuracy panel:** shows P50, P95 and coverage for each element, names each reference layer, and labels curbs "map-conditioned".
- **ISD:**
  - Each leg shows the available and required distance, or "indeterminate", both without and with parked vehicles.
  - A synthetic test confirms that a canopy point above the sight line doesn't block it.
- **Security:**
  - A POST to `/api/w/*` without Access credentials gets 302, 401 or 403 at the edge.
  - A POST with a forged or missing JWT gets 401 at the origin.
  - A file route rejects `..`.
  - A pipeline where an enabled stage needs a disabled one is rejected.
  - A re-run that changes an earlier stage's parameters is rejected.
- **Controls:**
  - Signed out, the developer panel shows the live runs, with controls disabled.
  - Signed in, the operator changes one parameter, re-runs from the stage that uses it, and sees the comparison with the parent run.
- **Public views:**
  - They load from static files while the box is unreachable.
  - At 1280 px and 1440×900 there is no page scroll, every view can be reached, and no control is clipped. Phone and tablet widths: #11.
  - The footer credits OpenStreetMap (ODbL) for street names.
  - The footer shows the licence and the "non-commercial research demo" label.

## Detailed Implementation Plan

Ticket labels:
- **[operator]:** methodology. The operator reviews it line by line.
- **[scaffold]:** built by agents.

Every ticket's PR includes pytest tests. CI runs them on synthetic fixtures. nuScenes data never goes into CI, because download needs a login and the licence bars committing it. Real-data checks run on the box with `make itest`.

**Dependencies.**
- T0 and T1 come first.
- T2, T3 and T9 follow T0 and T1.
- T4 needs T2 and T3.
- T5 needs T4.
- T6 and T7 need T5.
- T8 builds on `twin fake-run` after T0 and is finished after T6 and T7.
- T12 (colour) needs T5. T13 (facilities) needs T2.
- T10 needs T0 and uses `twin fake-run`. Its live panel needs T9.
- T11 comes last.

- **T0 [scaffold]: contracts.**
  - `twin/contracts.py`: pydantic models for the section 4 contracts (stages, parameters, pipeline, manifest, StageResult).
  - JSON Schemas in `schemas/`.
  - The `twin fake-run` command.
  - Done when the schemas validate a fake run and the tests reject a bad pipeline and a bad re-run.
- **T1 [scaffold]: package and CI.**
  - `twin/` package with `pyproject.toml` and `uv.lock`, on Python 3.11 (R9).
  - Dependencies, licences in brackets:
    - numpy, pyyaml, pydantic, filelock;
    - open3d (MIT), kiss-icp (MIT, version pinned), cloth-simulation-filter (Apache-2.0);
    - laspy[lazrs], pyproj, shapely, ezdxf, matplotlib;
    - nuscenes-devkit (Apache-2.0);
    - fastapi, uvicorn, PyJWT.
  - GitHub Actions runs pytest and ruff.
  - Synthetic fixtures in `tests/fixtures/`: a sloped plane with painted stripes, a curb step and a canopy.
- **T2 [scaffold]: data and select.**
  - `scripts/get_nuscenes_mini.sh` installs to `/data/nuscenes` on the box. It prompts the operator for the download link and does no login itself.
  - `twin select` as in section 6.
  - The operator picks the scene.
- **T3 [scaffold]: runner and run store.**
  - Stage registry, `requires` check, run folders and manifest writing.
  - Hard-link re-run with the re-run rule.
  - `filelock` queue, cancel between stages, and the 10 GB free-disk check.
  - CLI: `run`, `rerun`, `publish`.
- **T13 [operator]: facilities.**
  - In load: `facilities.geojson` from the HD map and the cached OSM names, as in section 6.
  - Tests: IDs are stable across two loads; a merged segment spans two intersections; an intersection leg stops at the next facility.
- **T4 [operator]: stages 1–3.**
  - `twin/stages/{load,mask,align}.py`.
  - Tests:
    - box interpolation between two keyframes;
    - the anchored fit recovers a known x/y/yaw offset;
    - an ICP failure sets `height_valid=false`.
  - On the box, measure the runtime and estimate the full run.
- **T5 [operator]: stages 4–5.**
  - `twin/stages/{ground,features}.py`.
  - Tests:
    - ground RMSE under 0.02 m on the synthetic plane;
    - the stripes come out as polylines;
    - the curb step is found;
    - the QA check flags a 0.2 m sweep offset.
- **T12 [operator]: stage 6, colour.**
  - `twin/stages/colour.py`.
  - Tests: a synthetic camera over the striped plane recovers stripe colour; a box in front of the camera occludes; unseen cells stay transparent.
- **T6 [operator]: stages 7–8.**
  - `twin/stages/{profile,isd}.py`.
  - Tests:
    - the profile recovers the synthetic slope;
    - canopy doesn't block;
    - a wall does block;
    - a coverage gap gives "indeterminate";
    - `height_valid=false` gives "indeterminate".
- **T7 [operator]: stage 9.**
  - `twin/stages/accuracy.py`.
  - Tests:
    - a known 0.5 m offset gives P50 = 0.5 m;
    - a half-covered reference gives coverage 0.5;
    - with curbs off, the curb element is skipped.
- **T8 [scaffold]: stage 10.**
  - `twin/stages/outputs.py`: LAZ, GeoJSON, DXF, and PDF via the ezdxf drawing add-on.
  - `twin publish` adds the tiled rasters, the downsampled LAZ and `area.json`.
  - Tests:
    - DXF audit is clean;
    - every published file is at most 25 MiB.
- **T9 [scaffold]: control API.**
  - The section 4 routes, with JWT check, CORS, schema validation, path checks and compare.
  - Tests for the section 8 security items, using a test signing key.
  - The Cloudflare Tunnel config and the Access application on `/api/w/*` are written as a runbook. The operator approves the DNS record and the Access policy on day 1.
- **T10 [scaffold]: UI.**
  - Public views read static files; the developer panel uses the live API.
  - The brief includes:
    - what each view is for;
    - drone-survey `web/` as the reference skeleton;
    - banned patterns;
    - the approved mockup `prototypes/plan-view/index.html` as the layout reference;
    - a screenshot self-review at 1280 px and 1440×900 against section 8.
  - Web build and lint run in CI.
  - Built against `twin fake-run` output until the real outputs exist.
- **T11 [scaffold]: deploy.**
  - Dockerfile for the API, with the 8-CPU cap.
  - Pages project and the `twin` tunnel.
  - `twin publish` of the showcase run.
  - A smoke test of section 8, including the repeat-run check and the full-run time.

**Order to 2026-11-12**

| Day | Work |
|---|---|
| 1 | T0, T1; then T2, T3; drive check; operator approves DNS + Access policy |
| 2 | T4, T13, T9, T10 (on fake runs) |
| 3 | T5, T8 (on fake runs), T10 |
| 4 | T6, T7, T12, finish T8; #11 if time |
| 5 | T11, fixes |
