# Road-surface scoring harness (map #415, ticket #416)

Scores any static-layer reconstruction of an area against held-out nuScenes keyframes.

- `rv2harness.py split`: every 4th keyframe (index % 4 == 2) is held out; training excludes frames within 0.25 s of a held-out keyframe.
- `rv2harness.py gt`: ground truth is the held-out keyframe's LiDAR points labelled driveable_surface (24) or sidewalk (26) by nuScenes-lidarseg, inside the site polygon, projected into each camera (z between 1 and 50 m).
- `rv2harness.py score`: a method writes `<token>.png` and `<token>.depth.npy` (z-depth, metres, NaN where empty) per held-out view. Reports PSNR, SSIM, road and sidewalk depth error p50/p95, depth coverage, split into on-path and off-path views. Pass bar: PSNR >= 26 dB and road depth p95 <= 0.05 m, no missing views.
- `overlay.py`: draws ground truth over the camera image to check the projection.
- `views_to_capture.py`, `baseline_reconcore.py`: adapter and baseline for the recon-core splat node.

Data lives on the box under `/data/recon-v2/` and is never committed (nuScenes licence).
