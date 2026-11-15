# Which 3D Gaussian Splatting implementation (research, issue #176)

Decision: **gsplat 1.5.3 (Apache-2.0)**, used as a library under our own small training loop (`twin/stages/splats.py`). Checked 2026-11-10 to 2026-11-14 against the repositories (licence files and READMEs read, not recalled) and by running it on the box.

Splats are a rendering and a viewing layer (ADR 0006 Q2c). Nothing measured from them goes into the twin's metrics unless the lidar confirms it.

## Comparison

| Candidate | Licence | nuScenes | Lidar init / depth supervision | Pose refinement | 12 GB fit | Verdict |
|---|---|---|---|---|---|---|
| gsplat (nerfstudio-project/gsplat) | Apache-2.0 (repo licence file) | none built in: it is a rasteriser, we feed it nuScenes ourselves | any start points; renders expected depth (`RGB+ED`) for a depth loss; gradients reach the camera pose | yes: view matrices take gradients, so a learnable per-camera correction is a few lines | measured: 1.5 M splats at 800 px peaked at 1.4 GB | **chosen** |
| Inria gaussian-splatting (original 3DGS) | Inria / MPII "Gaussian-Splatting License": research and evaluation use, non-commercial | no | COLMAP points, no depth loss in the base code | no | fits | rejected: non-commercial |
| DrivingGaussian (VDIGPKU) | no licence file; the README says the code is released only after a signed application | nuScenes, Waymo | lidar prior | not stated | not stated | rejected: code not openly available |
| Street Gaussians (zju3dv) | "Project Registration License v1.0": free for research, education, evaluation; commercial use needs registration | Waymo, KITTI (no nuScenes in its README) | lidar init, lidar depth | tracked-pose optimisation for cars | fits | rejected: not permissive, no nuScenes |
| DriveStudio (ziyc/drivestudio, includes OmniRe) | MIT | nuScenes (2 Hz, up to 10 Hz with interpolated boxes), Waymo, others | lidar init, lidar depth, camera pose refinement | yes | not measured | candidate for later: a full dynamic-scene system built on gsplat; far more than the static-ground prototype needs, and its nuScenes loader would sit beside our own load stage |
| 3DGRUT (nv-tlabs) | Apache-2.0 | no | not used | no | not measured | not needed: ray-traced splats for distorted cameras; nuScenes cameras are pinhole |
| mip-splatting | Inria-derived, no SPDX id | no | no | no | fits | rejected: same non-commercial base |

## Why gsplat and our own loop

- Licence: Apache-2.0, the only choice here that is permissive and openly available with the features we need. The torch dependency is BSD-3-Clause.
- Lidar start: we pass the aligned lidar points as the first splats. Ground points become flat discs, so the road is covered from the first step.
- Lidar depth supervision: the loss includes the relative error between the rendered expected depth and the lidar depth projected into each image.
- Pose: dataset poses (ego pose times calibration) plus a clamped learnable correction per camera (ADR 0006 Q3); the correction is reported.
- Orthophoto: gsplat renders an orthographic camera, so the 2-3 cm orthophoto is a top-down render of the ground-layer splats.
- Install note: gsplat 1.5.3 on PyPI is a source wheel; its CUDA kernels compile on first use and need `nvcc` and `g++`. The box has neither, so for this work they were installed in user space from conda-forge and the NVIDIA conda channel (CUDA 12.8) under `/data`. The first call takes about 2.5 minutes to compile, later calls use the cache. Prebuilt gsplat wheels exist only for Python 3.10 and torch up to 2.4, not our Python 3.11 and torch 2.10.

## Known limits of this prototype

- One drive (scene-0757), not the merged area. The stage takes a single run's folders; the area merge produces its own cloud and is not wired to the stage (not in this ticket).
- No dynamic objects: cars and people are masked out of the loss, not reconstructed (DriveStudio or Street Gaussians style handling is a later question).
- Colour has no view dependence (no spherical harmonics), which suits a ground orthophoto and costs some photometric score.
- Held-out images are scored with the dataset pose; the correction learned for a training camera cannot be applied to an image that was not trained.

## Sources

- gsplat: https://github.com/nerfstudio-project/gsplat (Apache-2.0); docs https://docs.gsplat.studio
- 3DGS: Kerbl et al., "3D Gaussian Splatting for Real-Time Radiance Field Rendering", SIGGRAPH 2023; licence at https://github.com/graphdeco-inria/gaussian-splatting/blob/main/LICENSE.md
- DrivingGaussian: Zhou et al., CVPR 2024; https://github.com/VDIGPKU/DrivingGaussian
- Street Gaussians: Yan et al., ECCV 2024; https://github.com/zju3dv/street_gaussians (LICENSE: PRL v1.0)
- DriveStudio / OmniRe: https://github.com/ziyc/drivestudio (MIT)
- 3DGRUT: https://github.com/nv-tlabs/3dgrut (Apache-2.0)
