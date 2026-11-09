# 0004 — Reconstruction engine: poses, multi-drive fusion, confidence

Date: 2026-11-08. Issue #110. Status: agreed by the operator, 2026-11-08.

The engine is the chain load → mask → align → ground → features → colour. Every measured number in the twin comes out of it. This note reviews it against three questions the operator raised: is the vehicle pose used fully, how should drives by other cars be combined, and how should confidence grow with more passes.

Prior work: [multi-sensor-sota](../research/multi-sensor-sota.md), [kiss-icp-fit](../research/kiss-icp-fit.md), [camera-ground-projection](../research/camera-ground-projection.md), [related-work](../research/related-work.md).

## 1. Vehicle pose (position, yaw, full orientation)

The vehicle pose is already the backbone. What each stage uses:

| Stage | Pose use today |
|---|---|
| load | Dataset ego pose per sweep: x, y, yaw from nuScenes' lidar-map localisation (≤ 10 cm reported). |
| mask | Boxes interpolated to each sweep time, so moving road users are cut out at the right place. |
| align | KISS-ICP gives the full 6-DoF track: x, y, z, roll, pitch, yaw. It is anchored to the dataset x, y and yaw per window, and falls back to dataset poses when drift P95 exceeds 1 m. |
| ground | All sweeps are placed with the align poses before the surface is built. A disagreement between sweeps marks `height_valid=false`. |
| colour | Camera pose at each image's own time = interpolated vehicle pose × camera extrinsic. Cameras fire at different times from the lidar, so this interpolation matters. |

**Gaps, in order of value:**
1. **Pose quality does not reach the element level.** The align QA (`fallback_used`, drift P95) stops at `height_valid`. Recommendation for v1: copy the drive's pose QA onto every element's evidence, so an auditor sees the pose quality behind each marking.
2. **The CAN-bus IMU is not used.** nuScenes ships a 100 Hz IMU in a separate expansion. Its time alignment with the sensors is not documented. v1.1: use it only as a check on roll and pitch, not as an input.
3. **Camera extrinsics are taken on trust.** nuScenes publishes no calibration accuracy. v1.1: verify them with koide3's calibration tool (MIT), as the research recommends.

## 2. Combining drives by other cars

v1 keeps each drive as its own run. The area view places drives in one frame and, for each facility, shows the best-covered drive. Nothing is averaged (spec, decision 35; #14 is the v1.1 merge). This is the right v1 choice: each run stays a closed, auditable record.

**v1.1 method (extends #14):**
1. **Register.** All drives already share the nuScenes map frame. Refine each overlapping pair with ICP on static points only: ground plus masked non-ground, with parked cars removed. Accept the correction only if the residual P95 is under a threshold; otherwise keep the drives apart and flag the overlap.
2. **Fuse per cell, keep per-drive evidence.** On the 0.5 m ground grid, keep each drive's height and point count. The fused height is the median across drives. The spread across drives is the QA figure, as `height_valid` is today.
3. **Fuse elements by matching, never by averaging blindly.** Extract markings per drive as now, then match them across drives within a tolerance. A fused element records which drives saw it (`seen_in`) and which drives covered the place but did not see it (`covered_by`).
4. **Change over time.** Parked cars, roadworks and repainting differ between drives. The latest observation wins, with its date, and a disagreement is shown, not hidden.

## 3. Confidence that grows with passes

Confidence is reported as counts, not as a single invented score:
- **Observed:** a cell or element seen by at least one drive, with lidar evidence. Camera evidence is added by the colour stage when an image confirms the paint.
- **Confirmed:** seen by two or more drives that agree within tolerance, or by lidar and camera in one drive. Either counts.
- **Modelled:** inferred and not seen, for example a gap bridged between two observed pieces. It is a separate feature, drawn differently, and never counted in accuracy.

Each additional drive can only add evidence. It fills gaps (`covered_by` grows) and moves elements from observed to confirmed.

## 4. v1 / v1.1 split

**v1 (due 2026-11-12):**
- Keep the engine as built.
- Already done: markings and curbs follow the points, gaps stay gaps, and every feature carries `evidence` and `reliability` (operator, 2026-11-08).
- Add: copy the pose QA onto element evidence (one small ticket).
- Add: the colour stage appends `camera` to a marking's evidence when its image edges agree (part of 7c).

**v1.1:**
- Multi-drive registration and fusion (section 2, #14).
- Confirmed status from multi-drive agreement.
- Extrinsic verification and an IMU roll/pitch check.
- Hazards (#111).
- 3D view.

## Operator decision

Either counts as confirmed: two or more agreeing drives, or lidar plus camera from one drive (operator, 2026-11-08).
