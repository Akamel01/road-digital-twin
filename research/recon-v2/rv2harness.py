"""Road-surface scoring harness for static layers (road-digital-twin map #415, ticket #416).

Every reconstruction spike scores the same way:

  split  -> split.json: the held-out keyframes per drive, the views to render, and the time
            windows that training must exclude (no camera frame or LiDAR sweep inside them).
  gt     -> gt/<view>.npz: road and sidewalk LiDAR points of the held-out keyframe sweep,
            projected into each held-out camera (u, v, z, class). Site polygon only.
  score  -> score.json: PSNR/SSIM per view and overall, and the road depth error p50/p95.

Contract with a method: for every view in split.json["views"], write
  <pred>/<view_token>.png        RGB render, same size as the camera image
  <pred>/<view_token>.depth.npy  float32 z-depth in metres (camera frame), NaN where empty
Camera poses in split.json are cam->global 4x4 in the nuScenes global (map) frame, the frame
methods that read nuScenes natively already use. Intrinsics are the nuScenes K.

Off-path views (drives other than the trained one, same site) are scored the same way and
reported apart; they never gate.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

DRIVEABLE = 24  # nuScenes-lidarseg flat.driveable_surface
SIDEWALK = 26  # flat.sidewalk
Z_MIN, Z_MAX = 1.0, 50.0
HOLDOUT_EVERY, HOLDOUT_PHASE = 4, 2  # keyframe index % 4 == 2 is held out (25%)
EXCLUDE_US = 250_000  # training drops camera frames and sweeps within +-0.25 s of a held-out keyframe
CAMS = ("CAM_FRONT", "CAM_FRONT_RIGHT", "CAM_BACK_RIGHT", "CAM_BACK", "CAM_BACK_LEFT", "CAM_FRONT_LEFT")


def _pose(translation, rotation) -> np.ndarray:
    from pyquaternion import Quaternion

    m = np.eye(4)
    m[:3, :3] = Quaternion(rotation).rotation_matrix
    m[:3, 3] = translation
    return m


def _nusc(dataroot: str, version: str):
    from nuscenes.nuscenes import NuScenes

    return NuScenes(version=version, dataroot=dataroot, verbose=False)


def _sensor_to_global(nusc, sd_token: str) -> np.ndarray:
    sd = nusc.get("sample_data", sd_token)
    cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
    ep = nusc.get("ego_pose", sd["ego_pose_token"])
    return _pose(ep["translation"], ep["rotation"]) @ _pose(cs["translation"], cs["rotation"])


def _site_polygon_global(area: dict):
    """Area polygon (EPSG:32619) to the nuScenes global frame (local tmerc at the map origin)."""
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    lat, lon = (42.336849169438615, -71.05785369873047)  # boston-seaport map (0, 0); twin/stages/load.py
    local = f"+proj=tmerc +lat_0={lat} +lon_0={lon} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m"
    to_local = Transformer.from_crs(f"EPSG:{area['epsg']}", local, always_xy=True)
    return transform(to_local.transform, shape(area["polygon"]))


def cmd_split(a) -> None:
    area = json.loads(Path(a.area).read_text())
    nusc = _nusc(a.dataroot, area.get("dataset_version", "v1.0-trainval"))
    scene_by_name = {s["name"]: s for s in nusc.scene}
    drives = [d["scene"] for d in area["drives"] if d.get("build_input", True)]
    views, exclude = [], {}
    for name in drives:
        scene = scene_by_name[name]
        tok, idx, windows = scene["first_sample_token"], 0, []
        while tok:
            s = nusc.get("sample", tok)
            if idx % HOLDOUT_EVERY == HOLDOUT_PHASE:
                windows.append([s["timestamp"] - EXCLUDE_US, s["timestamp"] + EXCLUDE_US])
                for cam in CAMS:
                    sd = nusc.get("sample_data", s["data"][cam])
                    cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
                    views.append({
                        "token": sd["token"], "scene": name, "sample": s["token"], "channel": cam,
                        "lidar_token": s["data"]["LIDAR_TOP"], "image": sd["filename"],
                        "timestamp_us": sd["timestamp"], "width": sd["width"], "height": sd["height"],
                        "K": cs["camera_intrinsic"],
                        "cam_to_global": _sensor_to_global(nusc, sd["token"]).tolist(),
                    })
            tok, idx = s["next"], idx + 1
        exclude[name] = windows
    out = {
        "area": area["name"], "frame": "nuScenes global (map) frame, metres",
        "rule": f"keyframe index % {HOLDOUT_EVERY} == {HOLDOUT_PHASE} held out; training excludes every camera "
                f"frame and LiDAR sweep within +-{EXCLUDE_US / 1e6:.2f} s of a held-out keyframe",
        "train_exclude_us": exclude, "views": views,
    }
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(f"split: {len(drives)} drives, {len(views)} views -> {a.out}")


def cmd_gt(a) -> None:
    from nuscenes.utils.data_classes import LidarPointCloud
    from shapely import contains_xy

    split = json.loads(Path(a.split).read_text())
    area = json.loads(Path(a.area).read_text())
    nusc = _nusc(a.dataroot, area.get("dataset_version", "v1.0-trainval"))
    poly = _site_polygon_global(area)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lidar_cache: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    n_total = 0
    for v in split["views"]:
        lt = v["lidar_token"]
        if lt not in lidar_cache:
            sd = nusc.get("sample_data", lt)
            pc = LidarPointCloud.from_file(str(Path(a.dataroot) / sd["filename"]))
            labels = np.fromfile(str(Path(a.dataroot) / nusc.get("lidarseg", lt)["filename"]), dtype=np.uint8)
            keep = np.isin(labels, (DRIVEABLE, SIDEWALK))
            xyz = (_sensor_to_global(nusc, lt) @ np.vstack([pc.points[:3], np.ones(pc.points.shape[1])]))[:3].T
            xyz, cls = xyz[keep], labels[keep]
            inside = contains_xy(poly, xyz[:, 0], xyz[:, 1])
            lidar_cache[lt] = (xyz[inside], cls[inside])
        xyz, cls = lidar_cache[lt]
        w2c = np.linalg.inv(np.asarray(v["cam_to_global"]))
        cam = xyz @ w2c[:3, :3].T + w2c[:3, 3]
        z = cam[:, 2]
        ok = (z >= Z_MIN) & (z <= Z_MAX)
        K = np.asarray(v["K"])
        uvw = cam[ok] @ K.T
        u, vv = uvw[:, 0] / uvw[:, 2], uvw[:, 1] / uvw[:, 2]
        inb = (u >= 0) & (u < v["width"]) & (vv >= 0) & (vv < v["height"])
        np.savez_compressed(out / f"{v['token']}.npz", u=u[inb].astype(np.float32), v=vv[inb].astype(np.float32),
                            z=z[ok][inb].astype(np.float32), cls=cls[ok][inb])
        n_total += int(inb.sum())
    print(f"gt: {len(split['views'])} views, {n_total} road/sidewalk samples -> {out}")


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Mean SSIM over RGB, 11x11 Gaussian window (sigma 1.5), images in [0, 1]."""
    from scipy.ndimage import gaussian_filter

    c1, c2 = 0.01 ** 2, 0.03 ** 2
    vals = []
    for ch in range(3):
        x, y = a[..., ch], b[..., ch]
        f = lambda t: gaussian_filter(t, 1.5, truncate=3.5)
        mx, my = f(x), f(y)
        sxx, syy, sxy = f(x * x) - mx * mx, f(y * y) - my * my, f(x * y) - mx * my
        vals.append(((2 * mx * my + c1) * (2 * sxy + c2) / ((mx * mx + my * my + c1) * (sxx + syy + c2))).mean())
    return float(np.mean(vals))


def cmd_score(a) -> None:
    from PIL import Image

    split = json.loads(Path(a.split).read_text())
    pred, gtd = Path(a.pred), Path(a.gt)
    trained = set(a.trained_scenes.split(",")) if a.trained_scenes else None
    groups = {"on_path": {"psnr": [], "ssim": [], "road": [], "sidewalk": [], "cover": [0, 0]},
              "off_path": {"psnr": [], "ssim": [], "road": [], "sidewalk": [], "cover": [0, 0]}}
    missing = 0
    for v in split["views"]:
        if trained is not None and v["scene"] not in trained and not a.score_off_path:
            continue
        g = groups["on_path" if trained is None or v["scene"] in trained else "off_path"]
        rp, dp = pred / f"{v['token']}.png", pred / f"{v['token']}.depth.npy"
        if not rp.exists() or not dp.exists():
            missing += 1
            continue
        gt_img = np.asarray(Image.open(Path(a.dataroot) / v["image"]).convert("RGB"), dtype=np.float64) / 255.0
        img = np.asarray(Image.open(rp).convert("RGB"), dtype=np.float64) / 255.0
        if img.shape != gt_img.shape:
            raise SystemExit(f"render {rp.name} is {img.shape}, camera image is {gt_img.shape}")
        mse = float(((img - gt_img) ** 2).mean())
        g["psnr"].append(10 * math.log10(1.0 / max(mse, 1e-10)))
        g["ssim"].append(_ssim(img, gt_img))
        depth = np.load(dp)
        s = np.load(gtd / f"{v['token']}.npz")
        ui = np.clip(np.floor(s["u"]).astype(int), 0, depth.shape[1] - 1)
        vi = np.clip(np.floor(s["v"]).astype(int), 0, depth.shape[0] - 1)
        d = depth[vi, ui]
        valid = np.isfinite(d) & (d > 0)
        g["cover"][0] += int(valid.sum())
        g["cover"][1] += int(valid.size)
        err = np.abs(d[valid] - s["z"][valid])
        c = s["cls"][valid]
        g["road"].append(err[c == DRIVEABLE])
        g["sidewalk"].append(err[c == SIDEWALK])

    def summ(g):
        road = np.concatenate(g["road"]) if g["road"] else np.zeros(0)
        side = np.concatenate(g["sidewalk"]) if g["sidewalk"] else np.zeros(0)
        q = lambda x, p: float(np.percentile(x, p)) if x.size else None
        return {
            "n_views": len(g["psnr"]),
            "psnr": float(np.mean(g["psnr"])) if g["psnr"] else None,
            "ssim": float(np.mean(g["ssim"])) if g["ssim"] else None,
            "road_depth_p50_m": q(road, 50), "road_depth_p95_m": q(road, 95), "n_road": int(road.size),
            "sidewalk_depth_p50_m": q(side, 50), "sidewalk_depth_p95_m": q(side, 95), "n_sidewalk": int(side.size),
            "depth_coverage": (g["cover"][0] / g["cover"][1]) if g["cover"][1] else None,
        }

    on = summ(groups["on_path"])
    result = {
        "on_path": on, "off_path": summ(groups["off_path"]), "missing_views": missing,
        "pass_bar": {"psnr_min": 26.0, "road_depth_p95_max_m": 0.05},
        "passes": bool(on["psnr"] is not None and on["road_depth_p95_m"] is not None
                       and on["psnr"] >= 26.0 and on["road_depth_p95_m"] <= 0.05 and missing == 0),
    }
    Path(a.out).write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataroot", default="/data/nuscenes")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split")
    s.add_argument("--area", required=True)
    s.add_argument("--out", required=True)
    g = sub.add_parser("gt")
    g.add_argument("--area", required=True)
    g.add_argument("--split", required=True)
    g.add_argument("--out", required=True)
    c = sub.add_parser("score")
    c.add_argument("--split", required=True)
    c.add_argument("--gt", required=True)
    c.add_argument("--pred", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--trained-scenes", default="", help="comma list; views of other scenes count as off-path")
    c.add_argument("--score-off-path", action="store_true")
    a = p.parse_args()
    {"split": cmd_split, "gt": cmd_gt, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
