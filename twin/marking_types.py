"""Canonical marking kinds and dataset adapters for the marking-type model.

Dependency-light: ``torch``/``transformers`` are imported lazily inside functions
so ``import twin.marking_types`` stays cheap and CI-safe.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

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
    buffer: float = 0.0,
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
    return _FEATURE_TYPES[k]


KIND_TO_FEATURE_TYPE: dict[KINDS, str | None] = dict(_FEATURE_TYPES)


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