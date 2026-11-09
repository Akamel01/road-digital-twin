"""Stage 9 accuracy (one-way): synthetic data only, no devkit, no data."""

import json
import logging

import pytest

from twin import registry
from twin.contracts import STAGES, AccuracyParams
from twin.runner import StageContext


def _line(coords, layer=None, reliability="observed"):
    props = {"id": "x", "kind": "marking", "reliability": reliability}
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


def _run(tmp_path, reference, markings, curbs=None, qa=None, buffer_m=1.0):
    run = tmp_path / "run"
    run.mkdir()
    _write(run, "load", "reference.geojson", _fc(reference))
    _write(run, "load", "facilities.geojson", _fc([_core()]))
    _write(run, "features", "markings.geojson", _fc(markings))
    _write(run, "features", "crosswalks.geojson", _fc([]))
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
    assert doc["elements"]["markings"]["n"] == 21
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
