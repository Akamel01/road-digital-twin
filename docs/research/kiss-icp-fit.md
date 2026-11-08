# KISS-ICP fit for the align stage (#5)

Question (#5): can the KISS-ICP Python API take one numpy array per masked sweep, with no timestamps, and return an anchorable 4×4 pose per sweep? This decides the align stage in T4 ([spec section 6, Align](../design/twin-v1-spec.md#6-methods-operator-directed)).

Sources read on 2026-11-07: PRBonn/kiss-icp `main` at `1ffa7d7` (2026-05-04), which differs from tag `v1.3.0` only in `datasets/ouster.py` and `pyproject.toml` (GitHub compare API).

## Answer

**Yes.** The Python class `KissICP` takes one `(N, 3)` float64 array per sweep and an empty timestamp array, and it exposes the pose after each call. Masking needs nothing special: a masked sweep is just a smaller array.

1. **API.** Build a config with `kiss_icp.config.load_config(None)` and set its fields, then create `kiss_icp.kiss_icp.KissICP(config)`. For each sweep, in time order, call `odo.register_frame(points, np.array([]))` and read `odo.last_pose` (a 4×4 numpy array), then copy it. This is the same loop that `OdometryPipeline._run_pipeline` runs. The CLI is not needed.
2. **Frame.** Each pose maps that sweep's points into the frame of the **first sweep fed in**. Pose 0 is the identity. The poses are in whatever frame the input points are in. If we feed raw `LIDAR_TOP` points (sensor frame), the poses are lidar poses relative to the first lidar pose, T(lidar_0 ← lidar_k). To anchor them, compare against the nuScenes `ego_pose @ calibrated_sensor` of the same sweeps (global ← lidar), which is what KISS-ICP's own nuScenes loader uses as ground truth. Then the Umeyama x/y/yaw fit in the spec applies directly. Do not feed points that are already in the global frame: the maintainers say this breaks KISS-ICP ([issue #297](https://github.com/PRBonn/kiss-icp/issues/297)).
3. **Deskew off without timestamps.** Yes. Set `config.data.deskew = False`. Even with deskew on, the C++ preprocessor skips motion compensation when `timestamps` is empty (`if (!deskew_ || timestamps.empty()) return frame;`). Its own nuScenes loader passes `np.array([])`.
4. **Config for 32-beam nuScenes (starting point, still to be tuned on a real scene in T4):**
   ```yaml
   data:      {deskew: false, max_range: 70.0, min_range: 2.0}
   mapping:   {voxel_size: 0.5, max_points_per_voxel: 20}
   adaptive_threshold: {initial_threshold: 2.0, min_motion_th: 0.1}   # defaults
   ```
   - `voxel_size: 0.5`: the default is `max_range / 100` (1.0 m at the default 100 m range), which is too coarse for 32 beams. The maintainer's fix for a sparse 32-beam sensor used 0.5 m ([#128](https://github.com/PRBonn/kiss-icp/issues/128)).
   - The same comment also removes the second, 1.5 × voxel downsample of the registration source. We can do that without forking by subclassing `KissICP` and overriding `voxelize()` to return `(frame_downsample, frame_downsample)`. Keep this as an A/B option, not the default ([#239](https://github.com/PRBonn/kiss-icp/issues/239) repeats the advice).
   - `min_range: 2.0` drops returns from the ego car's own roof and body. KISS-ICP's loader does not drop them. The devkit's own multisweep loader drops points closer than 1.0 m. The 2.0 m value is my estimate and is not verified.
   - `max_range: 70.0`: my choice to keep sparse far returns out of ICP; the default is 100.
5. **nuScenes dataloader** (`datasets/nuscenes.py`):
   - It is hard-wired to `v1.0-mini` / `mini_train`, so it can't load trainval scenes as shipped.
   - It starts from the scene's first sample, takes its `LIDAR_TOP` sample_data and follows `next` to the end. So it reads **every 20 Hz sweep, keyframes and non-keyframes**.
   - It reads each `.pcd.bin` with `LidarPointCloud.from_file` and keeps x, y, z only (float64). Intensity is dropped, no range or ego-body filter is applied, and timestamps are `np.array([])`.
   - Points stay in the **lidar sensor frame**. It does **not** apply the lidar calibration to the points. It uses `calibrated_sensor` only for ground truth: `gt = ego_pose @ calibrated_sensor`, then left-multiplied by `inv(gt[0])`. It has no `apply_calibration`, so result poses are written as they are.
   - What to reuse: the sweep walk and the GT formula. It is about 20 lines, so we copy the pattern into our loader rather than import the class.
6. **Licence and version.** MIT (GitHub licence API, `LICENSE`), compatible with our Apache-2.0 repo. Pin `kiss-icp==1.3.0` (PyPI, uploaded 2026-04-26, `requires_python >=3.8`). Its config uses pydantic and pydantic-settings.

Verified on the Mac in a throwaway venv (Python 3.11, arm64, `pip install kiss-icp==1.3.0`, prebuilt wheel, no sudo). Synthetic static scene (ground, walls, poles, boxes), sweeps in the sensor frame with a 4 m × 3 m box masked out, 0.5 m and 0.01 rad per sweep (about 10 m/s at nuScenes' 20 Hz), and the config above:

| Sweeps | pose[0] is identity | Max translation error vs truth |
|---|---|---|
| 2 | yes | 0.009 m |
| 10 | yes | 0.006 m |

A first try with 1.2 m steps in a corridor (walls only along the direction of travel) drifted by 1.3 to 2.3 m. The first ICP step starts from a zero-velocity guess, and a long corridor gives little constraint along the direction of travel. A real nuScenes scene at 20 Hz moves less than 1 m per sweep, so this is a warning about featureless stretches, not a blocker. The spec's fallback to dataset poses (`height_valid=false`) covers it. The test script (about 50 lines) was throwaway and is not committed.

## Evidence

- Python API, `register_frame(frame, timestamps)`, `last_pose`, `last_delta`, initial guess `last_pose @ last_delta`: [python/kiss_icp/kiss_icp.py](https://github.com/PRBonn/kiss-icp/blob/1ffa7d7512f10bfc8b1185095011fa31184019e3/python/kiss_icp/kiss_icp.py)
- Pipeline loop `raw_frame, timestamps = dataset[idx]` → `register_frame` → `poses[idx] = odometry.last_pose`; `_calibrate_poses` only when the dataset defines `apply_calibration`: [python/kiss_icp/pipeline.py](https://github.com/PRBonn/kiss-icp/blob/1ffa7d7512f10bfc8b1185095011fa31184019e3/python/kiss_icp/pipeline.py)
- Config fields and defaults (`max_range 100`, `min_range 0`, `deskew True`, `voxel_size None`, `max_points_per_voxel 20`, `initial_threshold 2.0`, `min_motion_th 0.1`): [config/config.py](https://github.com/PRBonn/kiss-icp/blob/1ffa7d7512f10bfc8b1185095011fa31184019e3/python/kiss_icp/config/config.py). `voxel_size = max_range / 100` when unset: [config/parser.py](https://github.com/PRBonn/kiss-icp/blob/1ffa7d7512f10bfc8b1185095011fa31184019e3/python/kiss_icp/config/parser.py)
- Deskew skipped on empty timestamps; range filter `min_range < |p| < max_range`: [cpp/kiss_icp/core/Preprocessing.cpp](https://github.com/PRBonn/kiss-icp/blob/1ffa7d7512f10bfc8b1185095011fa31184019e3/cpp/kiss_icp/core/Preprocessing.cpp)
- nuScenes loader: [python/kiss_icp/datasets/nuscenes.py](https://github.com/PRBonn/kiss-icp/blob/1ffa7d7512f10bfc8b1185095011fa31184019e3/python/kiss_icp/datasets/nuscenes.py)
- Devkit multisweep loader drops points closer than `min_distance=1.0`: [nuscenes-devkit data_classes.py](https://github.com/nutonomy/nuscenes-devkit/blob/master/python-sdk/nuscenes/utils/data_classes.py)
- Sparse 32-beam tuning (voxel 0.5, skip the second downsample), maintainer comment: [kiss-icp#128](https://github.com/PRBonn/kiss-icp/issues/128), repeated in [#239](https://github.com/PRBonn/kiss-icp/issues/239)
- Masked nuScenes sweeps work once the points are in the sensor frame, not the global frame: [kiss-icp#297](https://github.com/PRBonn/kiss-icp/issues/297)
- Licence: [LICENSE](https://github.com/PRBonn/kiss-icp/blob/main/LICENSE) (MIT). Version: [PyPI kiss-icp 1.3.0](https://pypi.org/project/kiss-icp/1.3.0/); tags [v1.3.0](https://github.com/PRBonn/kiss-icp/releases/tag/v1.3.0)

## Minimal call pattern

```python
import numpy as np
from kiss_icp.config import load_config
from kiss_icp.kiss_icp import KissICP

cfg = load_config(None)
cfg.data.deskew, cfg.data.max_range, cfg.data.min_range = False, 70.0, 2.0
cfg.mapping.voxel_size = 0.5
odo = KissICP(cfg)
poses = []
for pts in sweeps:                      # (N, 3) float64, LIDAR_TOP frame, masked, time order
    odo.register_frame(pts, np.array([]))
    poses.append(odo.last_pose.copy())  # T(lidar_0 <- lidar_k)
```
