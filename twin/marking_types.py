"""Canonical marking kinds and dataset adapters for the marking-type model.

Dependency-light: ``torch``/``transformers`` are imported lazily inside functions
so ``import twin.marking_types`` stays cheap and CI-safe.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from twin.stages.features import MARKING_TYPES

# Held-out showcase bbox in EPSG:32619 (x_min, x_max, y_min, y_max).
HOLDOUT_BBOX_DEFAULT: tuple[int, int, int, int] = (332112, 332668, 4689895, 4690292)


class KINDS(enum.StrEnum):
    SOLID_WHITE = "solid_white"
    DASHED_WHITE = "dashed_white"
    DOUBLE_SOLID_WHITE = "double_solid_white"
    DOUBLE_DASHED_WHITE = "double_dashed_white"
    STOP_LINE = "stop_line"
    ARROW_LEFT = "arrow_left"
    ARROW_RIGHT = "arrow_right"
    ARROW_STRAIGHT = "arrow_straight"
    ARROW_OTHER = "arrow_other"
    TEXT = "text"
    HATCHED = "hatched"
    CROSSWALK_STRIPES = "crosswalk_stripes"
    UNKNOWN = "unknown"
    NONE = "none"


# Canonical kinds defined once; re-export as a tuple of strings for convenience.
KIND_VALUES: tuple[str, ...] = tuple(k.value for k in KINDS)


class HoldoutViolation(ValueError):
    """Raised when a sample intersects the held-out showcase bbox."""


@dataclass
class Sample:
    image: Any = None
    mask: Any = None
    source: str = ""
    scene_id: str = ""
    bbox: tuple[float, float, float, float] | None = None  # (x_min, x_max, y_min, y_max)
    meta: dict = field(default_factory=dict)


def _bbox_from_holdout(holdout_bbox: Any) -> tuple[float, float, float, float]:
    if isinstance(holdout_bbox, Mapping):
        return (
            float(holdout_bbox["x_min"]),
            float(holdout_bbox["x_max"]),
            float(holdout_bbox["y_min"]),
            float(holdout_bbox["y_max"]),
        )
    if isinstance(holdout_bbox, (tuple, list)) and len(holdout_bbox) == 4:
        # accept (x_min, x_max, y_min, y_max) or (xmin, ymin, xmax, ymax)?
        # Contract uses x_min,x_max,y_min,y_max.
        return (float(holdout_bbox[0]), float(holdout_bbox[1]),
                float(holdout_bbox[2]), float(holdout_bbox[3]))
    raise ValueError(f"invalid holdout_bbox: {holdout_bbox!r}")


def intersects_holdout(
    bbox: Any,
    holdout_bbox: Any = None,
    buffer: float = 50.0,
) -> bool:
    """Return True if ``bbox`` intersects ``holdout_bbox`` (+buffer).

    Bounding boxes use the ``(x_min, x_max, y_min, y_max)`` convention.
    Unsupported bbox types, missing bboxes, and ``None`` raise
    :class:`HoldoutViolation` instead of being silently treated as
    non-intersecting (fail-closed).
    """
    if holdout_bbox is None:
        holdout_bbox = HOLDOUT_BBOX_DEFAULT
    hx0, hx1, hy0, hy1 = _bbox_from_holdout(holdout_bbox)
    hx0 -= buffer; hx1 += buffer; hy0 -= buffer; hy1 += buffer

    if bbox is None:
        raise HoldoutViolation("bbox is None; cannot verify holdout exclusion")
    if isinstance(bbox, Sample):
        if bbox.bbox is None:
            raise HoldoutViolation(
                f"sample {bbox.scene_id!r} has no bbox; cannot verify holdout exclusion"
            )
        return intersects_holdout(bbox.bbox, holdout_bbox, buffer)

    # point form / bbox form: tuple or list of numbers
    if isinstance(bbox, (tuple, list)):
        if len(bbox) == 2:
            x, y = float(bbox[0]), float(bbox[1])
            return hx0 <= x <= hx1 and hy0 <= y <= hy1
        if len(bbox) == 4:
            x0, x1, y0, y1 = (float(bbox[0]), float(bbox[1]),
                               float(bbox[2]), float(bbox[3]))
            # Convention: (x_min, x_max, y_min, y_max). Swap only if reversed.
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0
            return not (x1 < hx0 or x0 > hx1 or y1 < hy0 or y0 > hy1)
        raise HoldoutViolation(f"unsupported bbox length {len(bbox)}: {bbox!r}")

    if isinstance(bbox, Mapping):
        if "x" in bbox and "y" in bbox and "x_min" not in bbox:
            return intersects_holdout((bbox["x"], bbox["y"]), holdout_bbox, buffer)
        if "x_min" in bbox and "x_max" in bbox and "y_min" in bbox and "y_max" in bbox:
            return intersects_holdout(
                (bbox["x_min"], bbox["x_max"], bbox["y_min"], bbox["y_max"]),
                holdout_bbox, buffer,
            )
        raise HoldoutViolation(f"unsupported bbox mapping keys: {bbox!r}")

    raise HoldoutViolation(f"unsupported bbox type {type(bbox).__name__}: {bbox!r}")


def in_holdout(
    x: float,
    y: float,
    holdout_bbox: Any = None,
    buffer: float = 50.0,
) -> bool:
    return intersects_holdout((x, y), holdout_bbox, buffer)


def enforce_holdout(sample: Sample, holdout_bbox: Any, buffer: float = 50.0) -> None:
    if intersects_holdout(sample, holdout_bbox, buffer):
        raise HoldoutViolation(
            f"sample {sample.scene_id!r} intersects held-out bbox"
        )


# Source -> canonical kind maps.

VISTAS_V2_LABEL_TO_KIND: dict[str, str] = {}
_vistas_map = {
    "Lane Marking - Straight Line": KINDS.SOLID_WHITE,
    "Lane Marking - Dashed Line": KINDS.DASHED_WHITE,
    "Lane Marking - Zigzag Line": KINDS.HATCHED,
    "Lane Marking - Crosswalk": KINDS.CROSSWALK_STRIPES,
    "Lane Marking - Stop Line": KINDS.STOP_LINE,
    "Lane Marking - Arrow (Left)": KINDS.ARROW_LEFT,
    "Lane Marking - Arrow (Right)": KINDS.ARROW_RIGHT,
    "Lane Marking - Arrow (Straight)": KINDS.ARROW_STRAIGHT,
    "Lane Marking - Arrow (Other)": KINDS.ARROW_OTHER,
    "Lane Marking - Arrow (Ambiguous)": KINDS.ARROW_OTHER,
    "Lane Marking - Arrow (Split Left or Straight)": KINDS.ARROW_OTHER,
    "Lane Marking - Arrow (Split Right or Straight)": KINDS.ARROW_OTHER,
    "Lane Marking - Arrow (Split Left or Right)": KINDS.ARROW_OTHER,
    "Lane Marking - Arrow (Split Left or Right or Straight)": KINDS.ARROW_OTHER,
    "Lane Marking - Arrow (U-Turn)": KINDS.ARROW_OTHER,
    "Lane Marking - Hatched (Chevron)": KINDS.HATCHED,
    "Lane Marking - Hatched (Diagonal)": KINDS.HATCHED,
    "Lane Marking - Text": KINDS.TEXT,
    "Lane Marking - Text (Other)": KINDS.TEXT,
    "Lane Marking - Text (Stop)": KINDS.TEXT,
    "Lane Marking - Text (Slow)": KINDS.TEXT,
    "Lane Marking - Text (Bus)": KINDS.TEXT,
    "Lane Marking - Text (School)": KINDS.TEXT,
    "Lane Marking - Text (Taxi)": KINDS.TEXT,
    "Lane Marking - Text (30)": KINDS.TEXT,
    "Lane Marking - Text (40)": KINDS.TEXT,
    "Lane Marking - Text (50)": KINDS.TEXT,
    "Lane Marking - Text (Ambiguous)": KINDS.UNKNOWN,
    "Lane Marking - Symbol (Bicycle)": KINDS.ARROW_OTHER,
    "Lane Marking - Symbol (Other)": KINDS.UNKNOWN,
    "Lane Marking - Symbol (Ambiguous)": KINDS.UNKNOWN,
    "Lane Marking - Give Way (Row)": KINDS.UNKNOWN,
    "Lane Marking - Give Way (Single)": KINDS.UNKNOWN,
    "Lane Marking - Ambiguous": KINDS.UNKNOWN,
    "Lane Marking - Other": KINDS.UNKNOWN,
    "Lane Marking (only) - Dashed Line": KINDS.DASHED_WHITE,
    "Lane Marking (only) - Crosswalk": KINDS.CROSSWALK_STRIPES,
    "Lane Marking (only) - Other": KINDS.UNKNOWN,
}
for k, v in _vistas_map.items():
    VISTAS_V2_LABEL_TO_KIND[k] = v.value


def _nu_value(v: str) -> str:
    return str(v).strip().lower()


NU_SCENES_SEGMENT_TYPE_TO_KIND: dict[str, str] = {
    "solid": KINDS.SOLID_WHITE.value,
    "dashed": KINDS.DASHED_WHITE.value,
    "double solid": KINDS.DOUBLE_SOLID_WHITE.value,
    "double dashed": KINDS.DOUBLE_DASHED_WHITE.value,
    "solid solid": KINDS.DOUBLE_SOLID_WHITE.value,
    "dashed dashed": KINDS.DOUBLE_DASHED_WHITE.value,
    "stop line": KINDS.STOP_LINE.value,
    "stop_line": KINDS.STOP_LINE.value,
    "crosswalk": KINDS.CROSSWALK_STRIPES.value,
    "arrow": KINDS.ARROW_OTHER.value,
    "text": KINDS.TEXT.value,
    "hatched": KINDS.HATCHED.value,
    "unknown": KINDS.UNKNOWN.value,
    "none": KINDS.NONE.value,
}


AV2_LANE_MARK_TYPE_TO_KIND: dict[str, str] = {}


def _av2_map_one(name: str) -> str:
    n = str(name).upper()
    if "DOUBLE" in n and "DASH" in n:
        return KINDS.DOUBLE_DASHED_WHITE.value
    if "DOUBLE" in n and "SOLID" in n:
        return KINDS.DOUBLE_SOLID_WHITE.value
    if "DASH" in n:
        return KINDS.DASHED_WHITE.value
    if "SOLID" in n:
        return KINDS.SOLID_WHITE.value
    if "STOP" in n:
        return KINDS.STOP_LINE.value
    if "CROSSWALK" in n or "ZEBRA" in n:
        return KINDS.CROSSWALK_STRIPES.value
    if "ARROW" in n:
        if "LEFT" in n:
            return KINDS.ARROW_LEFT.value
        if "RIGHT" in n:
            return KINDS.ARROW_RIGHT.value
        if "STRAIGHT" in n:
            return KINDS.ARROW_STRAIGHT.value
        return KINDS.ARROW_OTHER.value
    if "TEXT" in n:
        return KINDS.TEXT.value
    if "HATCH" in n or "CHEVRON" in n:
        return KINDS.HATCHED.value
    if "UNKNOWN" in n:
        return KINDS.UNKNOWN.value
    return KINDS.UNKNOWN.value


# Populate AV2 map with known LaneMarkType values (best effort).
_av2_known = [
    "SOLID_WHITE", "SOLID_YELLOW", "SOLID_BLUE",
    "DASHED_WHITE", "DASHED_YELLOW", "DASHED_BLUE",
    "DOUBLE_SOLID_WHITE", "DOUBLE_SOLID_YELLOW", "DOUBLE_SOLID_BLUE",
    "DOUBLE_DASHED_WHITE", "DOUBLE_DASHED_YELLOW", "DOUBLE_DASHED_BLUE",
    "UNKNOWN",
]
for _name in _av2_known:
    AV2_LANE_MARK_TYPE_TO_KIND[_name] = _av2_map_one(_name)


def map_source_to_kind(source: str, label: Any) -> str:
    """Map a source-specific label to a canonical kind string."""
    s = str(source).lower()
    if "vistas" in s:
        return VISTAS_V2_LABEL_TO_KIND.get(str(label), KINDS.UNKNOWN.value)
    if "nuscenes" in s or "nu_scenes" in s:
        return NU_SCENES_SEGMENT_TYPE_TO_KIND.get(_nu_value(label), KINDS.UNKNOWN.value)
    if "av2" in s or "argoverse" in s:
        return AV2_LANE_MARK_TYPE_TO_KIND.get(str(label), _av2_map_one(str(label)))
    raise ValueError(f"unknown source: {source}")


# kind -> features.MARKING_TYPES
_FEATURE_TYPES: dict[KINDS, str | None] = {
    KINDS.SOLID_WHITE: "divider",
    KINDS.DASHED_WHITE: "divider",
    KINDS.DOUBLE_SOLID_WHITE: "divider",
    KINDS.DOUBLE_DASHED_WHITE: "divider",
    KINDS.STOP_LINE: "stop_line",
    KINDS.ARROW_LEFT: "other_paint",
    KINDS.ARROW_RIGHT: "other_paint",
    KINDS.ARROW_STRAIGHT: "other_paint",
    KINDS.ARROW_OTHER: "other_paint",
    KINDS.TEXT: "other_paint",
    KINDS.HATCHED: "other_paint",
    KINDS.CROSSWALK_STRIPES: "crosswalk_stripe",
    KINDS.UNKNOWN: None,
    KINDS.NONE: None,
}


def kind_to_feature_type(kind: Any) -> str | None:
    if isinstance(kind, KINDS):
        k = kind
    else:
        k = KINDS(str(kind))
    result = _FEATURE_TYPES[k]
    if result is not None and result not in MARKING_TYPES:
        raise ValueError(f"feature type {result!r} not in MARKING_TYPES")
    return result


KIND_TO_FEATURE_TYPE: dict[KINDS, str | None] = dict(_FEATURE_TYPES)

# Validate feature-type values against the canonical MARKING_TYPES.
_feature_values = {v for v in _FEATURE_TYPES.values() if v is not None}
assert _feature_values <= set(MARKING_TYPES), (
    f"kind_to_feature_type values {_feature_values} not subset of MARKING_TYPES {set(MARKING_TYPES)}"
)

def _vistas_config_labels(config: Any) -> list[dict[str, Any]]:
    if isinstance(config, list):
        items = config
    elif isinstance(config, Mapping):
        for key in ("labels", "classes", "class_names", "categories"):
            if key in config and isinstance(config[key], list):
                items = config[key]
                break
        else:
            # Some configs map id -> name directly.
            items = [{"id": k, "name": v} for k, v in config.items()
                     if not isinstance(v, (list, dict))]
    else:
        items = []
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            out.append(dict(item))
        elif isinstance(item, str):
            out.append({"id": None, "name": item})
    return out


def _label_name(item: Mapping[str, Any]) -> str:
    for key in ("name", "label", "class_name", "title"):
        if key in item and item[key] is not None:
            return str(item[key])
    return ""


def _label_id(item: Mapping[str, Any]) -> Any:
    for key in ("id", "label_id", "class_id", "index"):
        if key in item and item[key] is not None:
            return item[key]
    return None


def _is_bbox_holdout(holdout: Any) -> bool:
    if holdout is None:
        return False
    if isinstance(holdout, Mapping):
        return ("x_min" in holdout and "x_max" in holdout
                and "y_min" in holdout and "y_max" in holdout)
    if isinstance(holdout, (tuple, list)) and len(holdout) == 4:
        return all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in holdout)
    return False


def load_vistas_v2_samples(
    split: str = "training",
    root: Any = "/data/vistas",
    holdout: Any = None,
) -> Iterator[Sample]:
    """Yield :class:`Sample` objects for a Mapillary Vistas v2.0 split.

    Layout::

        {root}/{training,validation}/images/*.jpg
        {root}/{training,validation}/v2.0/labels/*.png
        {root}/config_v2.0.json

    Class names/ids come from ``config_v2.0.json``; canonical kinds are
    derived from those names via :data:`VISTAS_V2_LABEL_TO_KIND` (not from
    hard-coded ids). ``holdout`` may be a bbox (applied only to samples that
    carry a bbox) or a collection of held-out image filenames/stems.
    """
    from pathlib import Path

    root_path = Path(root if root is not None else "/data/vistas")
    split = str(split)
    split_dir = root_path / split
    img_dir = split_dir / "images"
    label_dir = split_dir / "v2.0" / "labels"

    config_path = root_path / "config_v2.0.json"
    config: Any = {}
    if config_path.exists():
        import json
        config = json.loads(config_path.read_text())
    id_to_kind: dict[Any, str] = {}
    for item in _vistas_config_labels(config):
        name = _label_name(item)
        kind = VISTAS_V2_LABEL_TO_KIND.get(name, KINDS.UNKNOWN.value)
        lid = _label_id(item)
        if lid is not None:
            id_to_kind[lid] = kind
        # Also allow name-based lookup for configs without ids.
        id_to_kind[name] = kind

    # Normalise holdout filename collection.
    holdout_files: set[str] = set()
    if holdout is not None and not _is_bbox_holdout(holdout):
        if isinstance(holdout, (str, Path)):
            holdout_files.add(str(holdout))
        else:
            try:
                for h in holdout:
                    holdout_files.add(str(h))
            except TypeError:
                holdout_files.add(str(holdout))

    bbox_holdout = holdout if _is_bbox_holdout(holdout) else None

    if not img_dir.exists():
        return
    for img_path in sorted(img_dir.glob("*.jpg")):
        stem = img_path.stem
        if stem in holdout_files or img_path.name in holdout_files:
            continue
        label_path = label_dir / f"{stem}.png"
        sample = Sample(
            image=str(img_path),
            mask=str(label_path),
            source="vistas_v2",
            scene_id=stem,
            bbox=None,
            meta={
                "split": split,
                "image_path": str(img_path),
                "label_path": str(label_path),
                "class_id_to_kind": dict(id_to_kind),
                "id_to_kind": dict(id_to_kind),
                "canonical_kind_map": dict(id_to_kind),
                "canonical_kind_mask": id_to_kind,
            },
        )
        if sample.bbox is not None and bbox_holdout is not None:
            try:
                enforce_holdout(sample, bbox_holdout)
            except HoldoutViolation:
                continue
        # Also support holdout default? Only if bbox present; none here.
        yield sample



def load_samples(
    route: str,
    root: Any,
    holdout_bbox: Any = None,
    buffer: float = 50.0,
) -> Iterator[Sample]:
    """Iterator over ``Sample`` for a dataset route.

    Adapters are intentionally minimal here (no torch import at module load).
    Real dataset reading happens lazily; this function validates holdout on
    any sample that carries a bbox.
    """
    if holdout_bbox is None:
        holdout_bbox = HOLDOUT_BBOX_DEFAULT
    # Lazy import of torch/transformers would happen inside a real adapter.
    # _ = _lazy_torch()  # placeholder hook
    route = str(route).lower()
    if route not in ("camera", "bev"):
        raise ValueError(f"unknown route: {route}")
    # No datasets shipped; yield nothing. Adapters plug in here.
    for sample in _adapter(route, root):
        enforce_holdout(sample, holdout_bbox, buffer)
        yield sample


def _adapter(route: str, root: Any) -> Iterator[Sample]:
    return iter(())


def _lazy_torch():
    import torch
    return torch


def _lazy_transformers():
    import transformers
    return transformers