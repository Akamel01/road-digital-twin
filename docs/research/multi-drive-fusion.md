# Multi-drive fusion for nuScenes intersections (issue #419)

Part of map #415. Question: which way of fusing several drives fits nuScenes intersections: MTGS, NVlabs 3DGM/EnvGS, or a per-drive static layer merged after alignment? Researched 2026-11-22.

Each claim is tagged:
- **[C]** confirmed against a primary source (repo file, GitHub API, paper full text, or our own box data).
- **[U]** unverified: an abstract only, a search result, or my own inference.

Repo facts come from the GitHub API and shallow clones taken on 2026-11-22.

## Answer

1. **3DGM/EnvGS is out.**
   - NVlabs/3DGM holds a README and teaser images only. There is no code and no licence [C].
   - Three issues ask for a code release timeline, and none has a reply [C].
   - It is camera-only and gets its poses from COLMAP, so it would discard our LiDAR and metric poses [C].
2. **MTGS has the right model but cannot run as-is on our box.**
   - It is Apache-2.0 and was last pushed 2026-01-29 [C].
   - Its install guide says "at least 40 GB of GPU memory and 64 GB of RAM" [C]. The box has 12 GB.
   - Its preprocessing is tied to nuPlan and nuplan-devkit [C].
   - Its training side reads one documented pickle (`video_scene_dict.pkl`). A nuScenes adapter therefore means writing that pickle, not porting the pipeline [C].
   - It does not depend on drivestudio. The README only credits drivestudio, and no code imports it [C].
3. **Per-drive layers merged after alignment** cost the least and fit in 12 GB, but they give up what multi-traversal training buys.
   - That gain is shared geometry: MTGS reports +46.3% geometry accuracy over single-traversal baselines [C].
   - It is also the only option where appearance seams between drives are left for us to solve [U, inference].
4. **Recommendation for the spike (#421):** fuse one overlap group of `site-a1-signal` (group B below) in two ways.
   - **Primary:** MTGS's static model fed by a nuScenes pickle adapter, at reduced resolution and with a capped Gaussian count so it fits in 12 GB. Use our own aligned poses and skip MTGS's nuPlan registration scripts.
   - **Baseline:** per-drive OmniRe static layers, merged after alignment.
   - If MTGS's Python 3.9 / torch 2.0.1 / CUDA 11.8 stack will not build on the box, port its two appearance pieces (described below) into drivestudio instead. drivestudio is MIT and reads nuScenes natively.
   - This plan is [U]. It is a recommendation, not a measurement.
5. **No 2025–2026 method fuses multiple traversals and supports nuScenes with released code.** The closest are listed in the last section.

## Comparison

| | MTGS | 3DGM / EnvGS | Per-drive static layer, merged |
|---|---|---|---|
| Code | Released 2025-05-27; last commit 2026-01-29 ("auto reconstruction pipeline for nuPlan"); 175 stars [C] | None: README and teaser only; last push 2024-09-29 [C] | Ours to write. Per-drive training uses OmniRe (drivestudio) or SplatAD [C, #415 notes] |
| Licence | Apache-2.0 for the code; the released data is CC-BY-NC-SA 4.0 (nuPlan-derived) [C] | None (GitHub reports no licence) [C] | drivestudio MIT [C]; SplatAD/neurad-studio Apache-2.0 [#415 notes] |
| Paper | arXiv 2503.12552 (v3) | arXiv 2405.17187, NeurIPS 2024 | n/a |
| Inputs | Multi-camera images with poses and intrinsics; colourised LiDAR for init and depth loss; 3D boxes to initialise transient/rigid nodes; UniDepth pseudo-depth; Mask2Former semantic masks [C, paper + `mtgs/config/MTGS.py`] | RGB video only; "LiDAR-free"; poses from COLMAP SfM [C, paper] | Whatever the per-drive method needs (OmniRe: images, LiDAR, poses, boxes) [C, drivestudio] |
| Appearance across drives | Shared geometry and shared SH DC colour. Per-traversal higher-order SH residuals (`features_rest` per traversal). A per-Gaussian, per-traversal DC adapter exists but has learning rate 0.0 in the shipped config. A per-image 3×4 affine colour transform. Novel traversals use the nearest training traversal's appearance [C, code + paper] | No dedicated appearance model. Robust loss on DINOv2 features treats changed pixels as outliers. Assumes consistent weather and lighting [C, paper] | Each drive has its own appearance. Seams wherever two layers meet unless we normalise colour after the merge [U, inference] |
| Pose assumption / refinement | Calls nuPlan cross-traversal localisation "imprecise" (no number). Re-registers all traversals jointly with a customised KISS-ICP. Drops a traversal if ICP differs from the log pose by >1.0 m at either end or >0.5 m on average. Optional COLMAP BA/triangulation. Then trains a SO3×R3 camera optimiser (lr 1e-4 → 5e-7) [C, code + paper] | Poses from SfM, used as given; the paper says nothing about refining them [C, paper] | No joint refinement. The merge is only as good as our cross-drive alignment (#252) [C, our qa.json below] |
| Effect of pose steps (MTGS Table 6, novel-view PSNR*) | 19.43 with no registration, 20.79 with registration, 20.83 with registration plus camera optimiser [C] | n/a | n/a |
| Datasets evaluated | nuPlan only: 6 road blocks in Boston, Singapore and Pittsburgh, 3–6 traversals each [C, paper] | Ithaca365 and nuPlan (Las Vegas); no nuScenes [C, paper] | n/a |
| Memory / time | Install guide: ≥ 40 GB GPU, 64 GB RAM. 30k iterations by default. The paper reports no GPU type, time or Gaussian count [C] | One RTX 3090. Segmentation takes about 8 min for 1,000 images from 10 traversals. EnvGS time and memory are not reported [C, paper] | Same as one single-drive run, repeated once per drive and run one after another. Our gsplat prototype peaked at 2.27 GB [C, `gaussian-splats.md`]. OmniRe on nuScenes: not measured |
| Cost per added drive | Not reported. From the code, each traversal adds 48 floats per Gaussian (45 SH-rest + 3 adapter), i.e. 192 B, or about 768 B with gradient and Adam state. At 3 M Gaussians that is about 2.3 GB per drive. Transient nodes and images also grow with each drive [U, derived from code] | Not reported. Segmentation IoU rises 15% → 42% → 47% → 54% → 56% from 1 to 10 traversals [C, paper] | Training time grows linearly with drives. Merged splat size grows linearly too, unless overlapping cells are culled [U, inference] |
| nuScenes adapter effort | See next section | Not applicable (no code) | Low: drivestudio already loads nuScenes [C] |

## MTGS on nuScenes: what the adapter has to do

From the code at commit `main` on 2026-11-22 [C]:

- **Training does not need nuplan-devkit.**
  - `mtgs/` has about 13k lines.
  - Its only links to the preprocessing package are `nuplan_scripts.utils` helpers: config, `VideoScene` pickle tools, constants, and the Cityscapes label map.
  - The dataparser (`mtgs/dataset/nuplan_dataparser.py`) reads `video_scene_dict.pkl`, whose schema is documented in `docs/prepare_dataset.md`. Per frame it holds:
    - `ego2global` and `lidar2ego`;
    - per-camera `sensor2ego`, intrinsics, distortion and timestamp;
    - `gt_boxes` (x, y, z, l, w, h, heading in ego frame) and `track_tokens`.
- **Preprocessing does need nuplan-devkit.**
  - `nuplan_scripts/` has about 5.9k lines. Seven of its files import `nuplan.*`.
  - These cover video export, trajectory filtering, LiDAR registration and the map API.
  - It also pins nuplan-devkit 1.2.0, COLMAP 3.11.1, a customised KISS-ICP and UniDepth.
- **Adapter work:**
  1. Write the pickle from nuScenes: poses, the 6 cameras, and boxes interpolated from 2 Hz keyframes to the frames used.
  2. Replace the hard-coded nuPlan camera tuple (`CAM_F0` … `CAM_B0`, 8 cameras) in the dataparser and render tool.
  3. Point the LiDAR loader at nuScenes `.pcd.bin`.
  4. Produce semantic masks and UniDepth depth with MTGS's own scripts.
  5. Skip MTGS registration and use our aligned poses (or port its KISS-ICP step).
  - nuScenes images are already undistorted, so distortion is zero.
  - Size estimate: a few hundred lines of converter plus small edits [U, estimate].
- **Stack:** Python 3.9, torch 2.0.1 + CUDA 11.8, nerfstudio 1.1.5, gsplat 1.4.0, tiny-cuda-nn [C, `requirements.txt`, `docs/install.md`].
  - Our gsplat work runs Python 3.11 / torch 2.10 / CUDA 12.8 [C, `gaussian-splats.md`].
  - So MTGS needs its own conda environment under `/data` [U].
- **12 GB fit:**
  - The default trains at half resolution: `camera_res_scale_factor=0.5`, i.e. 960×540 on nuPlan [C].
  - At the same factor, nuScenes images are 800×450 [U, derived].
  - Fitting under 12 GB will need fewer drives, a Gaussian cap, or CPU image caching (already the default) [U]. This is the main spike risk.
- **Side note:** MTGS's Boston demo block is `road_block-331120_4690660_331190_4690710`. If nuPlan's Boston frame is UTM 19N (EPSG:32619, the frame our site file uses), that block lies about 300 m from `site-a1-signal` [U: the nuPlan map frame is not checked].

## Which `site-a1-signal` drives overlap well enough to fuse

Source: `/data/twin-sites/areas/site-a1-signal-twin/qa.json` on the box, written 2026-11-18 [C].
- Reference drive: scene-0233.
- 15 build drives; scene-0475 (rain) is excluded.
- The figures below are pairwise ground disagreement after alignment, p95 in metres, over the shared cells.

| Group | Drives | Pairwise p95 inside group | Shared cells per pair |
|---|---|---|---|
| A | 0233, 0248, 0295, 0714, 0715 | 0.1–0.7 m | 430–900 |
| B | 0234, 0259, 0296, 0297, 0716 | 0.2–0.4 m | 3,950–5,220 |
| B, weaker | 0249, 0685 (0685 ICP fitness 0.29) | 0.5–1.2 m against B | about 3,500–5,400 |
| Bridges | 0294, 0684, 0713 | 0.2–0.8 m against both A and B | 620–2,190 |

- **Between groups A and B, p95 is 2.4–3.6 m for 24 of the 25 pairs (0248–0296 is 0.77 m), but p50 stays at 0.03–0.23 m** [C].
  - The low p50 means most shared cells agree. A minority of cells differ by metres. My guess is one surface that A and B see differently, such as a ramp, bridge deck or kerb band. The cause is not found [U].
  - This disagreement, not the alignment itself, sets the 3.19 m worst case quoted in #419 [U: the worst pair here is 0249–0295 at 3.7 m after alignment; the 3.19 m figure may come from a different run].
- **Alignment corrections** (ICP, against 0233): translation 0.03–1.79 m, yaw within ±1°, ICP RMSE 0.09–0.31 m [C].
  - Under MTGS's own rejection rule (>1.0 m end-point or >0.5 m mean deviation from the log pose), 0294 (1.26 m), 0684 (1.19 m) and 0713 (1.79 m) may be dropped [U: MTGS measures against its own ICP, not ours].
- **Spike pick:** group B. It has the most shared cells, the tightest agreement and five drives, which matches MTGS's 3–6 traversals [U, recommendation].
- Do not fuse across A and B until the cross-group disagreement is explained [U].

## Other 2025–2026 multi-traversal work

None of these fuses traversals on nuScenes with released code.

- **ADM-GS** (arXiv 2604.05908, April 2026).
  - Splits static appearance into a traversal-invariant material part and a per-traversal illumination field. Reports +0.98 dB PSNR over latent-code baselines [C, abstract only].
  - Evaluated on Argoverse 2 and Waymo, not nuScenes [C, abstract].
  - The repo IRMVLab/ADM-GS holds a README only and has no licence [C].
- **LT-Gaussian** (arXiv 2508.01704, IEEE IV 2025).
  - Updates an old Gaussian map from a new LiDAR stream; benchmarked on nuScenes [C, abstract]. Which locations it uses is unverified.
  - It updates a map from a new drive rather than fusing drives jointly.
  - The repo ChengLuqi/LT-gaussian says "code will be released soon" and has no licence [C].
- **Bilateral-driving** (arXiv 2506.05280, NeurIPS 2025).
  - A single-traversal method that combines appearance codes with bilateral grids. Evaluated on nuScenes, Waymo, Argoverse and PandaSet [C, abstract].
  - Code: BigCiLeng/bilateral-driving, MIT, built on drivestudio's data pipeline [C, repo].
  - It is the ready-made nuScenes appearance model if we take the per-drive-merge path, or if we port MTGS's ideas into drivestudio [U, inference].
- **SpectralSplat** (arXiv 2604.03462): a feed-forward model that names multi-traversal data as a use case. No datasets in the abstract and no code link [C, abstract].
- **EUVS benchmark** (arXiv 2412.05256): extrapolated view synthesis on public multi-traversal AV data. The abstract does not name its source datasets [C]; whether nuScenes is among them is unverified.

## Sources

- MTGS: https://github.com/OpenDriveLab/MTGS (`README.md`, `LICENSE`, `docs/install.md`, `docs/prepare_dataset.md`, `mtgs/config/MTGS.py`, `mtgs/scene_model/gaussian_model/multi_color_gaussian_splatting.py`, `mtgs/scene_model/module/appearance.py`, `mtgs/dataset/nuplan_dataparser.py`, `nuplan_scripts/lidar_registration_multi_traversal.py`, `nuplan_scripts/ba_multi_traversal.py`, `thirdparty/kiss-icp/python/kiss_icp/datasets/mtgs.py`); paper https://arxiv.org/abs/2503.12552 (v3 HTML)
- 3DGM: https://github.com/NVlabs/3DGM (README; issues #1–#3); paper https://arxiv.org/abs/2405.17187 (HTML)
- drivestudio: https://github.com/ziyc/drivestudio (MIT, last push 2025-08-27)
- ADM-GS: https://arxiv.org/abs/2604.05908, https://github.com/IRMVLab/ADM-GS
- LT-Gaussian: https://arxiv.org/abs/2508.01704, https://github.com/ChengLuqi/LT-gaussian
- Bilateral-driving: https://arxiv.org/abs/2506.05280, https://github.com/BigCiLeng/bilateral-driving
- SpectralSplat: https://arxiv.org/abs/2604.03462
- EUVS: https://arxiv.org/abs/2412.05256
- Our data: box `/data/twin-sites/areas/site-a1-signal.json` and `site-a1-signal-twin/qa.json`; [`gaussian-splats.md`](gaussian-splats.md)
