"""Stage 9 accuracy (one-way): synthetic data only, no devkit, no data."""

import json
import logging

import pytest

from twin import registry
from twin.contracts import STAGES, AccuracyParams
from twin.runner import StageContext


def _line(coords, layer=None, reliability="observed", mtype="divider"):
    props = {
        "id": "x",
        "kind": "marking",
        "reliability": reliability,
        "marking_type": mtype,
    }
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _ref(coords, layer):
    return {
        "type": "Feature",
        "properties": {"layer": layer, "token": layer + "-1"},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _core():
    poly = [[-50, -50], [150, -50], [150, 50], [-50, 50], [-50, -50]]
    return {
        "type": "Feature",
        "properties": {"id": "I-0001", "type": "intersection", "name": None},
        "geometry": {"type": "Polygon", "coordinates": [poly]},
    }


def _write(run, stage, name, doc):
    d = run / f"{STAGES[stage].number}_{stage}"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(doc))


def _ctx(run):
    return StageContext(
        run_dir=run, scene_token="s", seed=0, log=logging.getLogger("t")
    )


def _run(
    tmp_path, reference, markings, curbs=None, qa=None, buffer_m=1.0, crosswalks=()
):
    run = tmp_path / "run"
    run.mkdir()
    _write(run, "load", "reference.geojson", _fc(reference))
    _write(run, "load", "facilities.geojson", _fc([_core()]))
    _write(run, "features", "markings.geojson", _fc(markings))
    _write(run, "features", "crosswalks.geojson", _fc(list(crosswalks)))
    _write(run, "features", "qa.json", {"not_scanned_enough": [], **(qa or {})})
    if curbs is not None:
        _write(run, "features", "curbs.geojson", _fc(curbs))
    fn = registry.lookup("accuracy", "one-way")
    result = fn(_ctx(run), AccuracyParams(buffer_m=buffer_m))
    assert result.status == "ok"
    return json.loads((run / "9_accuracy" / "accuracy.json").read_text())


def test_known_offset_gives_p50_and_p95(tmp_path):
    # Reference lane line on y=0; the marking sits 0.5 m off it along its whole length.
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    marking = [_line([[x, 0.5] for x in range(10, 31)])]
    doc = _run(tmp_path, ref, marking)
    m = doc["elements"]["markings"]
    assert m["p50_m"] == pytest.approx(0.5, abs=1e-3)
    assert m["p95_m"] == pytest.approx(0.5, abs=1e-3)
    assert m["reference_layer"] == "lane_divider, road_divider"


def test_ten_centimetre_offset(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    marking = [_line([[x, 0.10] for x in range(10, 31)])]
    doc = _run(tmp_path, ref, marking)
    assert doc["elements"]["markings"]["p50_m"] == pytest.approx(0.10, abs=1e-3)
    assert doc["elements"]["markings"]["p95_m"] == pytest.approx(0.10, abs=1e-3)


def test_half_covered_reference_gives_coverage_half(tmp_path):
    # Reference is 20 m long; the marking covers the first 10 m, within a 0.1 m tolerance.
    ref = [_ref([[0, 0], [20, 0]], "lane_divider")]
    marking = [_line([[x, 0] for x in range(11)])]
    doc = _run(tmp_path, ref, marking, buffer_m=0.1)
    assert doc["elements"]["markings"]["coverage"] == pytest.approx(0.5, abs=0.02)


def test_unobserved_features_are_not_scored(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    marking = [
        _line([[x, 0.1] for x in range(10, 31)]),
        _line([[x, 3.0] for x in range(10, 31)], reliability="modelled"),
    ]
    doc = _run(tmp_path, ref, marking)
    # The observed 20 m line is sampled every 0.25 m: 81 points. The modelled line is not counted.
    assert (
        doc["elements"]["markings"]["n_samples"] == 81
    )  # 20 m line, one sample per 0.25 m
    assert doc["elements"]["markings"]["n"] == 1
    assert doc["elements"]["markings"]["p95_m"] == pytest.approx(0.1, abs=1e-3)
    assert doc["qa"]["n_excluded_not_observed"] == 1


def test_missing_curbs_file_is_skipped(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    doc = _run(tmp_path, ref, [_line([[x, 0.1] for x in range(10, 31)])], curbs=None)
    assert "curbs" not in doc["elements"]
    assert doc["qa"]["absent_element_files"] == ["curbs"]


def test_curbs_are_map_conditioned(tmp_path):
    ref = [
        {
            "type": "Feature",
            "properties": {"layer": "drivable_area", "token": "d"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [40, 0], [40, 10], [0, 10], [0, 0]]],
            },
        }
    ]
    curb = {
        "type": "Feature",
        "properties": {"id": "c", "kind": "curb", "reliability": "observed"},
        "geometry": {
            "type": "LineString",
            "coordinates": [[x, 0.2, 0.1] for x in range(5, 36)],
        },
    }
    doc = _run(tmp_path, [*ref], [], curbs=[curb])
    c = doc["elements"]["curbs"]
    assert c["p50_m"] == pytest.approx(0.2, abs=1e-3)
    assert c["label"] == "map-conditioned"
    assert c["reference_layer"] == "drivable_area"


def test_facility_entry_reports_observed_facility(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    doc = _run(tmp_path, ref, [_line([[x, 0.1] for x in range(10, 31)])])
    fac = doc["facilities"]["I-0001"]
    assert fac["p50_m"] == pytest.approx(0.1, abs=1e-3)
    assert fac["reason"] == ""


def _crossing():
    """ped_crossing polygon, 12 m by 6 m."""
    ring = [[0, 0], [12, 0], [12, 6], [0, 6], [0, 0]]
    return {
        "type": "Feature",
        "properties": {"layer": "ped_crossing", "token": "pc-1"},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _stripe(x0, x1):
    """A stripe across the crossing: four corners, 6 m long."""
    ring = [[x0, 0], [x1, 0], [x1, 6], [x0, 6], [x0, 0]]
    return {"type": "Polygon", "coordinates": [ring]}


def _crosswalk(geometry):
    return {
        "type": "Feature",
        "properties": {"id": "cw", "kind": "crosswalk", "reliability": "observed"},
        "geometry": geometry,
    }


def test_perfect_crosswalk_inside_its_crossing_scores_zero(tmp_path):
    stripes = [_stripe(1 + 2 * k, 1.5 + 2 * k) for k in range(6)]
    geom = {"type": "MultiPolygon", "coordinates": [s["coordinates"] for s in stripes]}
    doc = _run(tmp_path, [_crossing()], [], crosswalks=[_crosswalk(geom)], buffer_m=1.0)
    cw = doc["elements"]["crosswalks"]
    assert cw["p50_m"] == 0.0
    assert cw["p95_m"] == 0.0
    assert cw["coverage"] == pytest.approx(1.0, abs=0.01)
    assert cw["reference_layer"] == "ped_crossing"


def test_stripe_shifted_outside_gives_p95_of_its_offset(tmp_path):
    # Five stripes inside. The sixth sits across the east edge of the crossing (x = 12 m), so its outer
    # edge is 0.3 m outside. Outlines are densified to 0.25 m in the stage, so the corners alone are enough.
    stripes = [_stripe(1 + 2 * k, 1.5 + 2 * k)["coordinates"] for k in range(5)]
    shifted = _stripe(11.8, 12.3)["coordinates"]
    geom = {"type": "MultiPolygon", "coordinates": [*stripes, shifted]}
    doc = _run(tmp_path, [_crossing()], [], crosswalks=[_crosswalk(geom)], buffer_m=1.0)
    cw = doc["elements"]["crosswalks"]
    assert cw["p50_m"] == 0.0
    assert cw["p95_m"] == pytest.approx(0.3, abs=0.01)


def test_curbs_off_leave_no_curb_label_on_facility(tmp_path):
    # Curbs disabled: no curb file, so the facility entry is not labelled map-conditioned.
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    doc = _run(tmp_path, ref, [_line([[x, 0.1] for x in range(10, 31)])], curbs=None)
    assert "curbs" not in doc["elements"]
    assert doc["facilities"]["I-0001"]["label"] == ""


def test_not_scanned_facility_has_reason_and_no_numbers(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    doc = _run(
        tmp_path,
        ref,
        [_line([[x, 0.1] for x in range(10, 31)])],
        qa={"not_scanned_enough": ["I-0001"]},
    )
    fac = doc["facilities"]["I-0001"]
    assert fac["reason"] == "not scanned enough"
    assert fac["p50_m"] is None and fac["p95_m"] is None and fac["coverage"] is None


def test_result_metrics_are_the_accuracy_document(tmp_path):
    # The runner stores StageResult.metrics as manifest metrics["accuracy"], so they must equal the file.
    run = tmp_path / "run"
    run.mkdir()
    _write(
        run,
        "load",
        "reference.geojson",
        _fc([_ref([[0, 0], [100, 0]], "lane_divider")]),
    )
    _write(run, "load", "facilities.geojson", _fc([_core()]))
    _write(
        run,
        "features",
        "markings.geojson",
        _fc([_line([[x, 0.1] for x in range(10, 31)])]),
    )
    _write(run, "features", "crosswalks.geojson", _fc([]))
    _write(run, "features", "qa.json", {"not_scanned_enough": []})
    result = registry.lookup("accuracy", "one-way")(_ctx(run), AccuracyParams())
    assert result.metrics == json.loads(
        (run / "9_accuracy" / "accuracy.json").read_text()
    )


# ------------------------------------------------------------------ marking types


def _poly_ref(coords, layer):
    return {
        "type": "Feature",
        "properties": {"layer": layer, "token": layer + "-1"},
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


def test_each_marking_type_scored_against_its_own_layer(tmp_path):
    ref = [
        _ref([[0, 0], [100, 0]], "lane_divider"),
        _poly_ref([[50, -2], [50.4, -2], [50.4, 2], [50, 2], [50, -2]], "stop_line"),
        _poly_ref([[20, -3], [24, -3], [24, 3], [20, 3], [20, -3]], "ped_crossing"),
    ]
    ms = [
        _line([[x, 0.2] for x in range(10, 31)]),
        _line([[50.2, -1.5], [50.2, 1.5]], mtype="stop_line"),
        _line([[21, -2], [21, 2]], mtype="crosswalk_stripe"),
        _line([[x, 30.0] for x in range(10, 31)], mtype="other_paint"),
    ]
    doc = _run(tmp_path, ref, ms)
    mt = doc["marking_types"]
    assert mt["divider"]["reference_layer"] == "lane_divider, road_divider"
    assert mt["divider"]["p50_m"] == pytest.approx(0.2, abs=1e-3)
    assert mt["stop_line"]["reference_layer"] == "stop_line"
    assert mt["stop_line"]["p95_m"] == 0.0 and mt["stop_line"]["n"] == 1
    assert mt["crosswalk_stripe"]["reference_layer"] == "ped_crossing"
    assert mt["crosswalk_stripe"]["p95_m"] == 0.0
    # elements.markings is the divider entry, so the viewer's headline figure stays meaningful
    assert doc["elements"]["markings"] == mt["divider"]


def test_other_paint_gets_no_figures_and_a_reason(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    doc = _run(
        tmp_path, ref, [_line([[x, 30.0] for x in range(10, 31)], mtype="other_paint")]
    )
    o = doc["marking_types"]["other_paint"]
    assert o["p50_m"] is None and o["p95_m"] is None and o["coverage"] is None
    assert o["reason"] == "no map layer" and o["n"] == 1
    # the other paint does not pollute the divider figures
    assert doc["marking_types"]["divider"]["reason"] == "no observed elements"


def test_far_false_positive_changes_fp_rate_not_matched_p95(tmp_path):
    # One good line 0.1 m off the reference, one line 5 m away (a false positive with no counterpart).
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    near = _line([[x, 0.1] for x in range(10, 31)])
    far = _line([[x, 5.0] for x in range(10, 31)])
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    clean = _run(tmp_path / "a", ref, [near])["elements"]["markings"]
    dirty = _run(tmp_path / "b", ref, [near, far])["elements"]["markings"]
    assert clean["false_positive_rate"] == 0
    assert dirty["false_positive_rate"] == pytest.approx(0.5)
    assert (
        dirty["matched_p95_m"] == clean["matched_p95_m"] == pytest.approx(0.1, abs=1e-3)
    )
    assert dirty["p95_m"] > 4  # the old one-way figure still carries the false positive


def test_nothing_within_radius_gives_no_matched_figures(tmp_path):
    ref = [_ref([[0, 0], [100, 0]], "lane_divider")]
    doc = _run(tmp_path, ref, [_line([[x, 5.0] for x in range(10, 31)])])
    m = doc["elements"]["markings"]
    assert m["matched_p95_m"] is None and m["false_positive_rate"] == 1
