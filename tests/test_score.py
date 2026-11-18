import json

import pytest

from twin import score
from twin.contracts import SiteMeta


def _line(coords, type="solid_line", element="marking", reliability="observed", mtype="divider", **props):
    p = {"id": props.pop("id", "run-1"), "kind": "marking", "reliability": reliability,
         "marking_type": mtype, "element": element, "type": type}
    p.update(props)
    return {"type": "Feature", "properties": p, "geometry": {"type": "LineString", "coordinates": coords}}


def _poly(ring, element="crosswalk", type="zebra", reliability="observed", **props):
    p = {"id": props.pop("id", "run-cw"), "kind": "crosswalk", "reliability": reliability,
         "element": element, "type": type}
    p.update(props)
    return {"type": "Feature", "properties": p, "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _point(x, y, element="curb_ramp", type="curb_ramp", reliability="observed", **props):
    p = {"id": props.pop("id", "run-ramp"), "kind": "curb_ramp", "reliability": reliability,
         "element": element, "type": type}
    p.update(props)
    return {"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [x, y]}}


def _site(poly=None, role="audit", id="s1", version=1):
    if poly is None:
        poly = [[-100, -100], [100, -100], [100, 100], [-100, 100], [-100, -100]]
    return SiteMeta(id=id, role=role, polygon={"type": "Polygon", "coordinates": [poly]},
                    version=version, created_at="2026-01-01T00:00:00+00:00", source_area="a")


# Mapping rows test
ROWS = [
    ("marking", "divider", "marking", "divider"),
    ("marking", "stop_line", "marking", "stop_line"),
    ("marking", "crosswalk_stripe", None, "crosswalk_stripe"),
    ("marking", "other_paint", "marking", "other_paint"),
    ("crosswalk", "zebra", "crosswalk", None),
    ("crosswalk", "parallel", "crosswalk", None),
    ("curb", "curb", "curb", None),
    ("curb_ramp", "curb_ramp", "curb_ramp", None),
]


@pytest.mark.parametrize("element,eff,eslot,mtslot", ROWS)
def test_mapping_rows(element, eff, eslot, mtslot):
    # build label
    if element == "marking":
        if eff == "crosswalk_stripe":
            geom = {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}
            props = {"element": "marking", "type": "solid_line", "source_marking_type": "crosswalk_stripe", "id": "l1"}
        elif eff == "divider":
            geom = {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}
            props = {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l1"}
        elif eff == "stop_line":
            geom = {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}
            props = {"element": "marking", "type": "stop_line", "source_marking_type": "stop_line", "id": "l1"}
        else:
            geom = {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}
            props = {"element": "marking", "type": "arrow", "source_marking_type": "other_paint", "id": "l1"}
    elif element == "crosswalk":
        ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        geom = {"type": "Polygon", "coordinates": [ring]}
        props = {"element": "crosswalk", "type": eff, "id": "l1"}
    elif element == "curb":
        geom = {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}
        props = {"element": "curb", "type": "curb", "id": "l1"}
    else:
        geom = {"type": "Point", "coordinates": [5, 5]}
        props = {"element": "curb_ramp", "type": "curb_ramp", "id": "l1"}

    label = {"type": "Feature", "properties": props, "geometry": geom}

    # run features
    if element == "crosswalk":
        # two run features: crosswalk polygon feeds crosswalk; typed stripe line feeds crosswalk_stripe
        ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        cw_poly = {"type": "Feature", "properties": {"id": "r1", "reliability": "observed", "marking_type": "crosswalk"}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
        stripe_line = {"type": "Feature", "properties": {"id": "r2", "reliability": "observed", "marking_type": "crosswalk_stripe"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
        run_features = {"crosswalks.geojson": [cw_poly], "markings.geojson": [stripe_line]}
    else:
        # generic run feature matching slot
        if element in ("marking",):
            if eff == "other_paint":
                mt = "arrow"
            elif eff == "crosswalk_stripe":
                mt = "crosswalk_stripe"
            else:
                mt = eff
            rf = _line([[0, 0], [10, 0]], type="solid_line", element="marking", mtype=mt)
            rf["properties"]["marking_type"] = mt
            run_features = {"markings.geojson": [rf]}
        elif element == "curb":
            rf = {"type": "Feature", "properties": {"id": "r", "reliability": "observed", "kind": "curb"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
            run_features = {"curbs.geojson": [rf]}
        elif element == "curb_ramp":
            rf = _point(5, 5)
            run_features = {"ramps.geojson": [rf]}

    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])

    if eslot is not None:
        assert partial["elements"][eslot]["n_labels"] == 1
        assert partial["elements"][eslot]["n_extracted"] == 1
        assert partial["elements"][eslot]["measured"] is True
        assert partial["elements"][eslot]["recall"] == 1.0
    if mtslot is not None:
        assert partial["marking_types"][mtslot]["n_labels"] == 1
        if mtslot == "crosswalk_stripe":
            assert partial["marking_types"][mtslot]["n_extracted"] == 1
        else:
            assert partial["marking_types"][mtslot]["n_extracted"] == 1

    for mt in score.MARKING_TYPE_ORDER:
        if mt != mtslot:
            assert partial["marking_types"][mt]["n_labels"] == 0
    if mtslot is None and element == "crosswalk":
        assert partial["marking_types"]["crosswalk_stripe"]["n_extracted"] == 1
    for slot in score.ELEMENT_ORDER:
        if slot != eslot:
            assert partial["elements"][slot]["n_labels"] == 0

    if element == "marking":
        assert partial["elements"]["curb"]["n_labels"] == 0
        assert partial["elements"]["curb_ramp"]["n_labels"] == 0
        assert partial["elements"]["crosswalk"]["n_labels"] == 0
        if eff == "crosswalk_stripe":
            assert partial["elements"]["marking"]["n_labels"] == 0
            assert partial["elements"]["marking"]["n_extracted"] == 0
        else:
            assert partial["elements"]["marking"]["n_labels"] == 1
            assert partial["elements"]["marking"]["n_extracted"] == 1
    if element == "crosswalk":
        assert partial["elements"]["marking"]["n_labels"] == 0
        assert partial["elements"]["marking"]["n_extracted"] == 0
        assert partial["elements"]["crosswalk"]["n_extracted"] == 1


def test_recall_is_matched_share_of_label_length():
    # label 0->80, run 1->39 (38m) -> matched 40m -> recall 0.5
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [80, 0]]}}
    rf = _line([[1, 0], [39, 0]], type="solid_line", element="marking", mtype="divider")
    rf["properties"]["marking_type"] = "divider"
    run_features = {"markings.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["marking_types"]["divider"]["recall"] == 0.5


def test_precision_is_share_of_run_samples_within_radius():
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]}}
    rf1 = _line([[0, 0], [40, 0]], type="solid_line", element="marking", mtype="divider")
    rf1["properties"]["marking_type"] = "divider"
    rf2 = _line([[0, 10], [40, 10]], type="solid_line", element="marking", mtype="divider")
    rf2["properties"]["marking_type"] = "divider"
    rf2["properties"]["id"] = "r2"
    run_features = {"markings.geojson": [rf1, rf2]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["marking_types"]["divider"]["precision"] == 0.5


def test_p95_is_the_p95_of_densified_samples():
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0.1], [100, 0.1]]}}
    rf = _line([[0, 0], [100, 0]], type="solid_line", element="marking", mtype="divider")
    rf["properties"]["marking_type"] = "divider"
    run_features = {"markings.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["marking_types"]["divider"]["p95_m"] == 0.1


def test_line_with_no_near_samples_has_precision_zero_and_is_measured():
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    rf = _line([[0, 5], [10, 5]], type="solid_line", element="marking", mtype="divider")
    rf["properties"]["marking_type"] = "divider"
    run_features = {"markings.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    e = partial["marking_types"]["divider"]
    assert e["precision"] == 0.0
    assert e["measured"] is True
    assert e["p95_m"] == 5.0


def test_point_with_no_pairs_is_measured():
    label = {"type": "Feature", "properties": {"element": "curb_ramp", "type": "curb_ramp", "id": "l"}, "geometry": {"type": "Point", "coordinates": [100, 100]}}
    rf = _point(0, 0)
    run_features = {"ramps.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    e = partial["elements"]["curb_ramp"]
    assert e["precision"] == 0.0
    assert e["recall"] == 0.0
    assert e["p95_m"] is None
    assert e["measured"] is True


def test_curb_height_compared_when_both_carry_height():
    label = {"type": "Feature", "properties": {"element": "curb", "type": "curb", "id": "l", "height_m": 0.10}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    rf = {"type": "Feature", "properties": {"id": "r", "reliability": "observed", "kind": "curb", "height_m": 0.12}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    run_features = {"curbs.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    h = partial["attributes"]["curb"]["height_m"]
    assert h["n_compared"] == 1
    assert h["p95_abs_delta_m"] == 0.02


def test_curb_height_pairs_one_to_one():
    labels = [{"type": "Feature", "properties": {"element": "curb", "type": "curb", "id": "l1", "height_m": 0.10}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}]
    rf1 = {"type": "Feature", "properties": {"id": "r1", "reliability": "observed", "kind": "curb", "height_m": 0.12}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    rf2 = {"type": "Feature", "properties": {"id": "r2", "reliability": "observed", "kind": "curb", "height_m": 0.13}, "geometry": {"type": "LineString", "coordinates": [[0, 0.5], [10, 0.5]]}}
    run_features = {"curbs.geojson": [rf1, rf2]}
    site = _site()
    partial = score.score_elements(run_features, [(site, labels)])
    assert partial["elements"]["curb"]["n_extracted"] == 2
    h = partial["attributes"]["curb"]["height_m"]
    assert h["n_compared"] == 1


def test_ramp_slope_deltas():
    # four paired ramps with deltas 0.4,0.9,0.9,0.9
    deltas = [0.4, 0.9, 0.9, 0.9]
    labels = []
    runs = []
    for i, dv in enumerate(deltas):
        x = i * 10
        labels.append({"type": "Feature", "properties": {"element": "curb_ramp", "type": "curb_ramp", "id": f"l{i}", "running_slope_pct": 1.0}, "geometry": {"type": "Point", "coordinates": [x, 0]}})
        runs.append(_point(x, 0, running_slope_pct=1.0 + dv))
        runs[-1]["properties"]["id"] = f"r{i}"
    # fix props field
    for r, dv in zip(runs, deltas):
        r["properties"]["running_slope_pct"] = 1.0 + dv
    run_features = {"ramps.geojson": runs}
    site = _site()
    partial = score.score_elements(run_features, [(site, labels)])
    a = partial["attributes"]["curb_ramp"]["running_slope_pct"]
    assert a["n_compared"] == 4
    assert a["p95_abs_delta_pct"] == 0.9
    assert a["max_abs_delta_pct"] == 0.9


def test_ramp_not_measured_when_run_lacks_field():
    labels = [{"type": "Feature", "properties": {"element": "curb_ramp", "type": "curb_ramp", "id": "l", "running_slope_pct": 1.0}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    rf = _point(0, 0)
    # no running_slope_pct
    run_features = {"ramps.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, labels)])
    a = partial["attributes"]["curb_ramp"]["running_slope_pct"]
    assert a["reason"] == "run ramps carry no running_slope_pct"


def test_ramp_precision_recall_counts():
    labels = [{"type": "Feature", "properties": {"element": "curb_ramp", "type": "curb_ramp", "id": "l"}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]
    rf1 = _point(0, 0)
    rf2 = _point(100, 100)
    run_features = {"ramps.geojson": [rf1, rf2]}
    site = _site()
    partial = score.score_elements(run_features, [(site, labels)])
    e = partial["elements"]["curb_ramp"]
    assert e["precision"] == 0.5
    assert e["recall"] == 1.0


def test_crosswalk_stripes_in_markings_are_not_marking_false_positives():
    label = {"type": "Feature", "properties": {"element": "crosswalk", "type": "zebra", "id": "l"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}}
    stripe = {"type": "Feature", "properties": {"id": "s", "reliability": "observed", "marking_type": "crosswalk_stripe"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    run_features = {"markings.geojson": [stripe], "crosswalks.geojson": []}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["elements"]["marking"]["n_extracted"] == 0
    assert partial["marking_types"]["crosswalk_stripe"]["n_extracted"] == 1
    assert partial["qa"]["n_excluded_crosswalk_stripes"] == 1


def test_marking_label_uses_source_marking_type():
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "crosswalk_stripe", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    stripe = {"type": "Feature", "properties": {"id": "s", "reliability": "observed", "marking_type": "crosswalk_stripe"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    run_features = {"markings.geojson": [stripe]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["marking_types"]["crosswalk_stripe"]["n_labels"] == 1
    assert partial["elements"]["marking"]["n_labels"] == 0
    assert partial["marking_types"]["divider"]["n_labels"] == 0


def test_drafted_divider_label_maps_to_divider():
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    rf = _line([[0, 0], [10, 0]], type="solid_line", element="marking", mtype="divider")
    rf["properties"]["marking_type"] = "divider"
    run_features = {"markings.geojson": [rf]}
    site = _site()
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["marking_types"]["divider"]["n_labels"] == 1
    assert partial["elements"]["marking"]["n_labels"] == 1
    assert partial["qa"]["unmapped_labels"] == []


def test_unmapped_label_is_counted_not_scored():
    bad = {"type": "Feature", "properties": {"element": "marking", "type": "curb", "id": "bad-1"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}}
    cross = {"type": "Feature", "properties": {"element": "crosswalk", "type": "zebra", "id": "c1"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}}
    run_features = {}
    site = _site()
    partial = score.score_elements(run_features, [(site, [bad, cross])])
    assert partial["qa"]["unmapped_labels"] == [{"id": "bad-1", "reason": "no metric for element/type"},
                                                 {"id": "c1", "reason": "non-polygon crosswalk label"}] or \
           partial["qa"]["unmapped_labels"] == [{"id": "c1", "reason": "non-polygon crosswalk label"},
                                                {"id": "bad-1", "reason": "no metric for element/type"}]
    # sorted by id
    ids = [u["id"] for u in partial["qa"]["unmapped_labels"]]
    assert ids == sorted(ids)


def test_publish_first_run_without_baseline():
    cand = {"target_kind": "run", "sites": [], "elements": {}}
    res = score.publish_decision(cand, None)
    assert res["publish"] is True
    assert res["comparable"] is True
    assert res["reason"] == "no baseline"
    assert all(v["status"] == "new" for v in res["elements"].values())


def test_publish_tie():
    doc = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}],
           "elements": {"marking": {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}}}
    # need all ELEMENT_ORDER entries
    for el in score.ELEMENT_ORDER:
        doc["elements"].setdefault(el, {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1})
    res = score.publish_decision(doc, doc)
    assert all(v["status"] == "tie" for v in res["elements"].values())
    assert res["publish"] is True


def test_improved_element_publishes():
    base = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}],
            "elements": {}}
    cand = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}],
            "elements": {}}
    for el in score.ELEMENT_ORDER:
        base["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
        cand["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
    cand["elements"]["crosswalk"]["recall"] = 0.55
    res = score.publish_decision(cand, base)
    assert res["elements"]["crosswalk"]["status"] == "improved"
    assert res["publish"] is True


def test_publish_within_noise_is_a_tie():
    base = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    cand = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        base["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
        cand["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
    cand["elements"]["curb"]["p95_m"] = 0.119
    res = score.publish_decision(cand, base)
    assert res["elements"]["curb"]["status"] == "tie"
    assert res["publish"] is True


def test_publish_worse_element_skips():
    base = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    cand = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        base["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
        cand["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
    cand["elements"]["curb"]["p95_m"] = 0.15
    res = score.publish_decision(cand, base)
    assert res["elements"]["curb"]["status"] == "worse"
    assert res["publish"] is False
    assert "curb" in res["reason"]


def test_publish_lost_element_skips():
    base = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    cand = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        base["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
        cand["elements"][el] = {"measured": False, "n_labels": 1, "precision": None, "recall": None, "p95_m": None}
    res = score.publish_decision(cand, base)
    assert res["elements"]["curb"]["status"] == "lost"
    assert res["publish"] is False


def test_empty_label_site_reports_not_labelled():
    site = _site(id="s1")
    run_features = {}
    partial = score.score_elements(run_features, [(site, [])])
    assert partial["sites"] == []
    assert partial["qa"]["sites_skipped"] == [{"id": "s1", "reason": "no labels"}]

    base = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    cand = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "abc"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        base["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
        cand["elements"][el] = {"measured": False, "n_labels": 0, "precision": None, "recall": None, "p95_m": None}
    res = score.publish_decision(cand, base)
    assert all(v["status"] == "not measured" for v in res["elements"].values())
    assert res["publish"] is True


def test_comparability_guard():
    cand = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "aaa"}], "elements": {}}
    base = {"target_kind": "area", "sites": [{"id": "s1", "version": 1, "label_hash": "aaa"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        cand["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
        base["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
    res = score.publish_decision(cand, base)
    assert res["comparable"] is False
    assert res["publish"] is None
    assert all(v["status"] == "not compared" for v in res["elements"].values())

    # version bump
    base2 = {"target_kind": "run", "sites": [{"id": "s1", "version": 2, "label_hash": "aaa"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        base2["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
    res2 = score.publish_decision(cand, base2)
    assert res2["comparable"] is False

    # same version different hash
    base3 = {"target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "bbb"}], "elements": {}}
    for el in score.ELEMENT_ORDER:
        base3["elements"][el] = {"measured": True, "n_labels": 1, "precision": 0.5, "recall": 0.5, "p95_m": 0.1}
    res3 = score.publish_decision(cand, base3)
    assert res3["comparable"] is False


def test_load_baseline_without_history_is_none(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    assert score.load_baseline(store) is None
    # seeded entry without score
    pub = store / "published"
    pub.mkdir()
    (pub / "history.json").write_text(json.dumps([{"run_id": "r1", "go_count": 0, "margin_sum": 1.0}]))
    assert score.load_baseline(store) is None


def _write_target(d, files):
    (d / "5_features").mkdir(parents=True, exist_ok=True)
    for fn, fc in files.items():
        (d / "5_features" / fn).write_text(json.dumps(fc))


def test_score_target_writes_score_json(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    poly = [[-100, -100], [100, -100], [100, 100], [-100, 100], [-100, -100]]
    site_dir = store / "labels" / "s1"
    site_dir.mkdir(parents=True)
    (site_dir / "site.json").write_text(json.dumps({
        "id": "s1", "role": "audit", "polygon": {"type": "Polygon", "coordinates": [poly]},
        "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "a"
    }))
    (site_dir / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "l", "element": "marking", "type": "solid_line", "source_marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    ]}))
    rf = {"type": "Feature", "properties": {"id": "r", "reliability": "observed", "marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    _write_target(run, {"markings.geojson": {"type": "FeatureCollection", "features": [rf]}})
    doc, reason = score.score_target(store, run, sites="audit", baseline=None)
    assert reason == ""
    assert (run / "score.json").is_file()
    keys = list(json.loads((run / "score.json").read_text()).keys())
    assert keys == ["schema", "method", "target", "target_kind", "sites", "elements", "marking_types", "attributes", "compare", "noise", "qa"]
    assert doc["target_kind"] == "run"
    assert len(doc["sites"][0]["label_hash"]) == 12
    assert doc["compare"]["publish"] is True
    assert any("301" in n for n in doc["qa"]["notes"])


@pytest.mark.parametrize("reason", ["no labels dir", "no audit label sites", "no 5_features", "no usable label sites"])
def test_score_target_none(tmp_path, reason):
    store = tmp_path / "store"
    run = tmp_path / "run"
    run.mkdir()
    if reason == "no 5_features":
        store.mkdir()
        sd = store / "labels" / "s1"
        sd.mkdir(parents=True)
        (sd / "site.json").write_text(json.dumps({"id": "s1", "role": "audit", "polygon": {"type": "Polygon", "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]]}, "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "a"}))
        (sd / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": "l", "element": "marking", "type": "solid_line", "source_marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}}
        ]}))
        # no 5_features dir
    elif reason == "no labels dir":
        # store has no labels dir; create 5_features
        run2 = run
        (run2 / "5_features").mkdir()
        (run2 / "5_features" / "markings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    elif reason == "no audit label sites":
        store.mkdir()
        # labels dir but no audit sites (dev only?) create dev site
        sd = store / "labels" / "s1"
        sd.mkdir(parents=True)
        (sd / "site.json").write_text(json.dumps({"id": "s1", "role": "dev", "polygon": {"type": "Polygon", "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]]}, "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "a"}))
        (sd / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"id": "l", "element": "marking", "type": "solid_line", "source_marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}}
        ]}))
        (run / "5_features").mkdir()
        (run / "5_features" / "markings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    elif reason == "no usable label sites":
        store.mkdir()
        sd = store / "labels" / "s1"
        sd.mkdir(parents=True)
        (sd / "site.json").write_text(json.dumps({"id": "s1", "role": "audit", "polygon": {"type": "Polygon", "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]]}, "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "a"}))
        (sd / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        (run / "5_features").mkdir()
        (run / "5_features" / "markings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))

    doc, r = score.score_target(store, run, sites="audit", baseline=None)
    assert doc is None
    assert r == reason
    assert not (run / "score.json").exists()


def test_score_is_deterministic(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    poly = [[-100, -100], [100, -100], [100, 100], [-100, 100], [-100, -100]]
    site_dir = store / "labels" / "s1"
    site_dir.mkdir(parents=True)
    (site_dir / "site.json").write_text(json.dumps({"id": "s1", "role": "audit", "polygon": {"type": "Polygon", "coordinates": [poly]}, "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "a"}))
    (site_dir / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": "l", "element": "marking", "type": "solid_line", "source_marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    ]}))
    rf = {"type": "Feature", "properties": {"id": "r", "reliability": "observed", "marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    (run / "5_features").mkdir()
    (run / "5_features" / "markings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [rf]}))
    score.score_target(store, run, sites="audit", baseline=None)
    b1 = (run / "score.json").read_bytes()
    score.score_target(store, run, sites="audit", baseline=None)
    b2 = (run / "score.json").read_bytes()
    assert b1 == b2


def test_no_clipped_run_features_site():
    label = {"type": "Feature", "properties": {"element": "marking", "type": "solid_line", "source_marking_type": "divider", "id": "l"}, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}}
    site = _site()
    rf = _line([[1000, 1000], [1010, 1000]], type="solid_line", element="marking", mtype="divider")
    rf["properties"]["marking_type"] = "divider"
    run_features = {"markings.geojson": [rf]}
    partial = score.score_elements(run_features, [(site, [label])])
    assert partial["sites"] == []
    assert partial["qa"]["sites_skipped"] == [{"id": "s1", "reason": "no extracted elements in site"}]


def test_list_sites(tmp_path):
    import json

    from twin.labels import list_sites
    store = tmp_path / "store"
    assert list_sites(store) == []
    (store / "labels" / "b").mkdir(parents=True)
    (store / "labels" / "a").mkdir(parents=True)
    (store / "labels" / "c").mkdir(parents=True)
    (store / "labels" / "a" / "site.json").write_text(json.dumps({
        "id": "a", "role": "audit", "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "x"
    }))
    (store / "labels" / "b" / "site.json").write_text(json.dumps({
        "id": "b", "role": "dev", "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "x"
    }))
    assert [s.id for s in list_sites(store)] == ["a", "b"]
    assert [s.id for s in list_sites(store, role="audit")] == ["a"]


def test_empty_label_site_reports_not_labelled_score_target(tmp_path):
    import json
    store = tmp_path / "store"
    run = tmp_path / "run"
    run.mkdir()
    poly = [[-100, -100], [100, -100], [100, 100], [-100, 100], [-100, -100]]
    for sid, labels in (("s1", []), ("s2", [{"type": "Feature", "properties": {"id": "l", "element": "marking", "type": "solid_line", "source_marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[5, 0], [15, 0]]}}])):
        sd = store / "labels" / sid
        sd.mkdir(parents=True)
        (sd / "site.json").write_text(json.dumps({"id": sid, "role": "audit", "polygon": {"type": "Polygon", "coordinates": [poly]}, "version": 1, "created_at": "2026-01-01T00:00:00+00:00", "source_area": "a"}))
        (sd / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": labels}))
    (run / "5_features").mkdir()
    rf = {"type": "Feature", "properties": {"id": "r", "reliability": "observed", "marking_type": "divider"}, "geometry": {"type": "LineString", "coordinates": [[5, 0], [15, 0]]}}
    (run / "5_features" / "markings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [rf]}))
    baseline = {"target": "old", "target_kind": "run", "sites": [{"id": "s1", "version": 1, "label_hash": "x"}], "elements": {}}
    doc, reason = score.score_target(store, run, sites="audit", baseline=baseline)
    assert reason == ""
    assert doc["qa"]["sites_skipped"] == [{"id": "s1", "reason": "no labels"}]
    assert [s["id"] for s in doc["sites"]] == ["s2"]
    assert doc["compare"]["comparable"] is False
    assert doc["compare"]["publish"] is None
