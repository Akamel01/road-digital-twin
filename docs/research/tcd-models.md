# Traffic-control-device (TCD) detection and MUTCD classification: commercially clean options (research only)

Research note for issue #259 (part of #257, blocks #263). No code change. Checked 2026-11-15 against primary pages (repo licence files, model cards, dataset pages, papers). "Not verified" means the primary page could not be read or did not state the point.

## Bottom line

1. **No ready-made, commercially clean model exists that outputs MUTCD codes.** No permissively licensed weights for US MUTCD classes were found. The only permissive "road sign" detector found (NVIDIA TrafficCamNet Transformer-Lite) has one generic `road sign` class and a licence that is not Apache/MIT (see table).
2. **No public US sign dataset with MUTCD labels is both commercially clean and sufficient.** LISA (academic licence), Mapillary MTSD (academic), BDD100K-MUTCD (images not cleared), LISA/Bosch/DTLD lights (NC or academic) are all out. GLARE is the one clean US sign dataset (CC BY 4.0, 2,157 images) but its classes are not confirmed.
3. **The MUTCD sign designs are public domain** (FHWA FAQ), so synthetic training data rendered from MUTCD templates is clean. This is the route that carries the weight.
4. **Recommendation: two stages, all Apache-2.0/MIT.** (a) Detector: RF-DETR Small/Medium (Apache-2.0 size, COCO-pretrained), fine-tuned to a few coarse classes (sign, signal head, optionally sign-plate subclass). (b) Classifier: small ImageNet/SigLIP-class backbone fine-tuned on MUTCD-template synthetic crops plus our own hand/VLM-assisted labels, giving code and speed value. Open-vocabulary models (Grounding DINO, OWLv2, Florence-2) are for bootstrapping labels, not for production classification.
5. **Hard blocker to raise on #257: nuScenes itself.** nuScenes is described by third-party and Motional sources as non-commercial (CC BY-NC-SA 4.0) with commercial use by separate licence. The official terms page could not be fetched, so this is not verified from the primary source. If the product is commercial, weights are not the only gate: images used for evaluation or pseudo-labels carry that licence too. Confirm with nuscenes@motional.com before treating any nuScenes-derived training data as clean.

## Licence ground rules used

- Weights licence and training-data licence both checked. Code under Apache does not clear data.
- Ultralytics (YOLOv5/8/11/12 and their weights) is AGPL-3.0 ([LICENSE](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)): excluded.
- Roboflow Universe re-uploads of NC datasets carry a CC BY 4.0 label that does not override the original owner's terms (example below): not trusted as a source.

## Detectors (architecture and pretrained weights)

All are COCO-pretrained, not traffic-sign-pretrained. They need fine-tuning on a clean dataset. COCO images are CC BY 2.0 Flickr, annotations CC BY 4.0 (COCO terms; not re-fetched here).

| Model | Weights/code licence | COCO AP / input / latency (T4 TRT FP16) | Fit in under 6 GB | Notes |
|---|---|---|---|---|
| RF-DETR N/S/M/L ([repo](https://github.com/roboflow/rf-detr)) | Apache-2.0 for N, S, M, L, all seg sizes. Atto/Femto/Pico/XL/2XL are PML 1.0 (not permissive for self-hosting) | N 48.4 / 384 / 2.3 ms; S 53.0 / 512 / 3.5 ms; M 54.7 / 576 / 4.4 ms; L 56.5 / 704 / 6.8 ms | Yes (30-34M params) | Best accuracy per size among Apache options. Use only N-L. Higher resolution (L, 704) helps small signs at 1600x900. |
| D-FINE ([repo](https://github.com/Peterande/D-FINE)) | Apache-2.0 | N 42.8 to X 55.8; L 54.0 / 31M / 8.07 ms | Yes | Do not use `*_obj365` checkpoints: README warns Objects365 terms may apply. Use COCO-only checkpoints. |
| DEIM / DEIMv2 ([repo](https://github.com/Intellindust-AI-Lab/DEIM)) | Apache-2.0 | D-FINE variant L 54.7 AP / 31M | Yes | Same Objects365 caution as D-FINE if those checkpoints are used. |
| RT-DETRv2 ([repo](https://github.com/lyuwenyu/RT-DETR)) | Apache-2.0 | S 48.1, M 51.9, L 53.4 AP; 108-217 FPS | Yes | Mature, plain choice. |
| NVIDIA TrafficCamNet Transformer-Lite ([NGC](https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/trafficcamnet_transformer_lite)) | NVIDIA Open Model License; page says ready for commercial use. Not Apache/MIT: counsel to read the licence | Input 544x960; classes car, road sign, person, bicycle | Yes | One generic `road sign` class, trained on NVIDIA's internal ITS dataset (data licence not stated). Detection only, no MUTCD code. Useful only as a baseline. |

## Open-vocabulary and VLM models (useful for bootstrapping labels)

| Model | Licence | Notes |
|---|---|---|
| Grounding DINO ([repo](https://github.com/IDEA-Research/GroundingDINO)) | Apache-2.0 code | COCO zero-shot 48.4 AP (Swin-T). Weights training data (Objects365, GoldG, Cap4M etc.) not licence-checked here: treat as unverified. Text prompts like "traffic sign" work; cannot output MUTCD codes reliably. |
| OWLv2 ([card](https://huggingface.co/google/owlv2-base-patch16-ensemble)) | Apache-2.0 | Fine-tuned on COCO and Open Images; CLIP backbone trained on web image-caption data (provenance not cleared). |
| Florence-2-large ([card](https://huggingface.co/microsoft/Florence-2-large)) | MIT | 0.77B params; detection, grounding, OCR (OCR helps read speed numbers). Training data (FLD-5B) licence not verified. |
| Qwen2.5-VL-7B-Instruct ([card](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)) | Apache-2.0 (7B). Note the 3B and 72B variants have different licences: not verified here | 8B params BF16 is about 16 GB, exceeds the 6 GB budget unless 4-bit quantised. Use offline on the box for label bootstrapping, not as the per-frame model. |
| Qwen3-VL-4B-Instruct ([card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)) | Apache-2.0 | 4B BF16 (about 8 GB), grounding claimed, no detection benchmark on card. 4-bit would fit. Unvalidated on MUTCD. |
| SigLIP 2 base ([card](https://huggingface.co/google/siglip2-base-patch16-224)) | Apache-2.0 | 0.4B params, trained on WebLI (Google internal). Candidate classifier backbone or zero-shot text matcher over MUTCD code names. |
| DINOv2 ([repo](https://github.com/facebookresearch/dinov2)) | Code and weights Apache-2.0 | Pretrained on 142M images, dataset not named on page. Backbone inside RF-DETR. |

Training-data provenance for large pretrained backbones (WebLI, LVD-142M, FLD-5B) is rarely a published licence. The strict reading of "training data must allow commercial use" cannot be fully verified for any of them. Flag for the operator: accept published model licences, or restrict to COCO/Open Images-derived weights.

## Datasets

| Dataset | Content | Licence | Usable? |
|---|---|---|---|
| GLARE ([repo](https://github.com/NicholasCG/GLARE_Dataset)) | 2,157 US dashcam sign images with sun glare, 33 videos | CC BY 4.0 | Yes. Classes, format, counts not stated on the repo page. Small. |
| MUTCD / FHWA sign designs ([FAQ](https://mutcd.fhwa.dot.gov/knowledge/faqs/faq_general.htm)) | Official sign figures | Public domain; reuse "without seeking permission from the FHWA" | Yes, for synthetic crops. Do not use third-party redraws (e.g. trafficsign.us claims copyright on its own drawings). |
| Open Images V7 ([facts](https://storage.googleapis.com/openimages/web/factsfigures_v7.html)) | Boxable classes `Traffic sign`, `Stop sign`, `Traffic light` | Annotations CC BY 4.0, images CC BY 2.0 (Google makes no per-image warranty) | Yes for coarse detection only. Not US-specific, no MUTCD codes. |
| LISA Traffic Signs ([UCSD](https://cvrr.ucsd.edu/lisa-traffic-signs-dataset)) | 47 US sign types, 6,610 frames, 7,855 annotations | "Academic license agreement" | No. Terms not shown on the page, so treat as not cleared. |
| Mapillary Traffic Sign Dataset ([paper](https://arxiv.org/abs/1909.04422)) | 100K images, 300+ classes, global | "Freely available for academic research" (the arXiv article itself is CC BY, the dataset is not) | No. Could not retrieve the licence text from mapillary.com (page did not render). Operator's note: CC BY-NC-SA. Either way excluded. |
| Roboflow Universe "mapillary traffic dataset" copy | Re-upload | Labelled CC BY 4.0 by uploader | No. Not the rights-holder; do not use. |
| BDD100K-MUTCD ([IEEE DataPort](https://ieee-dataport.org/documents/bdd100k-mutcd-fine-grained-human-verified-traffic-sign-type-annotations-bdd100k-dataset)) | 274,876 sign instances over 80,000 images, 38 MUTCD classes (14 speed values), 15,628 verified labels | Annotations CC BY 4.0, but images not redistributed; per-image attributes CC BY-NC 4.0; BDD100K data licence not verified (doc.bdd100k.com unreachable; the repo BSD-3 licence is for the toolkit code only). Needs IEEE DataPort subscription | No, unless BDD100K image terms are cleared by UC Berkeley (its Office of Technology Licensing is the stated commercial contact per a Hugging Face mirror, secondary). Best-shaped taxonomy to copy, though. |
| Augmented LISA Rural ([Zenodo](https://zenodo.org/records/15856539)) | Augmented LISA | CC BY-NC 1.0 | No. |
| LISA Traffic Lights ([HF mirror](https://huggingface.co/datasets/dronefreak/LISA-Traffic-Lights)) | 7 states (go, goLeft, stop, warning etc.) | CC BY-NC-SA 4.0 | No. |
| Bosch Small Traffic Lights | Lights | Non-commercial only per Heidelberg page (secondary summary) | No. |
| DriveU (DTLD) | Lights, Germany | "Academic" per survey (secondary) | No. |
| nuScenes (own data) | Boston Seaport, the target domain | Reported CC BY-NC-SA 4.0 / non-commercial (secondary sources; official terms not fetched) | Verify. Also has no traffic-sign or signal labels. |

Traffic signals: no commercially clean US signal-head dataset with state or layout labels was found. Open Images `Traffic light` gives a detector only. State (red/yellow/green, arrow) and head layout need our own labels or synthetic renders.

## Reported accuracy for the MUTCD task (primary paper)

- Sieverts et al., "Automated Road Asset Data Collection and Classification using Consumer Dashcams" ([PDF](https://users.cs.utah.edu/~tch/publications/pub323.pdf)): Faster R-CNN detector plus EfficientNet classifier over 600+ MUTCD classes, trained on Nashville dashcam data (98 classes, 1,578 labelled signs) plus 385,000 synthetic images from sign templates. Validation accuracy 0.994, but test accuracy on Utah DOT data only 0.47 (top-10 0.73). Takeaway: the synthetic-template route works on validation and loses roughly half on real data, so real-domain examples are required.
- GLARE paper: mixed-condition detectors reach average mAP50:95 of 42.3 on glare data (search summary; arXiv v2 reports lower baselines, versions differ).
- Mapillary paper: baselines on 300+ classes (academic data; not reusable).

No source reports MUTCD-code accuracy for the permissive detectors above on nuScenes-like imagery; that must be measured.

## Recommended pipeline

1. **Detect** with RF-DETR Small/Medium at 576 or higher (Apache-2.0). Classes: `sign`, `signal_head`. Fine-tune on Open Images (sign and light classes, CC BY) + GLARE + our own labelled nuScenes frames (subject to the nuScenes licence question).
2. **Classify** each sign crop with a compact classifier (ImageNet-class or SigLIP 2 base fine-tune) over MUTCD codes, with speed value via a second head or OCR (Florence-2, MIT). Train on synthetic crops from FHWA public-domain designs (heavy augmentation: blur, glare, perspective, occlusion, colour shift) plus real crops.
3. **Signals:** detect heads, then classify state and arrow from a small crop classifier. Labels must come from our own data.
4. **Bootstrap labels** offline on the box with Grounding DINO or a quantised Qwen VL, then human-review. The pseudo-labels are our own output, but check that any prompt output derived from a non-clean model does not carry an unwanted licence: unsettled, counsel to confirm.
5. **Memory:** RF-DETR S/M inference plus a small classifier is well under 2 GB. The VLM tools are batch-only.

## Fallback if the above is not good enough

Fine-tune on a larger own-labelled set: spend labelling effort (VLM pre-label, human review) on 1,000 to 3,000 real Boston and other US frames, reusing the 38-class taxonomy from BDD100K-MUTCD as a class list (taxonomy is a list of MUTCD codes, not copyrightable data, but confirm). If BDD100K images turn out to be licensable from UC Berkeley, that is the largest labelled US MUTCD source and should be reconsidered.

## Open items for #263

- Confirm nuScenes commercial terms with Motional (blocking if product is commercial).
- Decide the bar for pretrained-backbone data provenance (published model licence vs auditable training data).
- Obtain the GLARE class list and annotation format; fetch the BDD100K licence from bdd100k.com or bdd-data.berkeley.edu when reachable.
- Measure candidate detectors on a small hand-labelled nuScenes Boston sample.
