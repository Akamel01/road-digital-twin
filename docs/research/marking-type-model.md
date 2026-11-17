# Marking-type model: data, model type, and training on the box (#306)

**Status:** research/comparison (M1). No dataset downloads, no terms acceptance, no training run performed in this ticket.  
**Scope:** compare route (a) camera fine-tune on Mapillary Vistas v2.0 vs route (b) BEV on Argoverse 2 (AV2) + nuScenes Boston; choose a primary route with reasons.

## 1. Goal and v1 output vocabulary

Label road paint by kind (paint semantics), not only "lane marking present" (Vistas v1.2). Target v1 kinds (contract for scorer/audit set, mapped to `twin/stages/features.MARKING_TYPES` later):

| Canonical kind | Maps to feature type |
|---|---|
| `solid_white` | `divider` |
| `dashed_white` | `divider` |
| `double_solid_white` | `divider` |
| `double_dashed_white` | `divider` |
| `stop_line` | `stop_line` |
| `arrow_left`, `arrow_right`, `arrow_straight`, `arrow_other` | `other_paint` |
| `text` | `other_paint` |
| `hatched` | `other_paint` |
| `crosswalk_stripes` | `crosswalk_stripe` |
| `unknown` / `none` | (no paint / unknown) |

Colour (yellow/blue) is a separate axis and **out of v1 scope** here: nuScenes Boston has essentially no yellow and AV2 yellow is rare in US cities we would use; v1 scores type, not colour.

## 2. Route comparison

| Criterion | **Route (a) — camera: Mapillary Vistas v2.0 fine-tune** (primary) | **Route (b) — BEV: AV2 + nuScenes Boston** (fallback, documented) |
|---|---|---|
| **What it is** | Pixel-wise segmentation of camera images, projected/voted to 10 cm cells via existing semantics stage path (`twin/stages/semantics.py` `vote`/`_visible`). **No public Vistas v2.0 weights exist**; fine-tune from a v1.2-pretrained backbone (e.g. Mask2Former R50/Swin-L v1.2 public weights on HF) onto Vistas v2.0 labels. | BEV/raster model over map-aligned grids using AV2 `LaneMarkType` and nuScenes Boston `lane_divider.segment_type` supervision; would need a new BEV projection/label-rendering path. |
| **Licence / terms** | Vistas v2.0 labels: **CC BY-NC-SA 4.0** (non-commercial, share-alike). v1.2 public weights (HF) tagged `license: other`; underlying Vistas data CC BY-NC-SA. **Operator-gated:** operator must accept Vistas v2.0 terms and download; agent never creates accounts or accepts terms. Any published derived labels/models carry non-commercial/share-alike risk — flag to operator/legal before publication. | AV2 Sensor: **CC BY-NC-SA 4.0**. nuScenes v1.0-trainval: Motional Terms of Use (non-commercial; registration required to obtain download links). OpenLane-V2 (derived, if used): CC BY-NC-SA 4.0, code Apache 2.0. Non-commercial/share-alike constraints apply. |
| **Download size (map-only / labels-first)** | v1.2 pretrained weights: ~866 MB (fp32, public HF). v2.0 label download size: **unverified here** (behind operator terms/download page). Map-only N/A (image segmentation dataset). | AV2: map files available via `s5cmd --no-sign-request` (no AWS account) — **map-only first, size unverified here** (small relative to sensor). nuScenes: meta 47 MB + maps 457 MB (on-box docs reference `/data/nuscenes`; not present in this worktree). |
| **Download size (with images/sensor)** | Vistas v2.0 images+labels: **unverified here** (operator download). Budget disk before download. | AV2 Sensor: ~1 TB extracted (no compressed size published). nuScenes v1.0-trainval: ~300 GB+ (full). **Do not download sensor/images until route chosen; stay map-first.** |
| **GPU / VRAM (RTX 4070 SUPER 12 GB)** | Mask2Former Swin-L full fine-tune **likely does not fit 12 GB**. Start from **Mask2Former R50** config or Swin-L at **1024 crop, batch 1–2, fp16, gradient checkpointing**; measure and report peak VRAM in run. | BEV raster models can be sized down, but VRAM depends on raster resolution/context; **unverified here**. Must fit 12 GB with batch sized to leftover memory; measure peak VRAM in run. |
| **Batch size (expected starting point)** | 1–2 (fp16, grad checkpointing) on R50/1024-crop; tune only if VRAM headroom measured. | 1+ small rasters; **unverified here**, bounded by 12 GB. |
| **Seconds/frame/epoch & expected training time** | **Unverified (no box/GPU access in this worktree; no run performed).** Must be measured on box and reported as: sec/frame, sec/epoch, wall time to first useful checkpoint, peak VRAM. | **Unverified (no run performed).** Must be measured and reported with same fields. |
| **Time to first useful checkpoint** | **Unverified.** Defined by plateau/useful-floor rule below; report wall time when measured. | **Unverified.** Same reporting requirement. |
| **Supervised class coverage** | **Full v1 paint vocabulary** available in Vistas v2.0 labels (~24 lane-marking classes including solid/dashed/double/stop line/arrow/text/hatched/crosswalk context). Best coverage for requested kinds without hand labels. | **Partial:** AV2 `LaneMarkType` covers lane-boundary paint (14 types) but **no stop bars, no arrows, no hatching, no text**. nuScenes Boston gives crosswalks/dividers/stop lines but paint type only via `lane_divider.segment_type`; **yellow essentially absent**. Full v1 vocabulary would still need hand labels outside audit set. |
| **Domain gap (showcase Boston)** | Trained on global street imagery; domain shift to Boston/showcase possible but camera semantics reuse existing per-view voting/z-buffer projection. Prefer evaluation/fine-tune data from in-domain Boston patches (outside held-out box) when available. | nuScenes Boston is in-domain (467 scenes) — strong domain match for Boston patches **outside held-out box**. AV2 cities differ; Singapore/left-hand-traffic data secondary due to domain gap. |
| **Integration / reuse** | **Drops into existing semantics stage** (`Mask2Former` + `vote`/`_visible`, hard labels to 10 cm cells) with a model/method swap; no new projection code. | Requires BEV raster rendering/projection and different consumption path; higher integration cost and new failure modes. |
| **Data access** | Labels/terms **operator-gated** (HITL). Public v1.2 weights downloadable without dataset account. | AV2 downloadable without AWS account (`s5cmd --no-sign-request`). nuScenes requires registration/ToU acceptance for download links (HITL). |

## 3. Chosen route (primary) and reasons

**Primary: Route (a) — Mapillary Vistas v2.0 fine-tune (camera).**

Reasons:
1. **Vocabulary coverage:** only Vistas v2.0 labels supervise the full requested v1 paint vocabulary (solid/dashed/double/stop line/arrow/text/hatched/crosswalk stripes). Route (b) cannot supervise stop bars/arrows/hatching/text from AV2 alone and would leave gaps requiring hand labels.
2. **Reuse of existing pipeline:** route (a) slots into the existing semantics projection/voting path (`twin/stages/semantics.py`, #296 z-buffer top-5 views + saved poses) — model swap, no new BEV projection code.
3. **Swappable interface:** `twin/marking_types` loader/`kind_to_feature_type` mapping keeps trainer route-agnostic; semantics can consume a probability/class raster either way, so switching later does not force downstream rewrite.
4. **Practical availability:** v1.2 pretrained weights are public; v2.0 labels require operator terms acceptance (HITL, documented) but no invented access — a bounded, explicit gate.

**Fallback: Route (b) — BEV on AV2 + nuScenes Boston (documented, not built in #306).**  
Rationale for keeping as fallback: AV2 map/sensor accessible without AWS account (`s5cmd --no-sign-request`), nuScenes Boston is in-domain for the showcase, and BEV uses map geometry directly. Fall back to (b) only if camera per-class IoU is below the useful floor (mIoU < 0.4 on held-out paint classes) after plateau, or if v2.0 label access/quality proves blocking.

## 4. Held-out showcase area (excluded from training)

**Showcase bbox (EPSG:32619):** `x 332112–332668`, `y 4689895–4690292`.  
This area **must be excluded from every training patch by construction** (enforced in the data loader; loader must raise/error on intersection). A buffer around this box must be applied (buffer size to be finalized in implementation/loader config, default non-zero) so no training sample touches showcase vicinity. nuScenes map coordinates are local metres per map — transforming the showcase bbox into nuScenes local coordinates via map origin is a **requirement for the real adapter** (not implemented in #306); the loader must raise on intersection. Prefer Boston patches outside the box over Singapore (domain gap: left-hand traffic).

## 5. Operator-gated box training (HITL)

- **Box training is operator-gated:** Vistas v2.0 dataset requires terms acceptance/download by the operator. Agent must **never create accounts, accept terms, or bypass access controls**.
- nuScenes download links require Motional registration/ToU acceptance (operator action) if obtained.
- GPU training-first until 2026-12-07; use `twin/gpulease.py` lease; never stop `sme_*` containers. Batch sized to leftover memory. Training deps optional (`marking` group); core `import twin` stays cheap.
- Disk gates: datasets under `/data` only (never repo/root). Hold job if `/` < 10 GB or `/data` < 50 GB. Check before/after downloads.
- Training script is **not run in CI**; CI uses synthetic-data smoke tests only (no datasets/GPU required).

## 6. Plateau stop and escalation

- **Plateau stop:** end training after **3 consecutive evaluations with < 0.5 mIoU gain** (averaged over evaluated paint classes) — write `plateau.json` with the eval history and stop (no automatic continuation).
- **Escalate (do not add epochs):** if model is below a useful floor (**mIoU < 0.4** on held-out paint classes) at plateau, stop and escalate (consider fallback route (b) or data/label remediation) rather than continuing to train.
- Hold-out for validation must exclude the showcase bbox above; prefer in-domain Boston patches outside the box.

## 7. Per-class validation table schema

Each training/eval run must emit a per-class validation table (CSV or JSON rows) with at least:

| Field | Type | Description |
|---|---|---|
| `run_id` | string | run/checkpoint identifier |
| `route` | string | `camera` or `bev` |
| `eval_index` | int | evaluation sequence number (for plateau tracking) |
| `dataset` | string | validation source(s), version/split |
| `heldout_bbox_epsg32619` | string/object | bbox excluded (x/y ranges) + buffer used |
| `class` | string | canonical kind (e.g. `solid_white`, `stop_line`, …) |
| `support_pixels` (or `instances`) | int | count supporting the metric |
| `iou` | float | per-class IoU on held-out data |
| `precision` | float | optional but recommended |
| `recall` | float | optional but recommended |
| `miou_eval_classes` | float | mean IoU over evaluated paint classes for this eval |
| `delta_miou_vs_prev` | float/null | gain vs previous eval (for plateau rule) |
| `peak_vram_mib` | int | measured peak GPU memory |
| `wall_time_s` | float | cumulative/wall time to this eval/checkpoint |
| `sec_per_frame` | float/null | measured throughput if available |
| `sec_per_epoch` | float/null | measured epoch time if available |
| `checkpoint_path` | string | path under `--out` (e.g. `/data/models/marking-type/...`) |
| `manifest_path` | string | `data_manifest.json` path (dataset/version/paths/held-out box/counts/seed) |
| `notes` | string | e.g. backbone/crop/batch/fp16 flags |

Alongside: `data_manifest.json`, `LICENCES`, and `plateau.json` (when plateau/stop triggered). No dataset files committed to repo.

## 8. Constraints and non-goals (#306)

- **No false claims:** Vistas v2.0 has **no public weights**; route (a) is fine-tune from **v1.2-pretrained** backbone on v2.0 labels. Sizes/timings/VRAM marked unverified above until measured on box.
- **Held-out by construction:** showcase bbox excluded in loader with test.
- **Operator-gated:** terms acceptance/download/accounts are human actions only.
- **Out of scope:** BEV implementation, scoring on dev/audit sites, integration into features stage, curb/ramp model, colour axis decision. Follow-up ticket gated on passing plateau + approved method.

## 9. Evidence sources (repo)

- Discovery/architecture/grilling: `.autoforge/discovery/report.md`, `.autoforge/architecture/report.md`, `.autoforge/requirements/grilling.md`, `.autoforge/plans/plan.md`.
- Existing code/contracts: `twin/stages/semantics.py`, `twin/stages/features.py` (`MARKING_TYPES`), `twin/stages/accuracy.py`, `twin/gpulease.py`.
- Prior research context: #294/#295/#296/#305 as summarized in tracker; `docs/research/` (no prior marking-type-model doc in this worktree at time of writing).
