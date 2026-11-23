"""Sky masks for a drivestudio scene with HF SegFormer-B5 Cityscapes (stands in for the mmcv SegFormer env; class 10 = sky)."""
import glob
import os
import sys

import imageio.v2 as imageio
import numpy as np
import torch
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

scene = sys.argv[1]
name = "nvidia/segformer-b5-finetuned-cityscapes-1024-1024"
proc = SegformerImageProcessor.from_pretrained(name)
model = SegformerForSemanticSegmentation.from_pretrained(name).half().cuda().eval()
out = os.path.join(scene, "sky_masks")
os.makedirs(out, exist_ok=True)
files = sorted(glob.glob(os.path.join(scene, "images", "*.jpg")))
for i, f in enumerate(files):
    dst = os.path.join(out, os.path.basename(f)[:-4] + ".png")
    if os.path.exists(dst):
        continue
    im = imageio.imread(f)
    x = proc(images=im, return_tensors="pt")["pixel_values"].half().cuda()
    with torch.no_grad():
        logits = model(pixel_values=x).logits
        logits = torch.nn.functional.interpolate(logits.float(), size=im.shape[:2], mode="bilinear")
    sky = (logits.argmax(1)[0] == 10).cpu().numpy()
    imageio.imwrite(dst, sky.astype(np.uint8) * 255)
    if i % 200 == 0:
        print(i, len(files), float(sky.mean()), flush=True)
print("done", len(files))
