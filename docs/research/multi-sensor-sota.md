# State of the art: multi-sensor road reconstruction (ticket #13)

How this note was produced: primary high-trust sources first (papers with DOI, repos with verified GitHub full_name, products), registered in `docs/research/sources.yaml` and cross-referenced in `docs/research/related-work.md`. Every bracketed `[id]` resolves to a `sources.yaml` entry. No numbers are invented; cells that lack a sourced number are labelled "not reported in this pass" or "title-level read only". PSNR/SSIM are image-quality metrics and are never presented as geometry accuracy. Licence fields are copied from the source (repo licence file or paper terms), not inferred.

Questions 1-8 are unchanged (E-2). New topics map onto existing questions: colour/occlusion->Q8, lidar-only/Vancouver->Q3, odometry->Q1, road-surface/mesh->Q1/Q5, calibration->Q1, mobile-mapping->Q3/Q7.

## 1. Colour-stage occlusion (Q8): which points are visible from which image

Method inventory: depth buffer/Z-buffer per image (operator choice, Apache-2.0 in-house, decision 38); ray casting/ray tracing; HPR [katz-2007-hpr]; multi-view blending (median of 5 views within 12 m); neural rendering (3DGS/Street Gaussians/DrivingGaussian/OmniRe/EmerNeRF); TSDF/voxel fusion [curless-1996-tsdf].

| Method | Licence | Maturity | Runs on nuScenes | Reported accuracy | Relevance to colour-stage occlusion | Relevance to v1.1 |
|---|---|---|---|---|---|---|
| Depth buffer / Z-buffer per image (in-house, Apache-2.0) | Apache-2.0 | Production (decision 38) | Native (camera poses + lidar points) | not reported in this pass (geometry: per-point visibility, no rendered metric) | Direct: chosen method for Q8 | Baseline for v1.1 cameras-only colouring |
| Ray casting / ray tracing | n/a (technique) | Mature | Adapter (needs poses + mesh/points) | not reported in this pass | Alternative to Z-buffer | Reusable for drone meshes |
| HPR [katz-2007-hpr] | paper (method) | Published (2007) | Adapter (point cloud + viewpoints) | not reported in this pass | Hidden-point removal from viewpoints | Useful for airborne lidar viewpoints |
| Multi-view blending (median of 5 views within 12 m) | in-house | Production | Native | not reported in this pass | Smoothing colour across views | Applies to merging drives |
| 3D Gaussian Splatting [kerbl-2023-3dgs] (base) | non-commercial research (repo [gaussian-splatting-repo]) | Research | Adapter (COLMAP poses) | PSNR/SSIM on held-out views (image quality, not geometry) | Neural rendering of colour, not occlusion logic | Cameras-only v1.1 candidate |
| Street Gaussians [yan-2024-street-gaussians] | Project Registration License 1.0 ([street-gaussians-repo]) | Research | No (paper uses Waymo, KITTI) | PSNR/SSIM (image quality, not geometry) | Dynamic urban scenes | Not on nuScenes |
| DrivingGaussian [zhou-2023-drivinggaussian] | None (no LICENSE; all rights reserved) ([drivinggaussian-repo]) | Research | Yes (paper uses nuScenes) | PSNR/SSIM (image quality, not geometry) | Strongest camera+lidar fit | Licence blocks reuse |
| OmniRe [chen-2024-omnire] | NVIDIA licence, non-commercial ([emernerf-repo] adjacent) | Research | Yes (urban logs) | PSNR/SSIM (image quality, not geometry) | All dynamic objects | Licence blocks reuse |
| EmerNeRF [yang-2023-emernerf] | NVIDIA, non-commercial | Research | Yes | PSNR/SSIM (image quality, not geometry) | Static/dynamic self-supervision | Licence blocks reuse |
| HUGS [zhou-2024-hugs] | custom non-commercial ([hugs-repo]) | Research | RGB-only focus | PSNR/SSIM (image quality, not geometry) | Urban understanding | RGB-only, no lidar prior |
| TSDF/voxel fusion [curless-1996-tsdf] | paper (method) | Mature (1996) | Adapter | volumetric reconstruction error (not PSNR) | Volumetric colour/occupancy fusion | Reusable for fusion |
| gsplat [gsplat-repo] | Apache-2.0 | Production library | Not evaluated here | not reported in this pass | Rendering backend only | Apache-2.0 base for optional viewing layer |

Recommendation for Q8 (E-4 evidence bar: "clearly better, licence-clean method"): option (a) stands on current evidence. Neural methods report PSNR/SSIM (image quality), not geometry accuracy, and all licence-clean candidates either lack nuScenes runs or report no geometry metric. No clearly better, licence-clean method is evidenced.

## 2. Lidar-camera odometry (Q1)

nuScenes has no per-point timestamps (spec section 6). Adapter required for R3LIVE, FAST-LIVO2, LVI-SAM: verify IMU availability and per-point timestamps in nuScenes mini; do not assert "no IMU" without a cited source. [caesar-2019-nuscenes]

| Method | Licence | Maturity | Runs on nuScenes | Reported accuracy | Relevance to colour-stage occlusion | Relevance to v1.1 |
|---|---|---|---|---|---|---|
| R3LIVE [r3live-2021] ([r3live-repo]) | check repo licence (GitHub) | Research | Adapter (IMU + per-point timestamps required) | not reported in this pass | Provides poses for colouring | Pose source for cameras-only |
| FAST-LIVO2 [fast-livo2-repo] | check repo licence | Research | Adapter (IMU + per-point timestamps required) | not reported in this pass | Provides poses | Pose source |
| LVI-SAM [lvi-sam-2021] ([lvi-sam-repo]) | check repo licence | Research | Adapter (IMU + per-point timestamps required) | not reported in this pass | Provides poses | Pose source |
| COLMAP [schonberger-2016-colmap] ([colmap-repo]) | BSD-3-Clause | Mature | Not evaluated here (SfM/MVS from images) | not reported in this pass | Pose + sparse points | Drone/cameras-only base |

## 3. Road-surface / mesh reconstruction (Q1/Q5)

Ticket-named (non-substitutable): RoMe [rome-2024] ([rome-repo]), StreetSurf [streetsurf-2023]. Plus DrivingGaussian, Street Gaussians, EmerNeRF, HUGS, Gaussian Splatting base, gsplat, COLMAP, Metric3D v2, Depth Anything, DUSt3R, VGGT, SurroundDepth.

| Method | Licence | Maturity | Runs on nuScenes | Reported accuracy | Relevance to colour-stage occlusion | Relevance to v1.1 |
|---|---|---|---|---|---|---|
| RoMe [rome-2024] ([rome-repo]) | check repo licence | Research | check source | not reported in this pass | Mesh reconstruction | Road-surface candidate |
| StreetSurf [streetsurf-2023] | check source | Research | check source | not reported in this pass | Street surface modelling | Road-surface candidate |
| DrivingGaussian [zhou-2023-drivinggaussian] | None (all rights reserved) | Research | Yes | PSNR/SSIM (image, not geometry) | Colour + geometry | Licence blocks reuse |
| Street Gaussians [yan-2024-street-gaussians] | Project Registration License 1.0 | Research | No | PSNR/SSIM (image, not geometry) | Dynamic scenes | Not on nuScenes |
| EmerNeRF [yang-2023-emernerf] | NVIDIA non-commercial | Research | Yes | PSNR/SSIM (image, not geometry) | Static/dynamic fields | Licence blocks reuse |
| HUGS [zhou-2024-hugs] | custom non-commercial | Research | RGB-only | PSNR/SSIM (image, not geometry) | Urban understanding | RGB-only |
| 3DGS base [kerbl-2023-3dgs] | non-commercial research | Research | Adapter | PSNR/SSIM (image, not geometry) | Rendering | Viewing layer only |
| gsplat [gsplat-repo] | Apache-2.0 | Production library | Not evaluated | not reported in this pass | Rendering backend | Viewing layer |
| COLMAP [schonberger-2016-colmap] | BSD-3-Clause | Mature | Not evaluated | not reported in this pass | SfM/MVS geometry | Drone/cameras-only |
| Metric3D v2 [hu-2024-metric3d-v2] ([metric3d-repo]) | BSD-2-Clause (repo) | Research | Not evaluated | metric depth (sourced number not verified in this pass) | Metric depth prior | Cameras-only metric reconstruction |
| Depth Anything [yang-2024-depth-anything] ([depth-anything-repo]) | Apache-2.0 | Research | Not evaluated | relative depth only (no metric claim in abstract) | Depth prior | Cameras-only (relative) |
| DUSt3R [wang-2023-dust3r] ([dust3r-repo]) | CC BY-NC-SA 4.0 | Research | Not evaluated | not reported in this pass | Pose-free reconstruction | Licence blocks reuse |
| VGGT [wang-2025-vggt] ([vggt-repo]) | custom licence | Research | Not evaluated | under one second per reconstruction (abstract) | Feed-forward depth/poses | Licence blocks reuse |
| SurroundDepth [wei-2022-surrounddepth] | check source | Research | Not evaluated | not reported in this pass | Surround-camera depth | Cameras-only |
| NeuralSim [neuralsim-repo] | check repo licence | Research | check source | not reported in this pass | Neural simulation | Adjacent |

## 4. Extrinsic / time calibration (Q1)

(a) methods: hand-eye, target-based, motion-based, learning-based; (b) verification checks runnable on nuScenes factory calibration.

| Method | Licence | Maturity | Runs on nuScenes | Reported accuracy | Relevance to colour-stage occlusion | Relevance to v1.1 |
|---|---|---|---|---|---|---|
| Hand-eye (classic) | n/a (method) | Mature | Adapter (factory calibration) | not reported in this pass | Aligns cameras to lidar | All stages |
| Target-based | n/a (method) | Mature | Adapter | not reported in this pass | Board-based extrinsics | All stages |
| Motion-based | n/a (method) | Mature | Adapter | not reported in this pass | Ego-motion calibration | All stages |
| Learning-based | n/a (method) | Research | Adapter | not reported in this pass | Data-driven calibration | Cameras-only |
| Calibration survey [calib-survey-2022] | check source | Review | n/a (survey) | not reported in this pass | Method taxonomy | Method selection |
| Besl & McKay ICP [besl-1992-icp] | check source | Mature (1992) | Adapter | not reported in this pass | Registration verification | Merging drives |

## 5. Mobile mapping for audit-grade accuracy (Q3/Q7)

Survey-grade vs AV-log-grade. The accuracy gap between survey-grade mobile mapping and AV-log-grade reconstruction is unmeasured in this literature.

| Method | Licence | Maturity | Runs on nuScenes | Reported accuracy | Relevance to colour-stage occlusion | Relevance to v1.1 |
|---|---|---|---|---|---|---|
| Leica Pegasus [leica-pegasus-product] | commercial product | Commercial | No (hardware) | not reported in this pass (product page, not evaluation) | Survey-grade reference | Vancouver/audit reference |
| RIEGL mobile scanning [riegl-mobile-scanning-product] | commercial product | Commercial | No (hardware) | not reported in this pass | Survey-grade reference | Audit reference |
| Toronto-3D [tan-2020-toronto3d] | check dataset terms | Dataset | No | not reported in this pass | MLS feature training | Lidar-only features |
| DALES [varney-2020-dales] | check dataset terms | Dataset | No (airborne) | not reported in this pass | Airborne features | Vancouver airborne |
| RandLA-Net [hu-2019-randla-net] ([randla-net-repo]) | CC BY-NC-SA 4.0 | Research | Adapter | not reported in this pass | Point-cloud segmentation | Licence blocks reuse |
| Vancouver airborne lidar [vancouver-lidar-2022] | open data | Dataset | No (airborne, Vancouver) | not reported in this pass | Height-check template | Vancouver lidar-only |

E-3 (spec R1 wording tension, carried verbatim): Vancouver airborne lidar is a methodology/height-check template, not Boston ground truth. The note does not silently contradict the spec; operator to reconcile spec wording separately.

v1.1 merging overlapping drives: pose graph + ICP [besl-1992-icp]; B2F-Map [b2f-map-2026] ([b2f-map-repo]); correspondence-free multiview registration; VRF; MLS+ALS fusion thesis. B2F-Map is a correspondence-free multiview registration method; ICP [besl-1992-icp] is the classical baseline.

v1.1 Vancouver airborne lidar-only: methodology/height-check template only (see E-3 above); drone reconstruction: COLMAP [schonberger-2016-colmap] (BSD-3-Clause) base; cameras-only metric reconstruction: Metric3D v2 [hu-2024-metric3d-v2] + COLMAP poses (see section 3).

## Recommendation

E-4 evidence bar: a reopen of decision 38 requires a "clearly better, licence-clean method". On current evidence, option (a) (depth buffer/Z-buffer per image, Apache-2.0 in-house) stands. Neural rendering methods (3DGS/Street Gaussians/DrivingGaussian/OmniRe/EmerNeRF/HUGS) report PSNR/SSIM, which measure rendered image quality, not geometry accuracy, and carry non-commercial or no-licence terms that block reuse in an Apache-2.0 repo. Licence-clean candidates (gsplat, COLMAP, Metric3D v2, Depth Anything) do not themselves solve occlusion and are supporting components, not replacements. No cited source demonstrates a clearly better, licence-clean colour-stage occlusion method on nuScenes geometry. Option (a) stands. Sources: [katz-2007-hpr], [curless-1996-tsdf], [rome-2024], [streetsurf-2023], [r3live-2021], [lvi-sam-2021], [b2f-map-2026], [calib-survey-2022], [besl-1992-icp], [rome-repo], [neuralsim-repo], [r3live-repo], [fast-livo2-repo], [lvi-sam-repo], [b2f-map-repo], [vancouver-lidar-2022].
EOF
echo done