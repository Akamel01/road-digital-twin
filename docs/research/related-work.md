# Related work: measurable 3D road digital twins

Every source is an entry in [`sources.yaml`](sources.yaml). Citations use the entry id in square brackets. Summaries come from the abstract or the full text named in each entry. Where I read only the title or a search summary, the text says so. Repo facts (stars, licence, last push) come from the GitHub API.

## 1. Cameras + lidar (vehicle-mounted): static scene reconstruction and dynamic-object removal

- **[zhou-2023-drivinggaussian]** splits the scene into a static background built from incremental Gaussians and moving objects handled by a composite graph. LiDAR points replace structure-from-motion points as the starting Gaussians. The experiments use nuScenes and KITTI-360, on 8 RTX 8000 GPUs with 384 GB in total.
- **[yan-2024-street-gaussians]** models a street as a static background plus tracked vehicles, each with its own Gaussians. The paper reports faster training and rendering than NeRF methods. Its experiments use Waymo and KITTI, not nuScenes, on one RTX 4090.
- **[chen-2024-omnire]** builds digital twins from on-device logs and extends dynamic modelling from vehicles to all dynamic objects, such as pedestrians.
- **[yang-2023-emernerf]** separates static and dynamic fields by self-supervision, with no manual labels. It is a neural-field method, not Gaussian splatting.
- **[zhou-2024-hugs]** targets urban scene understanding from RGB images. Its abstract contrasts it with methods that need LiDAR scans or manual 3D boxes.
- **[hess-2024-splatad]** renders camera and lidar data with Gaussian splatting for driving simulation. Its abstract argues that NeRF renderers are too slow for this use.
- **[kerbl-2023-3dgs]** is the base method: 3D Gaussian splatting for real-time radiance-field rendering, published in ACM Transactions on Graphics.
- **[caesar-2019-nuscenes]** is the nuScenes dataset with cameras, lidar and radar from driving logs. It is the test set most of the methods above use.
- **[vechersky-2018-colourising]** colours a lidar map from a loosely coupled camera. It interpolates the trajectory at each image time, tests visibility with hidden point removal, and keeps a robust weighted mean of the colour candidates, weighted towards closer views.
- **[katz-2007-hidden-point-removal]** is the hidden point removal operator: it finds the points visible from a viewpoint without building a surface.
- **[waechter-2014-let-there-be-color]** textures large meshes by choosing one view per face (an MRF with a data term from the projected gradient, which favours close, sharp views) and then adjusting colours globally to hide seams. Its code is [mvs-texturing-repo] (BSD-3-Clause).
- **[gharibi-2018-true-orthophoto]** reviews occlusion detection for true orthophotos (z-buffer, height-based, angle-based). It notes that the z-buffer gives false occlusions when the image GSD and DSM cell size do not match, and mosaics from the closest visible image.

The camera colouring method for v1 is in `docs/research/camera-ground-projection.md` (issue #7).

**What this means for us.** The strongest technical match for v1 is DrivingGaussian: it uses nuScenes and a LiDAR prior, which fits our camera-plus-lidar input. Its repo [drivinggaussian-repo] has no licence file, so the code is all rights reserved and we cannot reuse it. Street Gaussians is the next best fit, but its repo [street-gaussians-repo] uses a registration licence (Project Registration License 1.0) that needs a registration before project use, and its paper does not test on nuScenes. EmerNeRF's NVIDIA licence [emernerf-repo] is non-commercial, so it also cannot go into an Apache-2.0 repo. The 3DGS reference code [gaussian-splatting-repo] is non-commercial research only, and the HUGS code [hugs-repo] carries a custom non-commercial licence. For a measurable layer, none of these is needed in v1. Stacking the lidar sweeps with the dataset's ego poses and masking road users with the annotated 3D boxes [nuscenes-devkit-repo] gives a metric point cloud with no learned model (Claude review, 2026-11-07; EGM review in `docs/reviews/2026-11-07-decisions/`). Gaussian splatting matters only for the cameras-only comparison and an optional viewing layer. If we add it, build on gsplat (Apache-2.0) with COLMAP poses, and use Street Gaussians as a reference that needs a registration decision. The main risk is the licence gap. Most papers do not state per-GPU memory, so the memory budget for the 12 GB box is unverified.

## 2. Cameras only: metric-scale road reconstruction

- **[hu-2024-metric3d-v2]** is a monocular model for zero-shot metric depth and surface normals (IEEE TPAMI, 2024). I read the title and the record only, not the full text.
- **[yang-2024-depth-anything]** is a monocular depth foundation model trained on about 62 million unlabelled images. Its abstract does not claim metric scale.
- **[wang-2023-dust3r]** reconstructs dense 3D from unposed image collections without camera calibration, so it removes the calibration step.
- **[wang-2025-vggt]** is a feed-forward transformer that predicts camera parameters, depth and point maps from one to hundreds of views. The abstract says a reconstruction takes under one second.
- **[wei-2022-surrounddepth]** predicts depth from several surrounding cameras with self-supervision, and presents camera depth as a cheaper option than LiDAR.
- **[guizilini-2021-full-surround]** extends self-supervised monocular depth to wide-baseline multi-camera rigs with a scale-consistent setup.
- **[gruber-2019-pixel-accurate]** is a depth benchmark with high-resolution reference depth (up to 25 arcseconds of angular resolution). It argues that the sparse references in KITTI are too coarse for per-pixel evaluation. The paper's results on camera-versus-lidar error were not checked in full text, so I do not quote them.

**What this means for us.** No source I checked gives a verified accuracy gap between camera-only and lidar-based road reconstruction on the same road. This question is not answered yet. The best candidate for the metric-depth step is Metric3D [metric3d-repo] (repo licence BSD-2-Clause), with COLMAP for poses. Depth Anything [depth-anything-repo] is Apache-2.0 but gives relative depth. DUSt3R [dust3r-repo] is CC BY-NC-SA 4.0, and VGGT [vggt-repo] is under its own custom licence, so neither can go into our repo as is. The risk is scale drift over long runs, which is not measured here. To measure the gap ourselves, use the high-resolution benchmark design in Gruber et al. with nuScenes lidar as reference. Coverage for this question is weak.

## 3. Lidar only: road features from mobile and airborne laser scanning

- **[tan-2020-toronto3d]** is a labelled mobile laser scanning dataset of urban roadways, built for semantic segmentation for driving and HD mapping.
- **[varney-2020-dales]** is an aerial lidar dataset with over half a billion hand-labelled points across 10 km² and eight object classes.
- **[hu-2019-randla-net]** is a segmentation network that uses random point sampling to handle large point clouds cheaply. Its repo [randla-net-repo] licence is CC BY-NC-SA 4.0, so it cannot be used commercially.
- **[yu-2015-road-markings]** learns hierarchical features to extract road markings from 3D mobile lidar. I read the title and record only.
- **[yu-2015-urban-road-facilities]** automatically extracts urban road facilities from mobile laser scanning data. I read the title and record only.
- **[guan-2014-road-markings-mls]** extracts road markings from mobile laser scanning data. I read the title and record only.
- Commercial mobile mapping hardware is covered in the product table. [leica-pegasus-product] pairs five 4 MP cameras with two lidar profilers and SLAM positioning, and [riegl-mobile-scanning-product] sells scanners for the same kind of survey. These are product pages, not evaluations.

**What this means for us.** The lidar-only route has public datasets (Toronto-3D, DALES) that our feature classes could be trained and tested on. RandLA-Net is the reference architecture, but its non-commercial licence means we must reimplement it or pick another model. The three road-feature papers are title-level reads, so I cannot yet say how accurate their feature sets are. Risk: transferring models between mobile and airborne scans, which the sources do not test.

## 4. Drone: road-corridor reconstruction and feature extraction

- **[tan-2019-uav-road-distress]** builds 3D road models from UAV oblique images and detects surface distress from them.
- **[polat-2023-uav-road-roughness]** assesses road roughness from UAV-derived dense point clouds, covering the workflow from sparse to dense point cloud.
- **[uthai-2024-uav-road-surface]** extracts the road surface from UAV-derived dense point clouds with deep learning. I read the title and record only.
- **[schonberger-2016-colmap]** is the COLMAP structure-from-motion pipeline [colmap-repo], the usual first step for drone photogrammetry.
- Commercial photogrammetry: [pix4d-product] turns drone imagery into maps and 3D models, and [bentley-itwin-capture-product] produces reality meshes and point clouds from images and point clouds.

**What this means for us.** Photogrammetry is mature, and COLMAP (BSD-3-Clause, last push 2026-11-07) is the best open-source base for the drone stage. The drone-corridor feature papers focus on distress and roughness, not corridor features such as sidewalks or signs, so drone feature extraction stays a research gap. Risk: depth quality of drone photogrammetry on road edges is not reported in these sources. Drone lidar has no source in this set.

## 5. Vector map extraction: 3D lanes, road edges and HD-map geometry

- **[liu-2022-vectormapnet]** predicts vectorised HD map elements end to end, instead of rasterised segmentation followed by post-processing. Its experiments use nuScenes and Argoverse 2, on 8 GTX 3090 GPUs. The official repo [vectormapnet-repo] has no licence and holds only a README and project page, so the code cannot be reused as is.
- **[liao-2022-maptr]** models each map element as a set of points with equivalent orderings and learns it with a transformer. It is tested on nuScenes, and its repo [maptr-repo] is MIT-licensed. The HDMapNet code [hdmapnet-repo] is GPL-3.0, which is a copyleft licence.
- **[liao-2023-maptrv2]** is the follow-up to MapTR and keeps the same point-set modelling.
- **[li-2021-hdmapnet]** builds semantic HD maps online from onboard sensors and defines its own semantic and instance metrics.
- **[wang-2023-openlane-v2]** is a benchmark for lane topology and traffic-element reasoning in 3D HD mapping. Its code [openlane-v2-repo] is Apache-2.0.
- **[xiong-2023-neural-map-prior]** uses a learned prior map to reduce the sensor-range and occlusion limits of online mapping.
- **[poggenhans-2018-lanelet2]** is the Lanelet2 map framework for storing lanes as geometry and topology. Its repo [lanelet2-repo] is BSD-3-Clause. [autoware-repo] is an Apache-2.0 open-source driving stack that could consume our maps for testing; I did not check its map formats.

**What this means for us.** Our twin is built offline from measured data, so a learned online mapper is only a partial fit. The output format should follow Lanelet2 (BSD-3-Clause), and MapTR's point-set model is the best learned candidate (MIT). The main risk is that these models learn 2D-style map elements from cameras, and none of the papers I read reports a height error. Height is required for the vertical profile, so it must be measured with our own tests.

## 6. Vertical profile and sight distance: stopping and intersection sight distance from point clouds

- **[holgado-barco-2014-vertical-alignment]** extracts the vertical road profile, slope, vertical curves and cross-sections from mobile laser scanning. The pipeline uses segmentation, orthogonal regression and filtering. I read the title, DOI record and a search summary, not the full text.
- **[gonzalez-gomez-2019-sight-distance]** builds a 3D point-cloud model to estimate available sight distance from mobile lidar. Its abstract says the models give accurate 3D road geometry.
- **[jung-2018-virtual-isd]** analyses intersection sight distance in a 3D virtual model built from lidar. I read the title and record only.
- **[gargoum-2021-sight-obstruction]** detects and classifies sight-distance obstructions in lidar data. I read the title and record only.
- **[kilani-2021-urban-isd]** simulates a driver's view at urban intersections from mobile lidar, estimates the blocked share of the view, and links it to collision risk.
- **[ma-2022-urban-visibility]** analyses urban road visibility from mobile laser scanning with deep learning. I read the title and record only.

**What this means for us.** Sight-distance analysis from lidar is a steady line of work (2014–2022), and the Kilani and González-Gómez papers give the clearest method outlines. No open-source code was found for any of them, so the licence is unknown. The vertical-alignment evidence rests on one paper (Holgado-Barco 2014). Coverage for vertical profile is therefore weak, and the next step is to read it in full before choosing a method.

## 7. Digital twins for road safety audits and inspections

- **[ding-2026-road-digital-twin]** builds road digital twins from semantically labelled point clouds (Journal of Intelligent Construction, 2026). I read the title and record only.
- **[gonzalez-gomez-2019-sight-distance]** and **[kilani-2021-urban-isd]** are the sight-distance sources from section 6. They tie a 3D model to a visibility check, which is an audit-type result, but neither paper states an audit procedure.
- Commercial examples: [leica-pegasus-product] and [mapillary-product] (crowdsourced street-level imagery with computer-vision feature extraction, from the help-centre summary).

**What this means for us.** I found no source that combines a 3D road twin with a formal road safety audit, so this is the least-covered question. The audit checklist should come from AuditorAI's stage questions, not from the literature. Risk: no benchmark exists to test a twin against an audit outcome.

## 8. Accuracy evaluation: how a reconstructed road is measured against ground truth

- **[liao-2022-maptr]** reports Chamfer-distance average precision at thresholds {0.5, 1.0, 1.5}. The text does not state the units. These thresholds are matching tolerances, not error levels.
- **[liu-2022-vectormapnet]** uses Chamfer-based average precision with the same kind of thresholds, and adds a Fréchet-based measure that accounts for vertex order.
- **[li-2021-hdmapnet]** defines semantic-level and instance-level metrics.
- **[gruber-2019-pixel-accurate]** sets the reference standard: high-resolution depth ground truth, which measures error more finely than the sparse KITTI references.
- **[caesar-2019-nuscenes]** provides the lidar and map data that the reference can be built from. The devkit [nuscenes-devkit-repo] is Apache-2.0; the dataset terms are a separate question I did not check.

**What this means for us.** The papers I read measure matching quality, not centimetre-level error, so none of them supports our 20 cm target for lane and curb edges. We need our own test: Chamfer distance in plan view against the nuScenes HD map, with the threshold set from the audit checklists. The nuScenes map is 2D, with no elevation, so it cannot measure height error, and it has no curb layer. Curbs need a proxy (the drivable-area or walkway boundary) or another reference, and height needs an independent source such as a survey or a different scan (Claude review, 2026-11-07).

## Strongest open-source candidates for v1

| Candidate | Input type | Licence | Last push (GitHub API) | GPU memory if stated | nuScenes support |
|---|---|---|---|---|---|
| DrivingGaussian [drivinggaussian-repo] | Cameras + lidar prior | None (no LICENSE file; all rights reserved) | 2024-07-25 | 8 RTX 8000, 384 GB total (per GPU not stated) | Yes, in the paper ([zhou-2023-drivinggaussian]) |
| Street Gaussians [street-gaussians-repo] | Cameras (tracked vehicles) | Project Registration License 1.0 (registration before project use) | 2026-09-15 | One RTX 4090; memory not stated | No: paper uses Waymo and KITTI ([yan-2024-street-gaussians]) |
| MapTR [maptr-repo] | Cameras to vector HD map | MIT | 2025-03-03 | RTX 3090 (paper text reads 88, likely 8); memory not stated | Yes ([liao-2022-maptr]) |
| Lidar sweep stacking with nuscenes-devkit [nuscenes-devkit-repo] | Lidar + ego poses + 3D boxes for masking | Apache-2.0 (devkit); nuScenes data CC BY-NC-SA 4.0 | see sources.yaml | Not needed (CPU) | Yes (native) |
| COLMAP [colmap-repo] | Drone and camera images (SfM and MVS) | BSD-3-Clause | 2026-11-07 | Not stated | Not evaluated here |
| gsplat [gsplat-repo] | Rendering library for Gaussian splats | Apache-2.0 | 2026-09-19 | Not stated | Not evaluated here |

Weakest coverage: vertical profile (section 6, one paper), camera-only accuracy versus lidar (section 2, no quantitative source), and digital twins for audits (section 7, no direct source).

## 9. Sight-line target heights (issue #15)

- **[aashto-green-book-2018]** is the primary standard for sight-distance eye/object heights (ch.3 stopping/passing/decision; ch.9 intersections); paywalled, values confirmed via secondary summaries.
- **[nchrp-383]** (Harwood et al., 1996) is the TRID-listed basis (trid.trb.org/view/481444) for the ISD cases (A–F) and the 1.08 m / 1.08 m passenger-car eye/object heights adopted by the 2001/2018 Green Book and FHWA IDRM; not open access.
- **[aashto-bike-guide]** gives cyclist eye height 1.4 m (4.5 ft) and object height 0.0 m for bicycle facilities.
- **[fhwa-idrm-2003]** documents the IDRM ISD model with h1 = h2 = 1080 mm.
- **[nchrp-15-75]** (not adopted) proposes raising the passenger-car eye height to 3.75 ft (1.14 m); not current standard, not adopted for v1.
- **[ohio-dot-ldm]** is a secondary state-DOT summary confirming 3.5 ft eye / 2.0 ft object for SSD and 3.5 ft / 3.5 ft for ISD and PSD.
- **[iowa-sudas]** is a secondary summary confirming the same height values.
- **[dmrb-cd-109]** (CD 109 §3.1) defines SSD as measured from driver eye heights 1.05–2.00 m to object heights 0.26–2.00 m; no pedestrian- or child-specific object height is defined (envelope only).
- **[manual-for-streets]** (MfS visibility splay) uses a vertical envelope of driver eye 1.05–2.00 m to object height 0.6–2.00 m; no pedestrian- or child-specific object height is defined.
- **[tac-gdg-2017]** (§2.5.2.1) defines vehicle object heights (0.38/1.08/1.15/1.30 m by context); no pedestrian- or child-specific object height is defined.
- No standard checks ISD at night using a headlight target: headlight sag-curve values (0.5–0.6 m, 1° upward divergence) are for vertical (sag) curve design only, not an ISD target.
