# State of the art in multi-sensor road reconstruction (issue #13)

Part of #3. It decides the colour-stage occlusion method (#8, Q8; decision 38) and the multi-sensor direction for v1.1. Researched 2026-11-07 and 2026-11-08.

Source ids in `[brackets]` are entries in [`sources.yaml`](sources.yaml), and each one is cited in [`related-work.md`](related-work.md) section 10 or earlier. Licences and last-commit dates come from the GitHub API (default branch, 2026-11-08). Numbers are copied from the full text of each paper unless a cell says "abstract only". If a paper gives a metric without units, this note says so; it does not guess them.

## Answer

**Q8, colour-stage occlusion for v1: keep decision 38 (option a).** Use a depth buffer per image, rendered from all lidar points plus the annotated boxes at the image time.
- **No better method found.** I found no method that is clearly better for our case and licence-clean. Nobody reports colour or edge-offset accuracy for any visibility method on nuScenes-like data. The only measured colour-registration numbers come from Yamakawa et al.: mean misregistration fell from 11.1 to 5.55 px and from 16.3 to 8.1 px after edge-based correction [yamakawa-2016-mms-colour]. Those measure calibration error, not occlusion error.
- **Hidden point removal (HPR)** [katz-2007-hidden-point-removal] answers a different question: which *points* face the camera. It cannot see occluders that are not in the cloud. Our moving road users were masked out of the cloud but are still in the photos, so the boxes have to be drawn into the occlusion test. A depth buffer takes boxes directly. HPR also assumes fairly even point density, which a 32-beam drive does not have ([biasutti-2019-visibility], abstract).
- **Ray casting** [open3d-repo] gives the same answer as a depth buffer against a surface. It needs a mesh, and it costs one ray per pixel or point instead of one splat per point. It is the same test, so it is a future implementation choice, not a different method.
- **Neural and Gaussian methods** do not decide visibility at all, and most have no licence or a non-commercial one (section 3).
- **Patent note.** Topcon holds an active US patent on a depth-comparison occlusion check for mobile-mapping colourisation, with an estimated expiry in 2039 [morikawa-2020-topcon-colour-patent]. The depth buffer is decades older than that patent, and v1 is a non-commercial research demo. Even so, the operator should know about it before any commercial use. This is not legal advice.

**v1.1 multi-sensor direction: keep KISS-ICP for geometry plus the colour stage. Add one calibration tool and keep one odometry benchmark.**
1. **Calibration check: build on koide3's `direct_visual_lidar_calibration`** [koide-2023-dvlc] [dvlc-repo] (MIT, ROS1/ROS2, last commit 2026-01-02).
   - It reports 4.3 cm and 0.374° from a single shot, against survey-target pseudo ground truth.
   - Use it to verify or refine the six nuScenes camera extrinsics, seeded from the dataset calibration.
   - Skip its SuperGlue initial guess: that code is licensed for non-commercial research only [superglue-repo].
   - Add a Levinson-Thrun style edge-alignment score as a continuous check [levinson-2013-online-calibration]. That paper detected miscalibrations of 0.25° or 10 cm within a 9-frame window and never misclassified one.
2. **Odometry benchmark, not a dependency: FAST-LIVO2** [zheng-2024-fast-livo2] [fast-livo2-repo] (GPL-2.0, last commit 2026-03-08).
   - It reports the best accuracy in this survey: 0.044 m mean ATE RMSE across NTU-VIRAL and Hilti, against motion-capture, total-station or Hilti-scored references.
   - Run it as a separate process on data that has a real, synchronised IMU (our own rig, or a dataset other than nuScenes). Measure KISS-ICP plus colour against it.
   - Don't link it into the Apache-2.0 code.
   - On nuScenes it needs an adapter, and nuScenes poses are already lidar-localised to ≤ 10 cm [caesar-2019-nuscenes]. A tightly coupled lidar-camera-IMU odometry would therefore add risk and gain little there.

## nuScenes constraints that decide "runs on nuScenes"

- **IMU.** nuScenes has no IMU in the sensor tables. The separate CAN bus expansion has an IMU at 100 Hz, with `linear_accel` and `rotation_rate`, and the ego pose at 50 Hz [nuscenes-can-bus]. The README does not say how CAN time aligns with the sensor timestamps. I have not checked that the expansion is on the box.
- **Lidar.** One 32-beam sweep at 20 Hz. Sweeps are already motion-compensated, and there are no per-point timestamps (spec section 6; [camera-ground-projection](camera-ground-projection.md)).
- **Cameras.** Six cameras at 12 Hz, global shutter, images already undistorted. Each camera is triggered when the lidar sweeps across its centre, so camera and lidar times are related but not equal [caesar-2019-nuscenes].
- **Calibration.** Lidar extrinsics were measured with a laser liner; camera extrinsics come from a cube-shaped three-plane target. Calibration was updated about twice a week. **No calibration accuracy figure is published** (nuScenes paper, appendix A) [caesar-2019-nuscenes].

So "adapter" below means: write the sweeps, images and CAN IMU into the framework's input format (usually a ROS bag), and accept that deskewing and IMU-lidar sync cannot be checked.

## 1. Lidar-camera(-IMU) odometry and mapping

| Method | What it does; inputs | IMU needed | Licence | Last commit | Runs on nuScenes | Reported accuracy (reference) |
|---|---|---|---|---|---|---|
| R3LIVE [lin-2021-r3live] [r3live-repo] | FAST-LIO lidar-inertial geometry plus a visual-inertial stage that colours map points by frame-to-map photometric error. Estimates the camera-IMU extrinsic and time offset online. Ships offline mesh and texture tools. | Yes | GPL-2.0; README: free for personal and academic use only | 2022-08-24 (last push 2025-12-04) | Adapter. Needs IMU, and its README says spinning lidars need front-end code changes. Not tested on nuScenes. | Return-to-start drift 0.093–0.164 m and 0.285–3.925° on four 1.2–1.5 km HKUST loops (ArUco board). Relative error at 300 m: 0.14–0.23 % translation and 0.21–0.25° rotation against D-GPS RTK. |
| R3LIVE++ [lin-2022-r3live-plus] | R3LIVE plus photometric calibration and online exposure-time estimation. | Yes | Same repo as R3LIVE | as above | Adapter (as R3LIVE). | NCLT, 25 sequences: mean absolute position error 8.51 m (FAST-LIO2 9.59 m, LVI-SAM 15.03 m). Colour: mean photometric error 18.01 vs 23.58 for R3LIVE, units not stated. Exposure-time error 3.460 ms on one sequence. |
| FAST-LIVO [zheng-2022-fast-livo] [fast-livo-repo] | Sparse-direct lidar-inertial-visual odometry. Extrinsics are pre-calibrated and time offsets known; the authors' rig is hardware-triggered at 10 Hz. | Yes | GPL-2.0 | 2025-09-12 | Adapter. Needs IMU and known lidar-camera offsets. Not tested on nuScenes. | NTU-VIRAL ATE RMSE 0.17–0.29 m per sequence. Own data: 0.05 m and 0.04 m end-to-end drift. |
| FAST-LIVO2 [zheng-2024-fast-livo2] [fast-livo2-repo] | Direct LIVO with sequential updates. Estimates exposure online; extrinsics and time offsets must be known. Feeds meshing and 3DGS. | Yes | GPL-2.0; README: contact the author for a commercial licence | 2026-03-08 | Adapter. Needs IMU and known offsets. Not tested on nuScenes. | Mean ATE RMSE 0.044 m on 25 NTU-VIRAL and Hilti sequences (next best, FAST-LIVO: 0.137 m). References: motion capture or total station; Hilti scored by its website. Map accuracy: no number, only a < 0.01 m return-to-start error. The paper notes drift over long distances. |
| LVI-SAM [shan-2021-lvi-sam] [lvi-sam-repo] | Factor graph that couples a lidar-inertial and a visual-inertial subsystem. The lidar-inertial side initialises the visual side. | Yes | BSD-3-Clause | 2022-12-17 (inactive) | Adapter. Needs IMU. Not tested on nuScenes. | Against Reach RS+ GPS: RMSE 0.67 m (Jackal) and 0.83 m (handheld) with loop closure, 4.05 m and 7.87 m without. Fails on 9 sequences in the FAST-LIVO2 benchmark. |
| SR-LIVO [yuan-2023-sr-livo] [sr-livo-repo] | Rebuilds lidar sweeps so that each ends at an image time; the camera only colours the map. | Yes | GPL-2.0 | 2025-02-21 | No. Sweep reconstruction needs raw per-point timing, which nuScenes does not ship. | NTU-VIRAL ATE RMSE 0.12–0.23 m (laser-tracker ground truth). R3LIVE sequences: end-to-end error 0.021–0.546 m. |
| Coco-LIC [lang-2023-coco-lic] [coco-lic-repo] | Continuous-time B-spline lidar-inertial-camera odometry. | Yes | None (no LICENSE file; all rights reserved) | 2026-02-21 | Adapter, but the licence blocks reuse. | UrbanNav, the closest match to a car with a 32-beam lidar (HDL-32E): APE RMSE 2.189–6.031 m over 3.0–4.5 km, loop closure off. The paper does not state the ground-truth source for UrbanNav. Lidar-inertial only, against motion capture: 0.011–0.100 m. |
| Gaussian-LIC [lang-2024-gaussian-lic] [gaussian-lic-repo] | Coco-LIC tracking plus a 3D Gaussian map from coloured lidar points. | Yes | None (all rights reserved) | 2026-08-08 | Adapter, but the licence blocks reuse. | BotanicGarden APE RMSE 0.252 and 0.461 (units not stated). PSNR 18.6–29.5 on training views. No geometric map accuracy. |
| KISS-ICP (our align, [kiss-icp-fit](kiss-icp-fit.md)) | Lidar-only ICP odometry. | No | MIT | 2026-05-04 | **Yes.** It has its own nuScenes loader. | See kiss-icp-fit.md. |

**What this means.** Every lidar-camera framework here needs an IMU and was tested on handheld, drone or campus rigs. None was tested on nuScenes, and only FAST-LIVO2 and SR-LIVO report ATE against an external reference. None reports map accuracy as point-to-reference distance. So we can't say from the literature that any of them would make our twin more accurate than KISS-ICP on nuScenes.

## 2. Point-cloud colouring and occlusion handling

| Method | What it does | Licence / code | Runs on nuScenes | Reported accuracy |
|---|---|---|---|---|
| Depth buffer (z-buffer) per image with boxes (decision 38; [camera-ground-projection](camera-ground-projection.md)) | Splats all points into a depth image per camera and rasterises the 3D boxes at the image time. A sample is visible if it is no deeper than the buffer plus a tolerance. Reviewed for true orthophotos in [gharibi-2018-true-orthophoto]. | Our own code (Apache-2.0) | **Yes.** It uses only devkit poses, calibration and boxes. | No published colour accuracy. Our `colour/qa.json` edge offset will be the first measurement. Gharibi notes false visibility or false occlusion when the image GSD and the cell size do not match. |
| Hidden point removal [katz-2007-hidden-point-removal], in [open3d-repo] (`hidden_point_removal`) | Spherical flip plus convex hull; returns the points visible from one viewpoint. Used in [vechersky-2018-colourising] and inside [koide-2023-dvlc]. | Open3D MIT | Adapter. It runs on our points, but the boxes would need to be sampled into points. | The Katz paper is not open access, and I did not read its full text. Biasutti et al. report that methods assuming uniform density give low-quality visibility on mobile-mapping lidar (abstract; the full text was blocked by a bot wall) [biasutti-2019-visibility]. |
| Screen-space visibility for variable density [biasutti-2019-visibility] | Decides visibility from each point's screen-space neighbourhood; no assumption about density. | No code found | Adapter (pure point cloud) | Scored against a hand-annotated mobile-mapping set, the authors say; numbers not read (full text blocked). |
| Ray casting, Open3D `RaycastingScene` [open3d-repo] | One ray per pixel or point against a mesh. | MIT | Adapter (needs a ground mesh) | It is a geometric test, so no accuracy figure applies; the result matches a depth buffer on the same surface. |
| R3LIVE / R3LIVE++ map colouring [lin-2022-r3live-plus] | Bayesian per-point colour update from the tracked images, inside the odometry. | GPL-2.0 | Adapter (needs the whole R3LIVE pipeline) | Mean photometric error 18.01, units not stated. No occlusion test beyond the map projection is described in what I read. |
| Edge-based colour correction [yamakawa-2016-mms-colour] | Matches edges in lidar-intensity images to RGB edges to fix colour misregistration. | No code | Adapter | Mean error from 11.1 to 5.55 px and from 16.3 to 8.1 px. |
| mvs-texturing [waechter-2014-let-there-be-color] [mvs-texturing-repo] | Picks one view per mesh face with an MRF, then adjusts colour globally to hide seams. | BSD-3-Clause, last commit 2026-03-11 | Adapter (needs a mesh) | No geometric accuracy; it is a texturing method. |
| Moving objects: boxes (v1) and ERASOR [lim-2021-erasor] [erasor-repo] | v1 drops all annotated box pixels in every image (#8 round 1). ERASOR removes dynamic points from accumulated lidar maps without labels. | ERASOR GPL-3.0 | Boxes: yes. ERASOR: adapter. | ERASOR, SemanticKITTI: preservation rate 87.7–94.0 % and rejection rate 95.4–99.3 % (0.2 voxels). |

## 3. Road-surface and mesh reconstruction from vehicle logs

"Measurable geometry" here means the paper reports a distance error of the reconstructed surface against an independent reference, with units.

| Method | Inputs | Licence | Last commit | Runs on nuScenes | Measurable geometry with stated error? |
|---|---|---|---|---|---|
| RoMe [mei-2024-rome] [rome-repo] | Images, poses (ORB-SLAM2 or COLMAP) and Mask2Former semantics. Lidar is used only for evaluation. Optimises extrinsics. | MIT | 2025-01-19 | **Yes:** 100 random nuScenes scenes in the paper, with a nuScenes loader in the repo. | **Partly.** Against lidar: Chamfer distance 1.33 and RMSE 1.03, against 15.93 and 6.98 for F2-NeRF. **Units not stated.** The authors note that a higher PSNR does not mean better geometry (PSNR 24.36 with CD 5.77). |
| EMIE-MAP [wu-2024-emie-map] | Surround-view video plus a trajectory. An explicit mesh with an elevation MLP; lidar is optional elevation supervision. | No code found (arXiv page has no link) | — | No: KITTI odometry seq. 09 and the authors' own 128-beam vehicle. | **Yes, in cm.** Elevation error is the mean distance from lidar ground points to the surface. City street: 2.35 cm with lidar supervision and 17.08 cm without. Night: 3.57 and 27.34 cm. Ramp: 4.33 and 93.12 cm. KITTI without lidar: 28.12 cm. RoMe on the same scenes: 45.08, 331.23, 496.24 and 107.98 cm. The lidar-supervised numbers are scored against the same lidar that supervised them, so they are not independent. |
| StreetSurf [guo-2023-streetsurf] [neuralsim-repo] | Posed images, with lidar or monocular cues as supervision. | MIT | 2024-03-14 | Adapter. The paper uses 32 Waymo sequences only; the neuralsim README ticks a nuScenes dataloader. | **Partly.** Against lidar, with 1 dense + 4 sparse lidars: Chamfer distance 0.19 and depth RMSE 1.44. With 4 sparse lidars: 0.90 and 3.04. Without lidar: RMSE 3.35. **Units not stated.** |
| Urban Radiance Fields [rematas-2022-urban-radiance-fields] | Street View Trekker panoramas plus lidar (depth and line-of-sight losses). | No code (only a project-page repo) | — | No: no code. | **Yes, coarse.** Held-out views: mean depth error 0.463 m, 74.2 % of rays within 0.1 m, F-score 0.880 at 0.1 m (reference: held-out lidar). |
| S-NeRF [xie-2023-s-nerf] [s-nerf-repo] | Images plus densified lidar depth with learned confidence. | MIT | 2026-10-24 | **Yes:** the paper uses nuScenes and Waymo. It notes that nuScenes' 32-beam lidar is too sparse for depth completion. | **No.** It reports a depth "error rate" against its own inputs and no ground-truth geometric error on nuScenes or Waymo. |
| Street Gaussians [yan-2024-street-gaussians] [street-gaussians-repo] | Images, tracked boxes, and lidar for initialisation and an L1 depth loss. | Project Registration License 1.0 | 2026-09-15 (last push) | No: Waymo, KITTI and vKITTI2. Adapter needed. | **No.** PSNR, SSIM and LPIPS only. |
| HUGS [zhou-2024-hugs] [hugs-repo] | Posed RGB only; lidar used only for evaluation. | Custom non-commercial | see sources.yaml | No: KITTI, KITTI-360 and vKITTI2. | **Partly.** KITTI-360: accuracy 0.233 and completeness 0.214 against lidar. Units not stated. |
| DrivingGaussian [zhou-2023-drivinggaussian] [drivinggaussian-repo] | Images plus a lidar prior. | None (all rights reserved) | 2024-07-25 | Yes (paper) | No. Image metrics only (related-work section 1). |

**What this means.**
- **Errors with units.** Two papers give geometric error in units. EMIE-MAP reports elevation error in cm. Urban Radiance Fields reports 0.46 m depth error on held-out views, far from survey grade.
- **Errors without units.** RoMe, StreetSurf and HUGS give lidar-referenced errors with no units, so we can't compare them with our 20 cm feature target. The rest report appearance only.
- **RoMe on someone else's data.** In EMIE-MAP's tests, RoMe's elevation error is 0.45–5 m. A road surface from cameras alone is not yet measurable geometry.
- **Lidar-supervised errors.** EMIE-MAP's 2–4 cm with lidar is scored against the same lidar that supervised it. It shows the surface agrees with the lidar; it is not an independent accuracy.
- **For v1.1.** RoMe is the one licence-clean (MIT) road-surface method that already runs on nuScenes. It is the natural cameras-only comparison for v1.1, but only after we score it ourselves in metres against our lidar ground surface.

## 4. Online extrinsic and time calibration checks

| Tool | What it does | Licence / code | Runs on nuScenes | Reported accuracy (reference) |
|---|---|---|---|---|
| Levinson & Thrun 2013 [levinson-2013-online-calibration] | Scores how well lidar depth edges land on image edges. A grid of 729 perturbations around the current calibration tells whether it is right, and greedy ascent tracks drift. | Paper only; no code | Adapter. The method needs only images, sweeps and poses, all present. | With a 9-frame window (under 1 s at 10 Hz), it never misclassified a calibration when the error was at least 0.25° or 10 cm. About 0.1° errors were detected more than 90 % of the time. Tracking: mean error 0.06° in yaw and 0.12° in roll and pitch. Velodyne HDL-64E with a Ladybug3 camera; the reference was synthetic perturbations. |
| direct_visual_lidar_calibration [koide-2023-dvlc] [dvlc-repo] | Targetless calibration: normalised information distance between lidar intensity and image, with HPR. Spinning lidars are densified by accumulating scans. | MIT (README); optional SuperGlue is non-commercial [superglue-repo] | Adapter. Accumulate sweeps with our poses and seed from the dataset calibration. | Single shot: 0.043 m and 0.374° (Ouster plus pinhole camera). Multi-shot: 0.010–0.082 m and 0.132–0.425°. The paper's text and Table IV disagree on which pairing gave 0.010 m. Reference: pseudo ground truth from survey-grade sphere targets. |
| OpenCalib [yan-2022-opencalib] [opencalib-repo] | Manual, target-based and targetless (lane lines and poles) lidar-camera tools. Online tools cover camera-IMU and lidar-IMU only. | Apache-2.0; last commit 2024-06-17 | Adapter | **No numerical lidar-camera accuracy**; only visual overlays. No lidar-camera time-sync tool. |
| [livox_camera_calib](https://github.com/hku-mars/livox_camera_calib) (hku-mars; paper arXiv 2103.01627, not read) | Edge-based targetless calibration for high-resolution lidars. | GPL-2.0 (GitHub API) | No. The README names only Livox Avia and Horizon, which are dense non-repetitive scanners. | The README claims pixel-level accuracy and gives no numbers. |
| Time offset | R3LIVE and R3LIVE++ estimate the camera-IMU offset online [lin-2021-r3live]. FAST-LIVO2 assumes it is known. nuScenes ties each image to the lidar sweep by trigger, so the offset is known by design. | — | — | No lidar-camera time-offset accuracy is published for nuScenes. The edge-offset QA in `colour/qa.json` is where a time error would show up. |

## 5. Mobile-mapping practice: how survey-grade accuracy is stated

| Source | What it states |
|---|---|
| Leica Pegasus TRK [leica-pegasus-trk-sheet] | Absolute accuracy in [X,Y], [Z] after post-processing: **TRK Neo and TRK Evo 11 mm, 11 mm** with no GNSS outage and 14 mm, 16 mm with a 60 s outage. TRK100: 19 mm, 11 mm and 39 mm, 16 mm. RTK: 12 mm, 12 mm for Neo and Evo; 21 mm, 13 mm for TRK100. The TRK100 datasheet footnote defines this as "One sigma with DMI on Leica Geosystems reference area". No relative accuracy is stated. |
| RIEGL VMX-2HA [riegl-vmx-2ha-brochure] | Scanner: 5 mm accuracy and 3 mm precision, one sigma at 30 m under RIEGL test conditions. IMU/GNSS (AP+60): absolute position **typ. 0.02 m horizontal, 0.03 m vertical**; roll and pitch 0.0025°, heading 0.015°. RMS, post-processed with base-station data, no GNSS outages, with DMI. |
| ASPRS Positional Accuracy Standards, Edition 2 [asprs-positional-accuracy-ed2] | Accuracy is reported as RMSE; the 95 % confidence figure is dropped. Checkpoints: at least 30, at most 120. The checkpoint survey error must be included in the product accuracy. Adds three-dimensional positional accuracy. |
| USGS 3DEP quality levels [usgs-3dep-quality-levels] | Vertical RMSEz: QL0 5 cm, QL1 10 cm, QL2 10 cm, QL3 20 cm. These are airborne-lidar levels; they are useful as a vocabulary, not as a mobile-mapping requirement. |
| NCHRP Report 748 [nchrp-748] | Mobile-lidar guidelines for DOTs. They define data-collection categories that pair accuracy with point density. The PDF returned HTTP 500 twice, so I quote no thresholds. |

**What this means.** Survey-grade systems quote absolute accuracy of 1–3 cm, at one sigma or RMS, under the vendor's best conditions (no GNSS outage, DMI, base station). Agencies then verify with at least 30 independent checkpoints under ASPRS Edition 2. Our twin can't make that claim. nuScenes localisation is "≤ 10 cm" with no ground truth [caesar-2019-nuscenes], and we have no checkpoints. The honest v1 statement stays as it is: relative consistency (`height_valid`), plan error against the HD map as P50/P95, and the label "indeterminate" where there is no reference. If we report accuracy, it should be RMSE against independent checkpoints, in ASPRS vocabulary, which is the v1.1 Vancouver check (spec R1).

## Recommendation (detail)

**v1, Q8.** Keep the per-image depth buffer with all points plus boxes (decision 38, option a). In plain words: draw everything that can block the view, including the cars we removed from the cloud, into a depth picture per camera. A ground sample takes colour from that camera only if nothing in the picture is closer. It is the only option that handles the removed road users directly, it runs on nuScenes as it is, and it is our own Apache-2.0 code. The colour QA (edge offset, P95) is our accuracy evidence, since no paper gives one. Keep HPR in mind only as a fallback if the depth-buffer holes (`zbuf_scale`) cause false visibility; it would need box surfaces sampled as points.

**v1.1.** Keep KISS-ICP plus the colour stage as the production path, and add:
1. **Calibration verification** with koide3's tool (MIT) seeded from the nuScenes calibration, plus a Levinson-Thrun edge score in QA. This is the cheapest way to turn "calibration accuracy not published" into a measured number per camera.
2. **FAST-LIVO2 as the external benchmark** (GPL-2.0, run as a separate program) on a dataset with a synchronised IMU, to measure what tight lidar-camera-IMU coupling would add. Adopt it only if it beats KISS-ICP by more than our error budget there.
3. **RoMe (MIT)** as the cameras-only road-surface comparison on nuScenes, scored in metres against our lidar ground.
4. **ERASOR-style dynamic removal** for future logs without 3D boxes. It is GPL-3.0, so reimplement it or run it as a separate program.

## Uncertainty and gaps

- The Katz HPR and Biasutti full texts were not read: Katz is paywalled, and the HAL and SciTePress copies were blocked or too large. No visibility method's colour or edge accuracy is known.
- Several key numbers have no units in their papers: the RoMe and StreetSurf Chamfer and RMSE values, HUGS, and the Gaussian-LIC APE.
- The NCHRP 748 thresholds were not retrieved.
- CAN bus IMU time alignment and its presence on the box were not checked.
- The Topcon patent's scope is reported from the Google Patents summary and is not a legal reading.
