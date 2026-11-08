# Projecting nuScenes camera images onto the ground surface

Issue #7 (part of #3). Feeds the colour-stage method ticket (#8). Researched 2026-11-07.
Source ids in `[brackets]` are entries in `sources.yaml`. Other primary sources are linked inline.

## Answer: recommended v1 method (`colour.zbuffer-topk`)

1. **Camera pose per image, from our own poses.** For every `CAM_*` sample_data in the scene (12 Hz, not only keyframes), build
   `T_global_cam(t_cam) = interp(T_global_ego_refined, t_cam) · T_ego_cam`.
   - `T_ego_cam` comes from the camera's `calibrated_sensor` record.
   - `T_global_ego_refined` is the align stage's refined 6-DoF sweep pose. Interpolate it to the image timestamp: lerp the translation and slerp the rotation between the two sweeps around `t_cam` (they are 50 ms apart).
   - Do not use the camera's dataset `ego_pose` as it is. It is 2D (z = 0, yaw only), so it would not match the 6-DoF cloud. A pitch mismatch is amplified on the ground (see the error table).
2. **Project with the devkit chain.** Use the same steps as `map_pointcloud_to_image`, then `view_points(K)`. The images are already undistorted, so there is no distortion model. Keep a point only if its depth is at least `min_depth_m` and it falls inside the image with a 1 px margin.
3. **Occlusion with a z-buffer per image.**
   - Render a depth buffer from everything that can block the road: ground, non-ground and parked points, splatted at quarter resolution.
   - Also rasterise **all annotated boxes**, interpolated to `t_cam`. The mask stage removed moving road users from the cloud, but they are still in the photos. Without the boxes they would paint the road.
   - A ground sample is visible if `depth ≤ zbuf + zbuf_tol_m`.
4. **Candidate filter.** Keep a view only if its horizontal range from the camera is at most `max_range_m`. Beyond that, the error from ground height and pitch grows with the square of the range.
5. **Blend: top-K median.**
   - For each orthoimage cell (and each 3D point), rank the visible candidates by ground footprint, with the smallest footprint first. The footprint is about `d³/(f²h)`, so this is close to nearest-first.
   - Keep the best `top_k` candidates and take the per-channel median.
   - The median removes transient occluders that no box covers, and odd exposures. A small K keeps the result sharp.
   - Cells with no candidate are no-data. Report `coverage` in `qa.json`.
6. **QA.** Measure the registration directly. Detect lane-marking edges in the orthoimage, take the offset to the lidar-intensity markings (features stage), and write P50/P95 to `colour/qa.json`. This replaces the error budget below with a measured number.

| Parameter | Default | Range | Why |
|---|---|---|---|
| `colour.cell_m` | 0.05 | 0.02–0.5 | Matches `ground.voxel_m`; ground footprint is ≤ 5.8 cm out to 10 m |
| `colour.max_range_m` | 12 | 5–30 | Error ≤ ~16 cm per 2 cm of ground-z error (table below) |
| `colour.min_depth_m` | 1.0 | 0.5–5 | Devkit default; drops camera-housing points |
| `colour.top_k` | 5 | 1–20 | 1 = nearest view (sharpest, seams); larger = smoother, blurrier |
| `colour.zbuf_scale` | 0.25 | 0.1–1 | Depth buffer at 400×225 fills splat holes between points |
| `colour.zbuf_tol_m` | 0.2 | 0.05–1 | Above the ground-z noise; below a curb plus a car's ground clearance |
| `colour.box_margin_m` | 0.3 | 0–1 | Same as `mask.box_margin_m` |
| `colour.frame_step` | 1 | 1–12 | 1 = all 12 Hz frames (~1,440 images per 20 s scene) |

The 3D point RGB uses the same steps, with the depth test against the point itself.

Exposure balancing between images (the global seam adjustment of [waechter-2014-let-there-be-color]) is not in v1. Add it only if seams show up in the showcase run.

## Main error sources and their size

Assumptions for the numbers: horizontal focal length f ≈ 800 / tan(35°) ≈ 1,140 px (70° FOV over 1,600 px, from the paper); camera height h ≈ 1.5 m (assumed, read the real value from `calibrated_sensor`); speed v = 4.4 m/s (the 16 km/h average in the paper) and 10 m/s worst case; d is the horizontal range.

| Source | Formula | Size | Handling |
|---|---|---|---|
| Ground-z error δz moves the ray hit | δz·d/h | δz = 2 cm: 6.7 cm at 5 m, 13 cm at 10 m, 16 cm at 12 m. δz = 5 cm: 33 cm at 10 m | **Largest term.** Use ground points or a fine surface, not the 0.5 m grid. Cap the range. |
| Pitch error δθ (extrinsic or pose), along the range | δθ·d²/h | 0.1°: 2.9 cm at 5 m, 12 cm at 10 m | Use the refined 6-DoF pose (step 1) |
| Yaw/roll error δθ, across the range | δθ·d | 0.1°: 1.7 cm at 10 m | Small |
| Wrong pose time (sweep pose used for a camera) | v·Δt, Δt up to 50 ms | 22 cm (4.4 m/s), 50 cm (10 m/s) | Avoided: each image gets its own interpolated pose |
| Exposure midpoint vs trigger timestamp | v·T/2, T ≤ 20 ms | ≤ 4.4 cm (avg), ≤ 10 cm (worst); far smaller in daylight | Not correctable (exposure time not stored) |
| Motion blur | v·T | ≤ 9 cm (avg), ≤ 20 cm (worst) | Small K favours near views; accept |
| Ground footprint (resolution), along the range | d²/(f·h) | 1.5 cm at 5 m, 5.8 cm at 10 m, 13 cm at 15 m, 23 cm at 20 m | `max_range_m` |
| Rolling shutter | n/a | 0 | Images are global shutter (below) |
| Lidar-camera sync within one image | 70°/360° × 50 ms | ±4.9 ms at the image edges | Irrelevant: we project a static, aggregated surface |
| Absolute localisation | n/a | ≤ 10 cm | Shifts cloud and images together; it does not misregister them |
| Calibration and intrinsics accuracy | n/a | Not published | Measured by the marking-edge QA |

In practice the result is limited by ground-height error and pitch along the range. Both grow fast with range, which is why `max_range_m` and nearest-first ranking matter more than the blend rule.

## Findings and sources

### Transform chain (devkit)

`NuScenesExplorer.map_pointcloud_to_image` in `python-sdk/nuscenes/nuscenes.py` ([nuscenes-devkit-repo], commit `b40adc4`) does this:
1. sensor → ego with the point sensor's `calibrated_sensor`;
2. ego → global with the `ego_pose` at the **sweep** timestamp;
3. global → ego with the `ego_pose` at the **image** timestamp;
4. ego → camera with the camera's `calibrated_sensor` (inverse);
5. `view_points(points, camera_intrinsic, normalize=True)`.

It then keeps points with depth > `min_dist` (default 1.0 m) and inside the image with a 1 px margin. The code comment explains that the 1 m cut removes lidar points on the camera casing for non-keyframes, which are slightly out of sync. The devkit does no occlusion test: every point in front of the camera is drawn.

The [schema](https://github.com/nutonomy/nuscenes-devkit/blob/master/docs/schema_nuscenes.md) says:
- all extrinsics are given relative to the ego body frame;
- all camera images are undistorted and rectified;
- `ego_pose` comes from lidar map-based localisation, is 2-dimensional in the x-y plane, and its z is always 0.

### Sync, rates, exposure, shutter

From the nuScenes paper [caesar-2019-nuscenes]:
- **Rates:** the cameras run at 12 Hz and the lidar at 20 Hz. The 12 exposures are spread across the 20 scans, so not every scan has an image.
- **Sync:** a camera's exposure is triggered when the top lidar sweeps across the centre of that camera's FOV. The image timestamp is the trigger time. The lidar timestamp is the end of the full rotation.
- **Sensors:** a 1/1.8" CMOS sensor, 1600 × 900, auto exposure, JPEG.
- **Poses and calibration:** localisation error ≤ 10 cm. Calibration was updated about twice a week.

The [nuScenes data-collection page](https://www.nuscenes.org/nuscenes#data-collection) adds:
- the camera is a Basler acA1600-60gc behind a 5.5 mm f/1.8 lens;
- the 1600 × 900 image is a crop from the 1600 × 1200 sensor;
- auto exposure is capped at 20 ms.

Shutter: Basler's [product page](https://www.baslerweb.com/en/shop/aca1600-60gc/) lists the EV76C570 sensor with "Global & Rolling Shutter", so it can run in either mode. A nuScenes maintainer confirmed that the images were taken with a **global shutter** ([devkit #1058](https://github.com/nutonomy/nuscenes-devkit/issues/1058), 2024-03-26). Lidar sweeps are already motion-compensated for ego motion ([devkit #293](https://github.com/nutonomy/nuscenes-devkit/issues/293)).

### Occlusion and blending in prior work

- **[vechersky-2018-colourising]**, colouring a lidar map from a loosely coupled camera:
  - interpolates the device trajectory linearly at each image time, then applies the camera extrinsic;
  - tests visibility with the hidden point removal operator [katz-2007-hidden-point-removal], using the exponential kernel because it is scale invariant;
  - speeds that up by voxelising and limiting the test to a radius around the camera;
  - colours each point with a sequential robust weighted Gaussian mean, weighted towards closer views.

  We use the same pose idea. We swap HPR (O(N log N) per pose) for a z-buffer, which is simpler and parallel, and swap the robust mean for a top-K median.
- **[gharibi-2018-true-orthophoto]**, true orthophotos from aerial images:
  - reviews the z-buffer, height-based and angle-based occlusion tests;
  - notes that the z-buffer gives false occlusions or false visibility when the image GSD and the DSM cell size do not match. Our `zbuf_scale` and `zbuf_tol_m` exist for that reason;
  - mosaics from the closest visible image, with inverse-distance weighting to balance colour.
- **[waechter-2014-let-there-be-color]** ([mvs-texturing-repo], BSD-3-Clause):
  - picks one view per face with an MRF;
  - criticises angle-only data terms because they ignore proximity and resolution;
  - prefers the projected-gradient term, which favours close, sharp views;
  - then makes a global additive colour adjustment to hide seams.

  This is the upgrade path if top-K median seams are visible.

## Open items

- Read the real camera heights and intrinsics on the box once nuScenes mini is there. `/data/nuscenes` was not present on 2026-11-07, so the f and h in the table are derived or assumed.
- The ego body may show in the bottom rows of some cameras. Check during the showcase run, and add a fixed per-camera mask if it does.
