import json

import pytest

from twin import labels
from twin.labeltool import (
    SURFACE_MAP,
    DraftError,
    import_draft,
    surface_to_feature,
)


def _make_area(tmp_path):
    build = tmp_path / "test-twin"
    build.mkdir()
    (build / "markings.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []})
    )
    area_def = {
        "name": "test",
        "polygon": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
    }
    (tmp_path / "test-twin.json").write_text(json.dumps(area_def, indent=2) + "\n")
    return build


def _draft():
    x0, y1, g = 0, 20, 0.05

    def px_of(xy):
        return [[round((x - x0) / g, 2), round((y1 - y) / g, 2)] for x, y in xy]

    evs = ["intensity", "ortho", "fused"]
    specs = [
        ("t001", "lane line, solid white", "polyline", [[1, 1], [5, 1]]),
        ("t002", "lane line, dashed white", "polyline", [[1, 2], [5, 2]]),
        ("t003", "lane line, solid yellow", "polyline", [[1, 3], [5, 3]]),
        ("t004", "lane line, double yellow", "polyline", [[1, 4], [5, 4]]),
        ("t005", "lane line, double yellow", "polyline", [[1, 5], [5, 5]]),
        ("t006", "stop line", "polyline", [[2, 6], [4, 6]]),
        ("t007", "crosswalk, ladder", "polygon", [[6, 6], [10, 6], [10, 10], [6, 10]]),
        ("t008", "crosswalk, continental", "polygon", [[6, 11], [10, 11], [10, 15], [6, 15]]),
        ("t009", "crosswalk, transverse", "polygon", [[11, 6], [15, 6], [15, 10], [11, 10]]),
        ("t010", "crosswalk, zebra", "polygon", [[11, 11], [15, 11], [15, 15], [11, 15]]),
        ("t011", "curb", "polyline", [[16, 1], [16, 5]]),
        ("t012", "edge of pavement", "polyline", [[17, 1], [17, 5]]),
        ("t013", "lane line, solid white", "polyline", [[1, 7], [5, 7]]),
        ("t014", "lane line, dashed white", "polyline", [[1, 8], [5, 8]]),
        ("t015", "lane line, double yellow", "polyline", [[1, 9], [5, 9]]),
    ]
    surfaces = []
    for i, (sid, raw, geom, xy) in enumerate(specs):
        surfaces.append(
            {
                "id": sid,
                "type": raw,
                "geom": geom,
                "px": px_of(xy),
                "xy": xy,
                "evidence": evs[i % 3],
                "by": "operator",
            }
        )
    return {
        "set": "s1",
        "version": 1,
        "frozen": None,
        "supports": [],
        "devices": [],
        "surfaces": surfaces,
    }


@pytest.mark.parametrize("raw", list(SURFACE_MAP))
def test_surface_to_feature_maps_every_template_type(raw):
    element, typ = SURFACE_MAP[raw]
    if element == "crosswalk":
        xy = [[0, 0], [1, 0], [1, 1]]
        geom = "polygon"
    else:
        xy = [[0, 0], [1, 1]]
        geom = "polyline"
    surf = {"id": "s1", "type": raw, "geom": geom, "xy": xy, "by": "operator"}
    feat = surface_to_feature(surf)
    assert feat["type"] == "Feature"
    assert feat["properties"]["element"] == element
    assert feat["properties"]["type"] == typ
    assert feat["properties"]["source_marking_type"] == raw
    assert feat["properties"]["origin"] == "operator"


def test_surface_to_feature_closes_polygon_ring():
    surf = {"id": "p", "type": "curb", "geom": "polygon", "xy": [[0, 0], [1, 0], [1, 1]], "by": "operator"}
    feat = surface_to_feature(surf)
    coords = feat["geometry"]["coordinates"][0]
    assert len(coords) == 4
    assert coords[0] == coords[-1]
    # already closed unchanged
    surf2 = {"id": "p2", "type": "curb", "geom": "polygon", "xy": [[0, 0], [1, 0], [1, 1], [0, 0]], "by": "operator"}
    feat2 = surface_to_feature(surf2)
    coords2 = feat2["geometry"]["coordinates"][0]
    assert len(coords2) == 4


def test_surface_to_feature_rejects_unknown_type():
    surf = {"id": "x", "type": "nope", "geom": "polyline", "xy": [[0, 0], [1, 1]]}
    with pytest.raises(DraftError):
        surface_to_feature(surf)


def test_surface_to_feature_rejects_non_operator_by():
    surf = {"id": "x", "type": "curb", "geom": "polyline", "xy": [[0, 0], [1, 1]], "by": "auto"}
    with pytest.raises(DraftError):
        surface_to_feature(surf)


def _setup_site(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    labels.draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    return store, "s1"


def test_import_draft_round_trips_fifteen_surfaces(tmp_path):
    store, site = _setup_site(tmp_path)
    draft = _draft()
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(draft))
    n = import_draft(store, site, dpath)
    assert n == 15
    fc = labels.read_labels(store, site)
    feats = fc["features"]
    assert len(feats) == 15
    ids = [f["properties"]["id"] for f in feats]
    assert ids == [f"t{i:03d}" for i in range(1, 16)]
    meta = labels.read_site(store, site)
    assert meta.version == 1
    assert meta.frozen is False
    # raw type/evidence/origin/xy/geometry type
    by_id = {f["properties"]["id"]: f for f in feats}
    for surf in draft["surfaces"]:
        f = by_id[surf["id"]]
        assert f["properties"]["source_marking_type"] == surf["type"]
        assert f["properties"]["evidence"] == surf["evidence"]
        assert f["properties"]["origin"] == "operator"
        # geometry type
        expected_gt = "Polygon" if (surf["geom"] == "polygon" or SURFACE_MAP[surf["type"]][0] == "crosswalk") else "LineString"
        assert f["geometry"]["type"] == expected_gt
        # xy (open ring compare)
        coords = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "Polygon":
            ring = coords[0]
            # strip closing
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            assert ring == surf["xy"]
        else:
            assert coords == surf["xy"]
    # px reconstruction
    x0, y1, g = 0, 20, 0.05
    for surf in draft["surfaces"]:
        f = by_id[surf["id"]]
        coords = f["geometry"]["coordinates"]
        ring = coords[0] if f["geometry"]["type"] == "Polygon" else coords
        # use first point
        x, y = ring[0]
        px = ((x - x0) / g, (y1 - y) / g)
        assert abs(px[0] - surf["px"][0][0]) <= 0.02
        assert abs(px[1] - surf["px"][0][1]) <= 0.02


def test_import_draft_is_idempotent(tmp_path):
    store, site = _setup_site(tmp_path)
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(_draft()))
    import_draft(store, site, dpath)
    import_draft(store, site, dpath)
    fc = labels.read_labels(store, site)
    assert len(fc["features"]) == 15


def test_import_draft_merges_without_dropping_existing_features(tmp_path):
    store, site = _setup_site(tmp_path)
    # add existing feature
    fc = labels.read_labels(store, site)
    fc["features"].append(
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
         "properties": {"id": "existing", "element": "marking", "type": "solid_line", "origin": "operator"}}
    )
    labels.write_labels(store, site, fc, expected_version=labels.read_site(store, site).version)
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(_draft()))
    import_draft(store, site, dpath)
    ids = [f["properties"]["id"] for f in labels.read_labels(store, site)["features"]]
    assert "existing" in ids
    assert len(ids) == 16


def test_import_draft_replace_drops_existing_features(tmp_path):
    store, site = _setup_site(tmp_path)
    fc = labels.read_labels(store, site)
    fc["features"].append(
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
         "properties": {"id": "existing", "element": "marking", "type": "solid_line", "origin": "operator"}}
    )
    labels.write_labels(store, site, fc, expected_version=labels.read_site(store, site).version)
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(_draft()))
    import_draft(store, site, dpath, replace=True)
    ids = [f["properties"]["id"] for f in labels.read_labels(store, site)["features"]]
    assert "existing" not in ids
    assert len(ids) == 15


def test_import_draft_rejects_set_mismatch(tmp_path):
    store, site = _setup_site(tmp_path)
    d = _draft()
    d["set"] = "other"
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    with pytest.raises(DraftError):
        import_draft(store, site, dpath)


def test_import_draft_rejects_non_empty_devices(tmp_path):
    store, site = _setup_site(tmp_path)
    d = _draft()
    d["devices"] = [{"code": "x"}]
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    with pytest.raises(DraftError):
        import_draft(store, site, dpath)


def test_import_draft_accepts_surface_features_key(tmp_path):
    store, site = _setup_site(tmp_path)
    d = _draft()
    d["surface_features"] = d.pop("surfaces")
    # keep set
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    n = import_draft(store, site, dpath)
    assert n == 15


def test_import_draft_prefers_surfaces_key(tmp_path):
    store, site = _setup_site(tmp_path)
    d = _draft()
    # add a conflicting surface_features with one bogus surface
    d["surface_features"] = [{"id": "bogus", "type": "curb", "geom": "polyline", "xy": [[0, 0], [1, 1]], "by": "operator"}]
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    n = import_draft(store, site, dpath)
    assert n == 15
    ids = [f["properties"]["id"] for f in labels.read_labels(store, site)["features"]]
    assert "bogus" not in ids


def test_import_draft_rejects_empty_surfaces(tmp_path):
    store, site = _setup_site(tmp_path)
    d = _draft()
    d["surfaces"] = []
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    with pytest.raises(DraftError):
        import_draft(store, site, dpath)


def test_import_draft_rejects_non_list_surfaces(tmp_path):
    store, site = _setup_site(tmp_path)
    d = _draft()
    d["surfaces"] = "nope"
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    with pytest.raises(DraftError):
        import_draft(store, site, dpath)


def test_import_draft_rejects_bad_site_id(tmp_path):
    store, _ = _setup_site(tmp_path)
    d = _draft()
    d["set"] = "bad/site"
    dpath = tmp_path / "draft.json"
    dpath.write_text(json.dumps(d))
    with pytest.raises(DraftError):
        import_draft(store, "bad/site", dpath)


def test_render_injects_surface_types_and_escapes_script():
    import json
    import re

    from twin.labeltool import SURFACE_MAP, render

    data = {"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05, "w": 10, "h": 10}, "missing": [], "window_fallback": False, "no_imagery": False, "notes": "</script><script>x"}
    html = render(data)
    assert "__DATA__" not in html
    assert "__PURE__" not in html
    m = re.search(r"const DATA=(.*?);", html, re.DOTALL)
    assert m
    # unescape not needed for parse of escaped? JSON parser handles \\u003c as <
    d = json.loads(m.group(1))
    assert d["site"] == "s1"
    assert len(d["surface_types"]) == 11
    assert "id" in d["schema_fields"] and "evidence" in d["schema_fields"]
    assert d["notes"] == "</script><script>x"
    data_json = html.split("const DATA=", 1)[1].split(";", 1)[0]
    assert "</script><script>x" not in data_json
    assert "\\u003c" in data_json
    assert d["notes"] == "</script><script>x"

    assert len(SURFACE_MAP) == 11
    assert "schema_fields" in html
    assert '"id"' in html and '"evidence"' in html


def test_rendered_html_has_no_removed_bindings():
    from twin.labeltool import render

    html = render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}})
    import re

    for tok in ("NAME", "STORE", "TITLES"):
        assert not re.search(r"\b" + tok + r"\b", html), tok
    assert "DEV_STORE" in html
    assert "SITE" in html


def test_template_has_no_hardcoded_audit_titles():
    from twin.labeltool import render

    html = render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}})
    assert "TITLES=" not in html
    assert "audit-" not in html
    assert "<title>Labelling tool</title>" in html


def test_rendered_script_has_one_script_element():
    from twin.labeltool import render

    html = render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}})
    import re
    assert len(re.findall(r"<script>", html)) == 1
    assert len(re.findall(r"</script>", html)) == 1


def test_rendered_script_declarations_are_unique():
    from twin.labeltool import render

    html = render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}})
    import re
    m = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    script = m.group(1)
    for decl in ("function renderAll", "function fileOf", "let state", "function snapPt",
                 "function fit", "function draw", "function finish", "const toPx"):
        import re as _re
        n = len(_re.findall(r"\b" + _re.escape(decl) + r"\b", script))
        assert n == 1, (decl, n)


def test_prototype_ui_markers_present():
    import re

    from twin.labeltool import render

    html = render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}})
    for rid in ("map", "mapwrap", "ca", "cb", "strip", "slist", "slots", "stype", "snap", "fuseinfo",
                "legend", "hint", "json", "setid", "frz", "freeze", "newver", "dl", "reset",
                "sub", "nsurf", "nsup", "la", "lb", "tri", "dsup", "dsave", "dclear", "dkind",
                "dcode", "dval", "dplaque"):
        assert re.search(r'id="' + rid + r'"', html), rid
    for fn in ("function fit(", "function draw(", "function snapPt(", "const toPx=",
               "unscr=", "function finish(", "function triangulate(", "function drawStrip(",
               "function drawPanes(", "function renderAll(", "function fileOf(", "toW=",
               "function ray(", "function proj(", "function drawPane("):
        assert fn in html, fn
    for s in ("LiDAR intensity", "Orthoimage", "Combined", "Height", "Click to add vertices",
              "Frames", "Mark the device face centre in both views", "Traced features", "Supports"):
        assert s in html, s
    for bg in ("intensity", "ortho", "fused", "height"):
        assert f'data-bg="{bg}"' in html, bg

