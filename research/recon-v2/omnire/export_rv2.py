"""Render a trained drivestudio model at the harness held-out cameras (full 1600x900, harness pose and K).

usage: export_rv2.py RUN_DIR SPLIT_JSON OUT_DIR   (run from the drivestudio folder, RV2_SPLIT set)
Writes <token>.png and <token>.depth.npy (expected z-depth, NaN where opacity < 0.5), plus per-layer PNGs
for a few views (static background, dynamic actors) under OUT_DIR/layers/."""
import json
import os
import sys

import numpy as np
import torch
from datasets.base.pixel_source import get_rays
from datasets.driving_dataset import DrivingDataset
from omegaconf import OmegaConf
from PIL import Image
from utils.misc import import_str

run_dir, split_json, out = sys.argv[1:4]
os.makedirs(f"{out}/layers", exist_ok=True)
cfg = OmegaConf.load(f"{run_dir}/config.yaml")
dataset = DrivingDataset(data_cfg=cfg.data)
trainer = import_str(cfg.trainer.type)(
    **cfg.trainer, num_timesteps=dataset.num_img_timesteps, model_config=cfg.model,
    num_train_images=len(dataset.train_image_set), num_full_images=len(dataset.full_image_set),
    test_set_indices=dataset.test_timesteps, scene_aabb=dataset.get_aabb().reshape(2, 3), device=torch.device("cuda"))
trainer.resume_from_checkpoint(ckpt_path=os.environ.get("RV2_CKPT", f"{run_dir}/checkpoint_final.pth"), load_only_model=True)
trainer.set_eval()
trainer.render_each_class = True

with open(split_json) as f:
    sp = json.load(f)
with open("/data/recon-v2/a1/split.json") as f:
    hv = {v["token"]: v for v in json.load(f)["views"]}
scene_dir = os.path.join(cfg.data.data_root, f"{cfg.data.scene_idx:03d}")
F0 = np.loadtxt(f"{scene_dir}/extrinsics/000_0.txt")
peak = 0
for n, (key, tok) in enumerate(sorted(sp["views"].items())):
    t, c = map(int, key.split("_"))
    v = hv[tok]
    img_infos, cam_infos = dataset.full_image_set.get_image(t * dataset.pixel_source.num_cams + c, camera_downscale=1.0)
    H, W = v["height"], v["width"]
    K = torch.tensor(v["K"], dtype=torch.float32, device="cuda")
    c2w = torch.tensor(np.linalg.inv(F0) @ np.asarray(v["cam_to_global"]), dtype=torch.float32, device="cuda")
    x, y = torch.meshgrid(torch.arange(W, device="cuda"), torch.arange(H, device="cuda"), indexing="xy")
    o, d, dn = get_rays(x.flatten(), y.flatten(), c2w, K)
    full = lambda key: torch.full((H, W), img_infos[key].flatten()[0].item(), dtype=img_infos[key].dtype, device="cuda")
    ii = {"origins": o.reshape(H, W, 3), "viewdirs": d.reshape(H, W, 3), "direction_norm": dn.reshape(H, W, 1),
          "img_idx": full("img_idx"), "frame_idx": full("frame_idx"), "normed_time": full("normed_time"),
          "pixel_coords": torch.stack([y / H, x / W], -1).float()}
    ci = {"camera_to_world": c2w, "intrinsics": K, "height": torch.tensor(H, device="cuda"), "width": torch.tensor(W, device="cuda")}
    with torch.no_grad():
        o_ = trainer(ii, ci, novel_view=True)
    rgb = o_["rgb"].clamp(0, 1).cpu().numpy()
    depth = o_["depth"][..., 0].cpu().numpy().astype(np.float32)
    depth[o_["opacity"][..., 0].cpu().numpy() < 0.5] = np.nan
    Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).save(f"{out}/{tok}.png")
    np.save(f"{out}/{tok}.depth.npy", depth)
    if n % 12 == 0:
        for layer in ("Background", "Dynamic"):
            if f"{layer}_rgb" in o_:
                Image.fromarray((o_[f"{layer}_rgb"].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)).save(f"{out}/layers/{tok}_{layer}.png")
    peak = max(peak, torch.cuda.max_memory_allocated() / 2**20)
print("exported", len(sp["views"]), "views; peak alloc MiB", round(peak))
