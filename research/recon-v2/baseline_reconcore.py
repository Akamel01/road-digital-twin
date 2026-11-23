"""Baseline for #416: recon-core v0.1.3 splat on the site-a1 capture, held-out frames removed, rendered at the harness views."""
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from gsplat import rasterization
from PIL import Image
from recon_core.capture.model import load_capture
from recon_core.nodes import splat as S

cap_dir, views_json, out_dir, iters = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]
out_dir.mkdir(parents=True, exist_ok=True)
V = json.load(open(views_json))
win = {s: np.asarray(w) for s, w in V["exclude"].items()}

def held(name):
    scene, ts = name.split("/")[0], int(Path(name).stem)
    w = win.get(scene)
    return w is not None and len(w) and bool(((ts >= w[:, 0]) & (ts <= w[:, 1])).any())

cap = load_capture(cap_dir)
keep = {i: im for i, im in cap.colmap.images.items() if not held(im.name)}
print("images", len(cap.colmap.images), "kept", len(keep), flush=True)
cap = dataclasses.replace(cap, colmap=dataclasses.replace(cap.colmap, images=keep))
args = S.parse_args([str(cap_dir), str(out_dir / "s.ply"), str(out_dir / "s.splat"), "--iterations", iters, "--seed", "42"])
views = S.build_cameras(cap, cap_dir)
init = S.initialise_points(cap, voxel=args.voxel_size, cap=args.max_init_points, seed=args.seed)
samples, _ = S._lidar_depth_samples(cap, views)
splat, secs = S.train(views, list(range(len(views))), (init.xyz, init.rgb), samples, args)
print("trained", round(secs, 1), "s", flush=True)
with torch.no_grad():
    for v in V["views"]:
        r, a, _ = rasterization(splat.means, F.normalize(splat.quats, dim=-1), torch.exp(splat.scales),
            torch.sigmoid(splat.opacity), splat.sh0.unsqueeze(1),
            torch.tensor(v["viewmat"], device="cuda", dtype=torch.float32)[None],
            torch.tensor(v["K"], device="cuda", dtype=torch.float32)[None], v["width"], v["height"],
            sh_degree=0, render_mode="RGB+ED", packed=True)
        rgb = (r[0, :, :, :3].clamp(0, 1) * 255).round().byte().cpu().numpy()
        d = r[0, :, :, 3].cpu().numpy().astype(np.float32)
        d[a[0, :, :, 0].cpu().numpy() < 0.5] = np.nan
        Image.fromarray(rgb).save(out_dir / f"{v['token']}.png")
        np.save(out_dir / f"{v['token']}.depth.npy", d)
print("rendered", len(V["views"]), flush=True)
