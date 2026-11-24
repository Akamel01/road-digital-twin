from typing import get_args

import pytest

from twin.contracts import LabelFeature
from twin.elements import ELEMENTS, FEATURE_FILES, by_file, score_slots


def test_catalogue_order_is_the_old_feature_files():
    assert FEATURE_FILES == ("markings.geojson", "crosswalks.geojson", "curbs.geojson", "ramps.geojson")


def test_element_names_match_the_label_contract():
    assert tuple(e.name for e in ELEMENTS) == get_args(LabelFeature.model_fields["element"].annotation)


def test_by_file_and_geometry():
    assert [(by_file(f).name, by_file(f).geometry) for f in FEATURE_FILES] == [
        ("marking", "line"),
        ("crosswalk", "area"),
        ("curb", "line"),
        ("curb_ramp", "point"),
    ]


@pytest.mark.parametrize(
    ("marking_type", "expected"),
    [
        ("divider", [("marking", "divider")]),
        ("stop_line", [("marking", "stop_line")]),
        ("other_paint", [("marking", "other_paint")]),
        ("crosswalk_stripe", [(None, "crosswalk_stripe")]),
        ("mystery", [("marking", "other_paint")]),
        (None, [("marking", "other_paint")]),
    ],
)
def test_score_slots_for_markings(marking_type, expected):
    assert score_slots(by_file("markings.geojson"), {"marking_type": marking_type}) == expected


@pytest.mark.parametrize("name", ["crosswalk", "curb", "curb_ramp"])
def test_score_slots_for_other_elements(name):
    element = next(e for e in ELEMENTS if e.name == name)
    assert score_slots(element, {"marking_type": "divider"}) == [(name, None)]
