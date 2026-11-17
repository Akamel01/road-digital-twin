# What the colour stage already gives a camera-label-to-ground projection

Issue #296 (part of #293). Local codebase only, read on `origin/main` at 14cecba (2026-11-17). Run times from the box's `/data/twin-dev` manifests, read-only.

## Short answer

The colour stage and the semantics stage already do the hard part of "project camera labels onto the ground": they map each ground **point** to a pixel, test it against a z-buffer, and vote per ground **cell** across images. What exists is a **forward** map (ground point to pixel), a **hard-label** vote (argmax class per pixel), and a **single-drive** scope. Per-pixel probabilities, per-observation weights, a per-cell registration error and any multi-drive path are missing.

## 1. What the colour stage computes today

| Quantity | Computed? | Where |
|---|---|---|
| Pixel to ground point | **No, only the inverse.** Each lidar ground/non-ground point is projected into the image (`project`: world to camera, then K). There is no ray cast from a pixel. A pixel gets a ground location only if some lidar point lands in it. | `twin/stages/zbuffer.py:123-139`, used at `twin/stages/colour.py:117-120` |
| Colour taken | Nearest-pixel lookup (floor of u, v) at the projected point. | `colour.py:117-120` |
| Visibility / occlusion | Yes. Per image, a depth buffer at `zbuf_scale` (0.25) resolution of non-ground points plus box faces (boxes lerped to image time); a target passes if in image (1 px margin), depth at least `min_depth_m` (1 m), within `max_range_m` (12 m) horizontally, and depth <= buffer + `zbuf_tol_m` (0.2 m). Ground never occludes ground. | `zbuffer.py:142-195`, `zbuffer.py:15-16`; params `twin/contracts.py:274-289` |
| Views per point | Yes. Keeps the `top_k` (5) smallest-footprint views per point (footprint d^3/(f^2 h)); `n_views` is returned. | `colour.py:42-54`, `colour.py:81-142` |
| Views per cell | Only a summary. `views_median` and `observed_share` go to `qa.json`; `n_views` per point is **not** written to disk. The semantics stage does keep a per-cell `images` count. | `colour.py:383-384`, `colour.py:372`; `semantics.py:178-215` |
| Camera pose per image | Yes. Refined ego pose lerp/slerp to image time times the camera extrinsic. | `zbuffer.py:67-91` |
| Registration error | Yes, but pooled. P50/P95 of painted-stripe offset against lidar markings over the whole orthoimage, plus a hold-out P95 (ADR 0007 D11). Not per cell or per pixel. | `colour.py:206-305`, `colour.py:375-399` |
| Per-frame pose refinement (#270, e5e88de) | Opt-in method `zbuffer-pose-refine`. 6-DOF correction per frame by point-to-line least squares against lidar paint edges (4 rounds, bounded 0.5 deg / 5 cm). Refined poses are used for colouring only and are **not saved**; only the corrections summary lands in `qa.json`. | `twin/stages/colour_pose.py:1-14, 141-228`; `colour.py:342-354, 400`; `docs/decisions/0007-colour-camera-lidar-registration.md:9` |
| Ortho raster | Per-cell lower median of observed ground points at `gsd_m` (5 cm), north-up RGBA, alpha 0 = unobserved. | `colour.py:145-175` |
| Outputs | `ortho.png`, `ortho.pgw`, `rgb.npz` (per-point `rgb`, `observed`), `qa.json`. | `colour.py:35, 368-372, 408` |

Where the colour lands: `rgb.npz` is aligned to ground points then non-ground points (`colour.py:315-316`), and `outputs` reads it back for `twin.laz` (`twin/stages/outputs.py:62-73`).

## 2. A closer existing consumer: the semantics stage (#178)

`twin/stages/semantics.py` already projects **class labels** onto the ground by reusing colour's visibility test.

- Segmenter: Mask2Former Swin-L on Mapillary Vistas (research-only licence). It sums class probability x mask probability per query, then takes `argmax`, then maps to our 5 classes (`semantics.py:81-120`, licences `:50-56`). **The probabilities exist inside the model but are collapsed to a class code before projection** (`semantics.py:119-120`).
- Targets: ground points plus non-ground within curb height (`semantics.py:522-523`).
- `vote()`: for each image, visibility from `zbuffer.visible` (`semantics.py:128-146, 197`), pixel lookup at the projected point (`semantics.py:199-204`), then per 10 cm cell integer counts `seen`, `images`, `marking`, `crosswalk`, `curb` (`semantics.py:149-215`). "Probability" is `votes / seen` over points, not a mean of model probabilities (`semantics.py:223-226`).
- Outputs: `prob.npz`, `prob.pgw`, `paint_prob.png`, `curb_prob.png`, `qa.json`, plus camera and fused feature variants (`semantics.py:33, 553-580`). Seconds for segmenting and projecting are logged (`semantics.py:171-173, 218-222`).
- It uses the **calibrated** poses from `camera_to_world`, not colour's refined ones (`semantics.py:545`); colour's refinement is local to `colour._run` (`colour.py:349-350`).

## 3. What a per-pixel class-probability projection still needs

1. **Soft labels through the projection.** Segmenter returns (H, W, C) probabilities, not class codes (change at `semantics.py:117-120`); the vote accumulates probability mass (float), not integer hard votes (`semantics.py:162-215`). Memory for C classes per image is the cost to plan.
2. **Interpolated sampling.** Colour and semantics both floor to the nearest pixel (`colour.py:117-120`, `semantics.py:199-204`). Bilinear sampling, or the footprint's pixel area, is needed when a ground cell spans several pixels or a pixel spans several cells (far range).
3. **A weight per observation.** Colour already ranks by footprint (`colour.py:42-54`) but semantics votes every visible view equally. Footprint, range and registration confidence should weight the sum.
4. **Per-cell uncertainty on the registration.** Only a pooled P50/P95 exists (`colour.py:393-399`). Per-frame deltas are summarised, not stored (`colour.py:400`; ADR 0007 line 9). To mask or down-weight cells near a known misregistration, per-frame refined poses (or a per-cell offset map) must be written.
5. **Dense ground, not lidar points.** Targets are the lidar ground **points**, so a cell with no lidar return gets no label however clearly the camera sees it. A pixel-to-ground ray cast needs a ground surface (`surface.npz` from the ground stage, read at `colour.py:337` and used by `profile.ground_z_at`, `colour_pose.py:76-85`) and its own occlusion test against that surface. The z-buffer here deliberately excludes ground (`zbuffer.py:154-157`), so ground-on-ground occlusion (shallow-angle views, a curb hiding the road behind it) is not tested.
6. **Persist the per-cell evidence.** Per-point `n_views` is dropped (`colour.py:372`). Per-cell view count, summed weight and mean footprint should be written beside the probability raster.
7. **Range limit.** `max_range_m` is 12 m (`contracts.py:280`) with errors rising fast beyond that (`docs/research/camera-ground-projection.md`, error table); labels beyond 12 m are never produced. Far, thin paint needs a decision on the limit.

## 4. Multiple drives and the area build

- The colour and semantics stages are single-drive: both read one scene's `cameras.json`, `boxes.json` and `poses.json` (`colour.py:318-328`, `semantics.py:529-540`).
- `twin area merge` builds each drive through **load, mask, align only**, clips to the polygon, and registers the drives by ICP plus a height plane (`twin/merge.py:396-427`, `merge.py:1-9`). Camera files, boxes and refined poses are not carried into `merged.npz`.
- `twin area twin` runs `ground, features, profile, isd, accuracy` on the merged cloud (`twin/areatwin.py:65`, docstring `:1-20`). No colour or semantics stage is in the area path.
- So an area-level label map has no existing path. Two routes: (a) run colour/semantics per drive, then fuse the per-cell evidence across drives in the merged frame, applying each drive's merge correction (`merge.py:287-300` returns a 4x4 per drive plus a height surface); or (b) re-project every drive's cameras against the merged cloud. Route (a) matches the current stage contract (one scene folder per stage) and needs only the per-cell evidence of item 6 above. Merged drives also differ in height by metres before registration and by a smooth residual after it (`merge.py:40-58`; `areatwin.py:44-48`), which sets the label-to-ground registration floor for area use.

## 5. Run time per drive

Read from `/data/twin-dev/<run>/manifest.json` stage seconds and `6_colour/qa.json` (read-only, no sudo).

| Run | Method | Device | Cameras | Points | Colour seconds | Whole pipeline |
|---|---|---|---|---|---|---|
| 20261116-220543-29f3b4 | zbuffer-topk | GPU | 240 | 2.90 M | 65 | about 5 min (align 136, load 44, ground 42) |
| 20261116-234102-ca5241 | zbuffer-topk | CPU | 234 | 1.00 M | 178 | about 6 min (align 100, load 32) |
| 20261116-173437-96a1c6 | zbuffer-pose-refine | CPU | 234 | 1.00 M | 8410 (2 h 20 min) | colour dominates; 76 of 234 frames refined |
| 20261109-230238-600aa5 .. 20261110-002509-298849 | zbuffer-topk | (not in manifest) | n/a | n/a | 125 to 332 | early dev runs |

- Plain `zbuffer-topk` colouring is about 1 to 3 minutes per drive on the GPU and 3 minutes on the CPU. P95 stripe offset in those runs was 0.19 to 0.20 m; the pose-refine run reached 0.145 m P95, 0.096 m P50 (qa.json).
- `zbuffer-pose-refine` costs about 8400 s on CPU for one drive, the number that triggered the #270 solver rewrite (the commit message e5e88de records the same figure). The rewrite's own timing is not in the manifests I could find.
- Semantics: **no run exists on the box** (`/data/twin-dev` has no `11_semantics` folder or `prob.npz`; the three manifests checked list semantics at 0 s). Its time per drive is therefore unknown here. It splits into `seconds_segment` and `seconds_project` in its `qa.json` (`semantics.py:171-173, 568-570`), so the first real run reads both directly. The projection part reuses the same visibility call as colour, so the 65 to 178 s figure is a floor for it; the segmenter adds a Swin-L forward pass per image (about 240 images).
- Free disk on the box at read time: 22 GB on `/` (97% used); no heavy jobs were run.

## Sources

All claims cite repository files at 14cecba. Run figures are from the box manifests named in section 5. The error budget in `docs/research/camera-ground-projection.md` (issue #7) is the prior research on range and pose error, not re-derived here.
