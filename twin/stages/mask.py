"""Stage 2 mask (boxes): remove points inside boxes; keep parked-vehicle points apart.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4 and 6 (Load and mask).
Input: load's points.npz and boxes.json (run CRS, boxes per sweep).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from twin.contracts import MaskParams, StageResult
from twin.parallel import pmap, savez_fast
from twin.registry import register
from twin.stages.load import quat_to_matrix

POINT_FIELDS = ("x", "y", "z", "intensity", "sweep")
OUTPUT_FILES = ("points.npz", "parked.npz")


def inside(xyz: np.ndarray, boxes: list[dict], margin: float) -> np.ndarray:
    """(N, B) bool: point n lies inside box b, with the box grown by `margin` on every side.

    Each point is moved into the box frame (inverse rotation about the centre), then tested
    against the half extents. Points and boxes are in the same CRS.
    """
    centres = np.array([b["center"] for b in boxes], dtype=float).reshape(-1, 3)
    rots = np.array([quat_to_matrix(b["rotation"]) for b in boxes], dtype=float)
    size = np.array([b["size"] for b in boxes], dtype=float).reshape(-1, 3)
    # DECISION: nuScenes size is [w, l, h] with length along the box's local x axis, so half extents are [l, w, h] / 2.
    half = size[:, [1, 0, 2]] / 2 + margin
    offset = xyz[:, None, :] - centres[None]  # (N, B, 3)
    local = np.einsum("nbj,bjk->nbk", offset, rots)  # R^T @ offset, per box
    return (np.abs(local) <= half[None]).all(axis=2)


def classify(
    xyz: np.ndarray, boxes: list[dict], margin: float
) -> tuple[np.ndarray, np.ndarray]:
    """For one sweep: (parked, dropped) masks over its points, and the parked box index (-1 if none).

    parked: inside at least one parked box. dropped: inside only non-parked boxes.
    Points inside neither are kept. A point in a parked box and a moving box goes to parked.
    """
    n = len(xyz)
    if not boxes:
        return np.zeros(n, bool), np.zeros(n, bool), np.full(n, -1, np.int32)
    hits = inside(xyz, boxes, margin)
    is_parked = np.array([bool(b["parked"]) for b in boxes], dtype=bool)
    in_parked = hits & is_parked[None]
    parked = in_parked.any(axis=1)
    dropped = hits.any(axis=1) & ~parked
    # DECISION: a point in a parked and a moving box goes to parked.npz; its box is the first parked box in that sweep's list.
    box_idx = np.where(parked, in_parked.argmax(axis=1), -1).astype(np.int32)
    return parked, dropped, box_idx


def _subset(fields: dict[str, np.ndarray], sel: np.ndarray) -> dict[str, np.ndarray]:
    return {k: v[sel] for k, v in fields.items()}


_JOB: tuple[dict, dict, float] | None = None  # read by forked workers


def _mask_sweep(s: int) -> tuple:
    fields, boxes_by_sweep, margin = _JOB  # type: ignore[misc]
    boxes = boxes_by_sweep.get(s, [])  # a box only applies to its own sweep
    if not boxes:
        e = np.zeros(0, bool)
        return np.zeros(0, np.intp), e, e, np.zeros(0, np.int32)
    sel = np.flatnonzero(fields["sweep"] == s)
    xyz = np.column_stack([fields["x"][sel], fields["y"][sel], fields["z"][sel]])
    return (sel, *classify(xyz, boxes, margin))


@register("mask", "boxes")
def run(ctx: Any, params: MaskParams) -> StageResult:
    src = ctx.input_dir("load")
    out: Path = ctx.stage_dir("mask")
    out.mkdir(exist_ok=True)

    with np.load(src / "points.npz") as f:
        fields = {k: f[k] for k in POINT_FIELDS}
    sweeps = json.loads((src / "boxes.json").read_text())["sweeps"]
    boxes_by_sweep = {int(s["sweep"]): s["boxes"] for s in sweeps}

    n = len(fields["x"])
    parked_all = np.zeros(n, bool)
    dropped_all = np.zeros(n, bool)
    box_all = np.full(n, -1, np.int32)
    global _JOB
    _JOB = (fields, boxes_by_sweep, params.box_margin_m)
    try:
        # Sweeps are independent; results come back in sweep order, so any worker count gives the same masks.
        done = pmap(_mask_sweep, np.unique(fields["sweep"]).tolist(), params.workers)
    finally:
        _JOB = None
    for sel, parked, dropped, idx in done:
        parked_all[sel] = parked
        dropped_all[sel] = dropped
        box_all[sel] = idx

    keep = ~(parked_all | dropped_all)
    savez_fast(out / "points.npz", **_subset(fields, keep))
    parked_fields = _subset(fields, parked_all)
    savez_fast(out / "parked.npz", **parked_fields, box=box_all[parked_all])

    n_parked = int(parked_all.sum())
    n_dropped = int(dropped_all.sum())
    return StageResult(
        status="ok",
        files=list(OUTPUT_FILES),
        metrics={
            "n_in": n_parked + n_dropped,
            "n_kept": int(keep.sum()),
            "n_parked": n_parked,
            "n_dropped_moving": n_dropped,
        },
    )
