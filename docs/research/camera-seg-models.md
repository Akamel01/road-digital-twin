# Camera segmentation models for crosswalk, lane marking, curb and curb cut (issue #294, part of #293)

Question: which pretrained street-scene segmentation models label crosswalk (zebra), lane marking types, curb and curb cut/ramp, and what do they cost on one RTX 4070 SUPER 12 GB at 1600x900 (nuScenes camera size)? No weights were downloaded and no model was run. Every number below is quoted from the source named next to it, or marked **ESTIMATE**.

Research date: 2026-11-17. Researched by a Claude subagent.

## Bottom line

1. Every public Mapillary Vistas checkpoint found is trained on **Vistas v1.2 (65 classes)**, not v2.0 (124 classes). That is why the class lists below are identical across models.
2. v1.2 gives us `Crosswalk - Plain`, `Lane Marking - Crosswalk`, `Lane Marking - General`, `Curb`, `Curb Cut`, `Bike Lane`. It has **no lane-marking types** (no dashed/solid/zigzag/arrow/stop line) and **no class named ramp**. `Curb Cut` is the nearest to a ramp.
3. Lane-marking types exist only in Vistas **v2.0** labels (about 24 lane-marking classes). No public v2.0 weights were found. Getting types means fine-tuning on v2.0.
4. Weights are not clean to reuse commercially: Vistas data is CC BY-NC-SA 4.0, and the HF weights carry the tag `license: other`. Fine for the non-commercial research demo, and the site must say so.
5. No per-class IoU for our classes is published by the model authors. See section 5.

Recommended spike: Mask2Former Swin-L semantic (A), OneFormer ConvNeXt-L (B), and a v2.0 fine-tune of a smaller model only if the demo needs lane-marking types (F). Details at the end.

## 1. The class list (exact names)

Source: `id2label` in the HF `config.json` of `facebook/mask2former-swin-large-mapillary-vistas-semantic` (65 labels), cross-checked against the mmsegmentation `MapillaryDataset_v1` / `MapillaryDataset_v2` class lists ([mmseg mapillary.py](https://onedl-mmsegmentation.readthedocs.io/en/latest/_modules/mmseg/datasets/mapillary.html)). `facebook/maskformer-resnet50-vistas` and the Mask2Former panoptic config also have 65 labels (config.json read via the HF raw URL).

Relevant v1.2 classes (what the public weights output):

| Element | Class names in public weights (v1.2) |
|---|---|
| Crosswalk (zebra) | `Crosswalk - Plain` (the road surface patch), `Lane Marking - Crosswalk` (the painted stripes) |
| Lane marking | `Lane Marking - General` only (plus `Lane Marking - Crosswalk`) |
| Curb | `Curb` |
| Curb cut / ramp | `Curb Cut` (no class named ramp) |
| Related | `Bike Lane`, `Pedestrian Area`, `Sidewalk`, `Road`, `Service Lane`, `Parking`, `Manhole`, `Catch Basin`, `Pothole` |

Vistas v2.0 (124 classes, dataset labels only, no public weights found) adds, per the mmseg list: `Lane Marking - Dashed Line`, `- Straight Line`, `- Zigzag Line`, `- Ambiguous`, six arrow classes (`Left`, `Right`, `Straight`, `Other`, `Split Left or Straight`, `Split Right or Straight`), `- Give Way (Row)`, `- Give Way (Single)`, `- Hatched (Chevron)`, `- Hatched (Diagonal)`, `- Stop Line`, `- Symbol (Bicycle)`, `- Symbol (Other)`, `- Text`, `- Other`, four `Lane Marking (only) - ...` classes, plus `Driveway`, `Road Shoulder`, `Traffic Island`, `Lane Separator`, `Road Median`. Curb and curb cut stay as the same two classes; there is still no ramp class. The Mapillary announcement confirms 66 to 124 classes but names none ([Vistas 2.0 post](https://blog.mapillary.com/update/2021/01/18/vistas-2-dataset.html)).

Consequence for the twin: crosswalks, curbs and curb cuts are available now. Lane marking comes out as one blob class. Ramps must be inferred from `Curb Cut` (and `Driveway` in v2.0).

## 2. Candidates

All numbers in the "Quality" column are Vistas v1.2 val, whole-dataset, from the model authors' tables.

### A. Mask2Former, Swin-L (IN21k), Vistas semantic (recommended)

- Weights, HF Transformers format: <https://huggingface.co/facebook/mask2former-swin-large-mapillary-vistas-semantic> (safetensors, 216M params, 866 MB fp32 per the HF API).
- Original Detectron2 weights: `https://dl.fbaipublicfiles.com/maskformer/mask2former/mapillary_vistas/semantic/maskformer2_swin_large_IN21k_384_bs16_300k/model_final_90ee2d.pkl` ([MODEL_ZOO.md](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md)).
- Classes: the 65 above.
- Quality: 63.2 mIoU single-scale, 64.7 multi-scale+flip ([MODEL_ZOO.md](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md)). R50 variant: 57.4 / 59.0.
- Licence: code MIT ([repo README](https://github.com/facebookresearch/Mask2Former#license)). HF weights tagged `license: other`; the HF repo has no LICENSE file in its file list (checked via the HF API). Training data: Vistas, CC BY-NC-SA 4.0 (see section 4). Treat the weights as non-commercial.
- Cost: no VRAM or FPS number for Vistas is published; the paper trains with 1024x1024 crops and infers with the longer side resized to 2048 ([paper appendix B.3, arXiv 2112.01527](https://arxiv.org/abs/2112.01527)). A 1600x900 frame resized that way is about 2048x1152. **ESTIMATE**: roughly 4 to 7 GB VRAM in fp16/fp32 inference and about 0.5 to 1.5 s per frame on a 4070 SUPER, not measured. The spike must measure it.

### B. OneFormer, Vistas (Swin-L, ConvNeXt-L or DiNAT-L)

- Weights (SHI-Labs hosting, not on HF; no `shi-labs` Vistas model is on the HF hub, the HF API search for "mapillary" returns only the facebook Mask2Former/MaskFormer models):
  - Swin-L: `https://shi-labs.com/projects/oneformer/mapillary/250_16_swin_l_oneformer_mapillary_300k.pth`
  - ConvNeXt-L: `https://shi-labs.com/projects/oneformer/mapillary/250_16_convnext_l_oneformer_mapillary_300k.pth`
  - DiNAT-L: `https://shi-labs.com/projects/oneformer/mapillary/250_16_dinat_l_oneformer_mapillary_300k.pth`
  - Source: [OneFormer README](https://github.com/SHI-Labs/OneFormer).
- Classes: Vistas v1.2 (same label set; the README gives no class notes).
- Quality (README table, val): Swin-L PQ 46.7, mIoU 62.9 (ms+flip 64.1), 219M params. ConvNeXt-L PQ 47.9, mIoU 63.2 (63.8), 220M. DiNAT-L PQ 47.8, mIoU 64.0 (64.9), 223M.
- Licence: code MIT (OneFormer LICENSE file read). Weights: no separate licence statement found; same Vistas NC caveat. DiNAT-L needs the NATTEN library (extra build risk, from the README's backbone listing; not tested).
- Cost: no FLOPs/FPS column for Vistas. **ESTIMATE**: similar to A, slightly heavier, because of the extra text-query path. The OneFormer paper measures FPS on V100 only, for other datasets.
- Takeaway: about the same accuracy as A (within 1 mIoU). Its value is a second opinion for voting, not new classes. Prefer the ConvNeXt-L variant for the spike (no NATTEN).

### C. Mask2Former Swin-L, Vistas panoptic

- Weights: <https://huggingface.co/facebook/mask2former-swin-large-mapillary-vistas-panoptic> (216M params) and `.../panoptic/maskformer2_swin_large_IN21k_384_bs16_300k/model_final_132c71.pkl`.
- Quality: PQ 45.5, mIoU 60.8, 200 queries ([MODEL_ZOO.md](https://github.com/facebookresearch/Mask2Former/blob/main/MODEL_ZOO.md)).
- Same 65 classes, same licence position as A. Only useful if we want instance IDs for things (cars, people to mask out). For ground labels the semantic head (A) scores higher.

### D. MaskFormer ResNet-50, Vistas (light baseline)

- Weights: <https://huggingface.co/facebook/maskformer-resnet50-vistas> (65 labels incl. `Crosswalk - Plain`, checked in config.json; ResNet backbone). Also `onnx-community/maskformer-resnet50-vistas`.
- No metrics on the card and no licence declared in the API response. Cheapest to run (**ESTIMATE**: about 2 GB VRAM, well under 0.3 s per frame). Quality is below A. Use as a speed floor only.

### E. Mapillary Seamless Scene Segmentation (seamseg), ResNet-50

- Code and weights: <https://github.com/mapillary/seamseg>. Code BSD-3-Clause; pretrained weights CC BY-NC-SA 4.0 (README). One model: ResNet-50, Vistas, PQ 37.99. The README gives neither the Vistas version nor a class list, no speed or memory figures. Old (2019), weaker than A to D. Listed for completeness; not recommended.

### Considered and rejected

- **Bevandic et al., multi-domain universal segmentation** ([arXiv 2108.11224](https://arxiv.org/abs/2108.11224)). Its supplement says the universal label space recovers `crosswalk`, `zebra`, `road marking`, `bike lane`, `manhole`, `pothole`, `service lane`, and that zebras are seen only at close range and otherwise labelled road marking. No code link or released weights were found on the abstract page. Not usable.
- **Cityscapes/ADE20K-only models** (SegFormer, OneFormer HF Cityscapes/ADE): no crosswalk or curb-cut class (Cityscapes has 19 classes, e.g. SegFormer-B5 config has `road`, `sidewalk`, no markings).

## 3. VRAM and time summary

No source gives a measured VRAM or time for these checkpoints at 1600x900 on a 4070 SUPER. The only published timing method is the Mask2Former paper's V100, batch size 1 FPS, and it is not reported for Vistas. All cost figures in section 2 are therefore estimates. Spike step 1 is to measure peak VRAM and per-frame latency at 1600x900 (and at the 2048-long-side resize) for fp32 and fp16.

## 4. Licence chain

| Layer | Licence | Source |
|---|---|---|
| Mask2Former code | MIT (some parts MIT/Apache-2.0) | [README](https://github.com/facebookresearch/Mask2Former#license) |
| OneFormer code | MIT | OneFormer LICENSE file |
| seamseg code / weights | BSD-3-Clause / CC BY-NC-SA 4.0 | [seamseg README](https://github.com/mapillary/seamseg) |
| HF facebook Vistas weights | tag `license: other`, no LICENSE file in repo | HF API |
| Vistas training data | CC BY-NC-SA 4.0 (v2.0) | secondary: [Dataset Ninja](https://datasetninja.com/mapillary-vistas-dataset). The official Mapillary page could not be fetched (JS-only), and the 2017 ICCV paper is reported to say CC-BY-SA, so **confirm on the Mapillary download page before the spike goes public** |

Practical stance: demo is non-commercial, so use is acceptable. State on the site: "Segmentation by Mask2Former trained on Mapillary Vistas (CC BY-NC-SA 4.0, non-commercial)." Share-alike on derived labels is a risk to check if we publish the label rasters.

## 5. Per-class IoU for our classes

- Mask2Former and OneFormer publish only overall mIoU/PQ for Vistas, no per-class table (checked MODEL_ZOO.md, the OneFormer README, and the Mask2Former paper appendix B.3).
- One unverified lead: a 2020 *Sensors* paper table on Vistas semantic segmentation shows values that read as Curb Cut 14.7, Crosswalk - Plain 17.4, Lane Marking - Crosswalk 53.5 (mIoU 59.4). This came from a garbled search snippet, the page was blocked when fetched, and the model is not identified. Do not cite these numbers as results for A or B. They only suggest curb cut and plain crosswalk are weak classes while painted crosswalk stripes are decent.
- Therefore the spike must compute per-class IoU for `Curb`, `Curb Cut`, `Crosswalk - Plain`, `Lane Marking - Crosswalk`, `Lane Marking - General` on Vistas val, and also hand-label ~20 nuScenes boston-seaport frames, because Vistas is a different camera and city mix.

## 6. Recommendation for the spike

- **A. Mask2Former Swin-L Vistas semantic (HF).** Easiest install (Transformers, safetensors), best published balance (63.2 mIoU), all needed classes present. Baseline for everything else.
- **B. OneFormer ConvNeXt-L Vistas.** Independent architecture at the same accuracy; use its disagreement with A as a confidence signal when voting across frames. Needs the OneFormer repo and Detectron2 (not on HF).
- **F (conditional). Fine-tune on Vistas v2.0 for lane-marking types.** Only if the demo needs dashed/solid/arrow/stop-line. Vistas v2.0 is NC-licensed on download. Mask2Former Swin-L training likely will not fit 12 GB (**ESTIMATE**); start from the R50 Mask2Former config (57.4 mIoU on v1.2) or use a 1024 crop with small batch. This is a separate ticket with its own cost; keep it out of the first spike.
- Skip D and E except D as a speed floor. Skip panoptic (C) unless instance masks are wanted.

Open risks: v1.2 `Curb Cut` quality may be low (see section 5); the label for ramps does not exist; nuScenes Boston night and rain frames are far from Vistas daytime imagery; cost numbers are unmeasured.
