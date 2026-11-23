"""Render a trained SplatAD model at the harness held-out cameras (its eval split = the held-out keyframe images).

usage (inside the container): python export_splatad.py CONFIG_YML OUT_DIR
Writes <token>.png and <token>.depth.npy (expected z-depth, NaN where accumulation < 0.5) and, for every 12th view,
<token>_Background.png (actor Gaussians hidden) under OUT_DIR/layers/."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from nerfstudio.data.datamanagers import full_images_datamanager as _fidm
from nerfstudio.utils.eval_utils import eval_setup
from PIL import Image

# export never trains: skip caching ~1,400 training images (the 36 GB container ran out of RAM)
_orig_load = _fidm.FullImageDatamanager._load_images


class _BlankTrainImages:
    """Stands in for the train cache: seed-point painting only needs correctly sized images, and the loaded
    checkpoint overwrites the painted colours anyway."""

    def __init__(self, dataset):
        self.ds = dataset

    def __len__(self):
        return len(self.ds)

    def __getitem__(self, i):
        c = self.ds.cameras[i]
        return {"image": torch.zeros(int(c.height), int(c.width), 3, dtype=torch.uint8)}


def _load_images(self, split, *a, **k):
    return _BlankTrainImages(self.train_dataset) if split == "train" else _orig_load(self, split, *a, **k)


_fidm.FullImageDatamanager._load_images = _load_images

cfg_path, out = Path(sys.argv[1]), sys.argv[2]
os.makedirs(f"{out}/layers", exist_ok=True)
with open("/rv2/a1-split.json") as f:
    by_image = {v["image"]: v["token"] for v in json.load(f)["views"]}
def _cb(c):
    c.load_dir = cfg_path.parent / "nerfstudio_models"  # resumed runs keep the old load_dir in config.yml
    return c


_, pipe, _, _ = eval_setup(cfg_path, test_mode="test", update_config_callback=_cb)
model = pipe.model.eval()
ds = pipe.datamanager.eval_dataset
cams = ds.cameras
done = 0
for i in range(len(cams)):
    rel = str(ds.image_filenames[i]).split("/data/nuscenes/")[-1]
    tok = by_image.get(rel)
    if tok is None:
        continue
    cam = cams[i : i + 1]
    cam.height[:] = 900  # nuScenes parser crops the ego hood; render the full frame the harness scores
    cam.width[:] = 1600
    with torch.no_grad():
        o = model.get_outputs_for_camera(cam)
    rgb = o["rgb"].clamp(0, 1).cpu().numpy()
    depth = o["depth"][..., 0].float().cpu().numpy()
    depth[o["accumulation"][..., 0].cpu().numpy() < 0.5] = np.nan
    Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).save(f"{out}/{tok}.png")
    np.save(f"{out}/{tok}.depth.npy", depth.astype(np.float32))
    if done % 12 == 0:
        op = model.gauss_params["opacities"]
        keep = op.data.clone()
        op.data[model.id.squeeze(-1) >= 0] = -20.0
        with torch.no_grad():
            s = model.get_outputs_for_camera(cam)
        op.data.copy_(keep)
        Image.fromarray((s["rgb"].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)).save(f"{out}/layers/{tok}_Background.png")
    done += 1
print("exported", done, "of", len(cams), "eval cameras; peak alloc MiB", round(torch.cuda.max_memory_allocated() / 2**20))
