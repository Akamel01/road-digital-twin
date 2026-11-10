# 0006 — Cameras and lidar together

Date: 2026-11-10. Status: agreed by the operator, 2026-11-10 (grilling Q1–Q7).

**Principle.** Lidar measures where things are. Cameras show what they are. Camera reconstruction is constrained by the lidar: poses come from the ego pose and the calibration, and scale and depth are checked against the lidar. It is not built as a separate cloud and blended in afterwards. Every point and every element records its source sensor and its uncertainty.

| # | Decision |
|---|---|
| Q1 | Lidar is the authority for geometry and scale. Cameras are the authority for appearance and paint, and they fill the lidar's gaps. Move to per-point uncertainty weighting once the error of each sensor is measured per element. |
| Q2 | Three camera products, in this order: (a) per-image semantics (paint, curbs, signs, signals) projected onto the lidar ground and voted across drives; (c) 3D Gaussian Splatting started from the lidar points and checked against lidar depth, giving a 2–3 cm orthophoto and the viewing layer; (b) MVS with fixed poses (COLMAP), as a check on (c). Splats are a rendering: nothing is measured from them unless the lidar confirms it. |
| Q3 | Start from the dataset poses. Allow small refinement inside the optimiser, and report each camera's correction as QA. A large correction flags the drive. |
| Q4 | Use a Mapillary Vistas–trained segmenter for now, marked research-only (CC BY-NC-SA) in the manifest. Build our own labelled set before any commercial use. |
| Q5 | Each study area is built three ways under the same gates: lidar-only, camera-only and fused. Fusion is adopted per element only where it beats lidar-only. |
| Q6 | GPU: unload ollama (Librarian's local models) while twin GPU jobs run (option a). **Top priority.** Supersedes ADR 0005's "yield to production" for twin GPU jobs. |
| Q7 | Heights across drives: correct each sweep's z, roll and pitch against a consensus ground surface, iterating. x, y and yaw keep the dataset values. The CAN-bus IMU is used only as a check on roll and pitch. |
