"""The catalogue of Feature elements: each one's name, the file the features stage writes, and its geometry kind."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from twin.stages.accuracy import MARKING_TYPES


@dataclass(frozen=True)
class Element:
    name: str
    file: str
    geometry: Literal["line", "area", "point"]


ELEMENTS = (
    Element("marking", "markings.geojson", "line"),
    Element("crosswalk", "crosswalks.geojson", "area"),
    Element("curb", "curbs.geojson", "line"),
    Element("curb_ramp", "ramps.geojson", "point"),
)
FEATURE_FILES = tuple(e.file for e in ELEMENTS)


def by_file(file: str) -> Element:
    return next(e for e in ELEMENTS if e.file == file)


def score_slots(element: Element, props: dict) -> list[tuple[str | None, str | None]]:
    """The (element slot, marking-type slot) pairs a run feature counts towards."""
    if element.name != "marking":
        return [(element.name, None)]
    mt = props.get("marking_type")
    if mt == "crosswalk_stripe":
        return [(None, "crosswalk_stripe")]
    return [("marking", mt if mt in MARKING_TYPES else "other_paint")]
