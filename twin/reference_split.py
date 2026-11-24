"""Deterministic reference/holdout split for evaluation features.

Splits a list of GeoJSON-like feature dicts into an anchor set and a held-out set
using a stable hash of each feature's ``element_id`` (layer:token). The split is
reproducible across runs and machines.
"""

from __future__ import annotations

import hashlib
from typing import Any


def element_id(feat: dict[str, Any]) -> str:
    props = feat["properties"]
    layer = props.get("layer", "")
    token = props.get("token", props.get("id", ""))
    if token is None:
        token = ""
    return f"{layer}:{token}"


def is_anchor(feat: dict[str, Any], ratio: float = 0.7) -> bool:
    value = int(hashlib.sha256(element_id(feat).encode("utf-8")).hexdigest(), 16) % 1000
    return value < int(ratio * 1000)


def split_reference(features: list[dict[str, Any]], ratio: float = 0.7):
    anchors = [f for f in features if is_anchor(f, ratio)]
    heldout = [f for f in features if not is_anchor(f, ratio)]
    counts_by_layer: dict[str, int] = {}
    for f in features:
        layer = f["properties"]["layer"]
        counts_by_layer[layer] = counts_by_layer.get(layer, 0) + 1
    heldout_ids = sorted(element_id(f) for f in heldout)
    meta = {
        "ratio": ratio,
        "method": "sha256-mod-1000",
        "n_total": len(features),
        "n_anchor": len(anchors),
        "n_heldout": len(heldout),
        "counts_by_layer": counts_by_layer,
        "heldout_ids": heldout_ids,
        "holdout": True,
    }
    return anchors, heldout, meta
