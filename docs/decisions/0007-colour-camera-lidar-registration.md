# 0007 — Colour stage camera-to-lidar registration

Date: 2026-11-10. Status: agreed by the operator, 2026-11-10.

This record covers issue #265: a second, selectable colour method that refines each camera frame's pose against lidar paint edges. It extends ADR 0006 (cameras and lidar together) and ADR 0005 (evaluation gates, GPU use). Lidar remains the authority for geometry and scale (ADR 0006 Q1); cameras are the authority for appearance.

## Principle

The orthoimage must land its painted edges on the lidar-intensity markings. A global shift cannot reach 5 cm because the offset varies along a single crosswalk, so refinement is per camera frame, anchored on crisp lidar paint edges projected into the image (ADR 0006 Q3). The refined poses are used for colouring only; they are not written as a new output file. Corrections are reported as QA.

## Decisions

| # | Decision |
|---|---|
| D1 | Keep one `colour` stage (stage 6) with two methods: `zbuffer-topk` (default, unchanged) and `zbuffer-pose-refine` (new). Do not add a new stage. `STAGES["colour"].methods = ("zbuffer-topk", "zbuffer-pose-refine")`; default stays `zbuffer-topk` for backward compatibility and comparison runs. |
| D2 | Refinement is per camera frame (amended 2026-11-16, #270; was per channel): 6 DOF per image, right-multiplied as `c2w' = base_c2w @ T_delta`, with `delta6 = (rx, ry, rz, tx, ty, tz)` in the camera frame. Per channel cannot work: frames of one channel carry different errors (ego pose and timing), so one shared correction fits none of them (`tests/test_colour_pose.py::test_stage_refines_each_frame_of_a_channel_on_its_own`). |
| D3 | Bounds: rotation `±pose_max_deg` (default 0.5, range 0.01–5) and translation `±pose_max_m` (default 0.05, range 0.001–1), per component. `hit_bound` is true when any component of the frame's solution is within 0.1% of its bound; such a frame keeps its calibrated pose (reason `hit_bound`). |
| D4 | Flag thresholds: a camera is flagged when its correction exceeds `pose_flag_deg` (default 0.25) or `pose_flag_m` (default 0.025). A drive is flagged when at least a quarter of its cameras are flagged. |
| D5 | Per frame: measure each anchor's stripe centre in the image (`colour._cross_section_offset` on a pixel cross-section along the projected line's normal, ±0.8 m at the anchor depth), then solve `scipy.optimize.least_squares` (TRF, `soft_l1`, scale 1.5 px) on the point-to-line residual in pixels plus a weak prior towards the calibrated pose (1 px at the bound). Four measure-then-solve rounds (ICP style). Visibility (`zbuffer.visible`) is computed once per frame at the calibrated pose. `pose_max_anchors` (default 200) and `pose_max_nfev` (default 200) bound work; `pose_min_anchors` (default 20) is the minimum measured anchors. |
| D6 | Anchors are image stripe centres derived from observed lidar markings: sample each observed-reliability marking at `EDGE_STEP_M`, interpolate ground z from `surface.npz`, fall back to nearest `points_3d` z when the surface is missing or out of range. Markings with too few cross-sections are dropped. The refinement trains on the complementary subset of markings; the acceptance metric is computed on the held-out subset. |
| D7 | Inlier gate: each round drops anchors with no measured stripe or `|residual| > max(2 px, 3 sigma)` (sigma = MAD × 1.4826). The correction is applied only if at least `pose_min_anchors` inliers remain, it is inside the bound, and the median stripe offset re-measured at the new pose is lower than at the calibrated pose; otherwise the frame keeps its calibrated pose (`insufficient_inliers`, `hit_bound` or `no_improvement`). |
| D8 | Ground z for anchors comes from `surface.npz` (the 0.5 m ground grid), with a `points_3d` fallback. |
| D9 | `pose_corrections` (null for `zbuffer-topk`) reports: `n_cameras`, `rotation_deg_p50`, `rotation_deg_p95`, `rotation_deg_max`, `translation_m_p50`, `translation_m_p95`, `translation_m_max`, `n_flagged`, `drive_flagged`, `by_channel`, `applied` (any frame applied), `hit_bound` (any frame hit its bound), `reason` (`converged` when every frame applied, otherwise the commonest reason a frame did not), `reasons` (count per reason) and `n_applied`; the colour QA also has `n_refined`, `n_reverted` and `n_skipped` (frames with no visible anchors). `n_cameras` is the number of camera frames. |
| D10 | QA metrics: `edge_offset_p50_m` and `edge_offset_p95_m`, the offset in metres between painted edges in the orthoimage and the lidar markings, pooled over cells at the ortho cell size (`colour.gsd_m`). Resolution is image-space offset in metres at the ortho cell gsd. |
| D11 | Hold-out partition: sorted observed marking ids, every 4th held out (indices 3, 7, 11, …, 0-based), with `HOLDOUT_EVERY = 4`. Refinement trains on the rest. `edge_offset_p95_m` pools every observed marking for both methods, so the two compare on the same samples; `edge_offset_holdout_p95_m` and `edge_offset_holdout_samples` report the held-out markings alone. `camera_confirmed` is reported on all markings. |
| D12 | Default method remains `zbuffer-topk`. Adoption of `zbuffer-pose-refine` requires `edge_offset_p95_m <= 0.05 m` on the I-1efe drives. |
| D13 | GPU lease: colour stays in `GPU_STAGES`, so the lease unloads ollama models while colour runs. Pose refinement is CPU-only and acquires no GPU lease; it must not use the GPU. If a future GPU implementation is desired, it must go through the same `_to_gpu` free-memory check and remain inside the lease. |
| D14 | `pose_report` lives in the neutral module `twin/pose.py` and is re-exported from `twin/stages/splats.py` (`from twin.pose import pose_report`), with no duplication or import cycle. `pose_report` accepts any params object exposing `pose_flag_deg`/`pose_flag_m` (and the rest) via a structural `Protocol`. |

## Consequences

- `twin/stages/colour.py` registers both methods and keeps `run = run_zbuffer_topk` as a backward-compatible alias; `colour.run` chooses the pose path per method.
- `twin/stages/colour_pose.py` holds the pure-CPU refinement and anchor sampling, so the synthetic recovery test needs no GPU or stage wiring.
- `twin/fake_run.py`, `schemas/params.schema.json` and `schemas/manifest.schema.json` carry the new method enum and params together with the stage code.
- `web/lib/runmetrics.ts` surfaces `edge_offset_p50_m` only; `pose_corrections` stays QA-only.
- No open questions remain for this stage.
