import json
import re

import pytest

from tests.test_labelraster import _mk_area_source_build
from twin import labels
from twin.labeltool import (
    SURFACE_MAP,
    AreaSource,
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
              "Frames", "Mark the device face centre in both views", "Traced features", "Supports",
              "Snap", "Trace", "Device", "Enter", "Backspace", "Escape", "pointerdown", "dblclick",
              "wheel", "data-t"):
        assert s in html, s
    for bg in ("intensity", "ortho", "fused", "height"):
        assert f'data-bg="{bg}"' in html, bg



def _render_html():
    from twin.labeltool import render

    return render({"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}, "missing": "MISSING_IMG", "window_fallback": "WIN_FB", "no_imagery": False})


def test_template_boot_fetches_site_and_labels():
    html = _render_html()
    assert "/api/r/labels/${encodeURIComponent(SITE)}" in html
    assert "/api/r/labels/${SITE}/labels" in html
    assert "state.loaded=true" in html or "state.loaded = true" in html
    assert "state.meta=meta" in html or "state.meta = meta" in html


def test_template_gates_tracing_until_loaded():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert "requireEditable()" in src
    assert "PURE.editsAllowed(state.meta,state.loaded)" in src or "PURE.editsAllowed(state.meta, state.loaded)" in src
    # pointerdown path
    assert 'if(tab!=="surf")return;if(!requireEditable())return;cur.push' in src or 'if(tab!=="surf")return; if(!requireEditable())return;cur.push' in src
    # finish path
    assert "function finish(){if(!requireEditable())return;" in src
    # delete path
    assert "if(!s&&!d)return;if(!requireEditable())return;" in src
    # per-row type change path
    assert "if(!requireEditable()){sel.value=f.rawType;return;}" in src


def test_template_queue_put_status_handling():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert "state.stopped||!state.loaded||!PURE.editsAllowed" in src
    assert "res.status===409" in src
    assert "state.stopped=true;dirty=false;showBanner(\"reload: the file may have changed\")" in src
    assert "res.status===422" in src


def test_template_pagehide_keepalive():
    html = _render_html()
    assert "pagehide" in html
    assert "beforeunload" in html
    assert "keepalive" in html


def test_template_download_json_is_legacy():
    html = _render_html()
    assert "Download JSON (legacy)" in html


def test_template_fileof_uses_meta_version():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert 'version:state.meta.version' in src
    assert 'source:"labels-store"' in src


def test_template_has_google_buttons():
    html = _render_html()
    assert "Satellite" in html and "Street View" in html
    assert "/api/r/geo/latlon" in html
    assert "toW(...unscr(cv.clientWidth/2,cv.clientHeight/2))" in html
    assert "maps/@?api=1&map_action=map" in html
    assert "map_action=pano" in html


def test_template_has_control_field():
    html = _render_html()
    for v in ("signalised", "stop_controlled", "uncontrolled", "mid_block"):
        assert v in html
    assert "/api/w/labels/" in html
    assert "metaBody" in html


def test_template_frozen_meta_display():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert "PURE.siteSummary(state.meta)" in src
    # frz line uses siteSummary
    for line in src.splitlines():
        if "frz" in line and "textContent" in line:
            assert "sha256" not in line


def test_template_server_owned_buttons_disabled():
    html = _render_html()
    assert 'id="freeze" disabled' in html
    assert 'id="newver" disabled' in html
    assert 'id="reset" disabled' in html
    assert "server-owned; use twin labels approve/new-version" in html


def test_template_no_imagery_disables_snap():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert "DATA.no_imagery" in src
    assert "snapPt" in src
    assert "if(DATA.no_imagery)return p;" in src


def test_template_has_banners():
    html = _render_html()
    assert "DATA.missing" in html
    assert "DATA.window_fallback" in html
    assert 'id="banner"' in html


def test_template_dev_store_key():
    html = _render_html()
    assert "labeltool-devices-" in html
    assert "DEV_STORE" in html
    # only supports/devices persisted
    assert "supports:state.supports,devices:state.devices" in html or 'supports:state.supports,devices:state.devices' in html


def test_template_per_row_type_select():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert "PURE.changeSurfaceType(f,sel.value,DATA.surface_map)" in src
    assert "queuePut();renderAll();" in src or "queuePut(); renderAll();" in src
    assert "sel.onchange" in src


def test_template_meta_save_allowed_when_frozen():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    m = re.search(r"async function saveMeta\(\)\{(.*?)\nasync function boot\(\)", src, re.DOTALL)
    assert m, "saveMeta block not found"
    save_meta = m.group(1)
    guard = save_meta.split("const body=", 1)[0]
    assert "requireEditable" not in guard
    assert "editsAllowed" not in guard
    assert "frozen" not in guard
    assert "state.loaded" in guard and "state.meta" in guard and "!state.stopped" in guard
    assert 'showBanner("Metadata saved")' in save_meta
    # labels/tracing gates remain unchanged
    assert "if(tab!==\"surf\")return;if(!requireEditable())return;cur.push" in src
    assert "function finish(){if(!requireEditable())return;" in src
    assert "if(!requireEditable()){sel.value=f.rawType;return;}" in src
    assert "if(!s&&!d)return;if(!requireEditable())return;" in src
    assert "PURE.editsAllowed(state.meta,state.loaded)" in src
    assert "if(state.stopped||!state.loaded||!PURE.editsAllowed(state.meta,state.loaded))return;dirty=true;" in src


def test_template_fileof_guards_failed_boot():
    with open("twin/templates/label_tool.html") as fh:
        src = fh.read()
    assert 'if(!state.loaded||!state.meta)return{set:SITE,version:1,source:"labels-store",surface_features:[]}' in src
    assert 'if($("dl"))$("dl").disabled=!state.loaded' in src

# --- M6b1: resolution/window/coverage ---

from twin.labeltool import (
    CELL,
    MAX_WINDOW_PX,
    MAX_WINDOW_SIDE_PX,
    WINDOW_MARGIN_M,
    _window_covered,
    fit_window,
    runs_for_area,
    window_for,
)


def _mk_area_build(store, area_name, drives_def, used_scenes):
    areas = store / "areas"
    areas.mkdir(parents=True, exist_ok=True)
    build = areas / f"{area_name}-twin"
    (build / "5_features").mkdir(parents=True, exist_ok=True)
    (areas / f"{area_name}.json").write_text(
        json.dumps(
            {
                "name": area_name,
                "dataset_version": drives_def.get("dataset_version", "v1.0-trainval"),
                "polygon": drives_def.get(
                    "polygon",
                    {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
                    },
                ),
                "drives": drives_def["drives"],
            }
        )
    )
    (build / "drives.json").write_text(
        json.dumps([{"scene": s} for s in used_scenes])
    )
    return build


def _mk_run(store, run_id, scene, dataset_version, stages_status):
    d = store / run_id
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "data": {"scene_token": scene, "nuscenes_version": dataset_version},
        "stages": [{"name": n, "status": st} for n, st in stages_status.items()],
    }
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


def _mk_site_with_labels(store, site, polygon, features_xy=None, *, features=None):
    from pathlib import Path as _Path

    store = _Path(store)
    d = store / "labels" / site
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": site,
        "role": "dev",
        "polygon": polygon,
        "version": 1,
        "approved_by": None,
        "approved_at": None,
        "crs": "EPSG:32619",
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_area": "a",
        "frozen": False,
    }
    (d / "site.json").write_text(json.dumps(meta))
    feats = []
    for i, xy in enumerate(features_xy or []):
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": xy},
                "properties": {"id": f"f{i}", "element": "marking", "type": "solid_line", "origin": "operator"},
            }
        )
    (d / "labels.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features if features is not None else feats})
    )


def test_window_for_fits_union(tmp_path):
    store = tmp_path / "store"
    # polygon alone 30x20, label extends union beyond polygon on right/top but still within fit window
    poly = {"type": "Polygon", "coordinates": [[[10, 10], [40, 10], [40, 30], [10, 30], [10, 10]]]}
    _mk_site_with_labels(store, "s", poly, features_xy=[[[35, 25], [55, 45]]])
    x0, y1, info = window_for(store, "s")
    assert info["fallback"] is False
    assert x0 == 8.0
    assert y1 == 47.0
    assert info["cell"] == 0.05
    assert info["downsampled"] is False
    assert_window_covers(info, 10, 10, 55, 45)


def test_window_for_downsamples_union_above_limit(tmp_path):
    store = tmp_path / "store"
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [40, 0], [40, 40], [0, 40], [0, 0]]]}
    # union exceeds fit size -> downsampled to stay within budget
    _mk_site_with_labels(store, "s", poly, features_xy=[[[150, 150], [180, 180]]])
    x0, y1, info = window_for(store, "s")
    assert info["fallback"] is False
    assert x0 == -2.0
    assert y1 == 182.0
    assert info["cell"] > 0.05
    assert info["width"] * info["height"] <= MAX_WINDOW_PX
    assert max(info["width"], info["height"]) <= MAX_WINDOW_SIDE_PX
    assert info["downsampled"] is True
    assert_window_covers(info, 0, 0, 180, 180)


def test_window_fits_slightly_over_80x75_at_5cm(tmp_path):
    store = tmp_path / "store"
    # polygon near limit, label nudges union to 80.05m x 75.05m; fit at 5cm if within budget
    minx, miny = 0.0, 0.0
    poly = {"type": "Polygon", "coordinates": [[[minx, miny], [80.0, miny], [80.0, 75.0], [minx, 75.0], [minx, miny]]]}
    _mk_site_with_labels(store, "s", poly, features_xy=[[[79.0, 74.0], [80.05, 75.05]]])
    x0, y1, info = window_for(store, "s")
    assert info["fallback"] is False
    assert x0 == -2.0
    assert y1 == 77.05
    assert info["cell"] == 0.05
    assert info["downsampled"] is False
    assert_window_covers(info, 0, 0, 80.05, 75.05)


def test_runs_for_area_newest_per_token(tmp_path):
    store = tmp_path / "store"
    area_def = {
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "drives": [{"scene": "s1", "scene_token": "t1"}, {"scene": "s2", "scene_token": "t2"}],
    }
    _mk_area_build(store, "a1", area_def, ["s1", "s2"])
    full = {"load": "ok", "align": "ok", "ground": "ok", "colour": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    newer = _mk_run(store, "20261102-000000-bbbbbb", "t1", "v1.0-trainval", full)
    r2 = _mk_run(store, "20261103-000000-cccccc", "t2", "v1.0-trainval", full)
    paths = runs_for_area(store, "a1")
    assert paths == [newer, r2]


def test_runs_for_area_falls_back_to_ground_only(tmp_path):
    store = tmp_path / "store"
    area_def = {
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "drives": [{"scene": "s1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["s1"])
    ground_only = {"load": "ok", "align": "ok", "ground": "ok"}
    r = _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", ground_only)
    paths = runs_for_area(store, "a1")
    assert paths == [r]


def test_runs_for_area_skips_failed_load(tmp_path):
    store = tmp_path / "store"
    area_def = {
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "drives": [{"scene": "s1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["s1"])
    failed_load = {"load": "failed", "align": "ok", "ground": "ok", "colour": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", failed_load)
    paths = runs_for_area(store, "a1")
    assert paths == []


def test_runs_for_area_missing_token(tmp_path):
    store = tmp_path / "store"
    area_def = {
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "drives": [{"scene": "s1", "scene_token": "t1"}, {"scene": "s2", "scene_token": "t2"}],
    }
    _mk_area_build(store, "a1", area_def, ["s1", "s2"])
    full = {"load": "ok", "align": "ok", "ground": "ok", "colour": "ok"}
    r1 = _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    # no run for t2
    paths = runs_for_area(store, "a1")
    assert paths == [r1]


def test_runs_for_area_filters_dataset_version(tmp_path):
    store = tmp_path / "store"
    area_def = {
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "drives": [{"scene": "s1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["s1"])
    full = {"load": "ok", "align": "ok", "ground": "ok", "colour": "ok"}
    good = _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    wrong_newest = _mk_run(store, "20261103-000000-cccccc", "t1", "v1.0-mini", full)
    paths = runs_for_area(store, "a1")
    assert paths == [good]
    assert wrong_newest not in paths


def test_window_covered_rejects_outside_area():
    area_def = {
        "name": "a1",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
    }
    # window far outside
    with pytest.raises(DraftError) as exc:
        _window_covered(area_def, 1000, 1000)
    msg = str(exc.value)
    assert "a1" in msg
    assert "--area/--areas" in msg or "--area" in msg


def test_window_for_skips_malformed_polygon_and_uses_label_coords(tmp_path):
    store = tmp_path / "store"
    bad = {"type": "Nope"}
    _mk_site_with_labels(store, "badtype", bad, features_xy=[[[5, 5], [25, 35]]])
    x0, y1, info = window_for(store, "badtype")
    assert info["fallback"] is False
    assert x0 == 3.0
    assert y1 == 37.0
    assert_window_covers(info, 5, 5, 25, 35)

    missing = {"type": "Polygon"}  # missing coordinates
    _mk_site_with_labels(store, "missing", missing, features_xy=[[[1, 2], [11, 12]]])
    x0, y1, info = window_for(store, "missing")
    assert info["fallback"] is False
    assert x0 == -1.0
    assert y1 == 14.0
    assert_window_covers(info, 1, 2, 11, 12)


def test_window_for_handles_features_null(tmp_path):
    store = tmp_path / "store"
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]}
    _mk_site_with_labels(store, "s", poly, features=[])
    # explicit null in labels.geojson (regression guard: reverting `or []` would break)
    (store / "labels" / "s" / "labels.geojson").write_text(
        '{"type":"FeatureCollection","features":null}'
    )
    x0, y1, info = window_for(store, "s")
    assert info["fallback"] is False
    assert x0 == -2.0
    assert y1 == 22.0
    assert_window_covers(info, 0, 0, 20, 20)


def test_window_for_raises_on_empty_union(tmp_path):
    store = tmp_path / "store"
    _mk_site_with_labels(store, "empty", {"type": "Nope"}, features=None)
    with pytest.raises(DraftError) as exc:
        window_for(store, "empty")
    msg = str(exc.value)
    assert "empty" in msg
    assert "no finite polygon or label geometry" in msg


def test_drive_tokens_uses_supplied_defined_not_sibling_json(tmp_path):
    from twin.areastore import open_area

    build = tmp_path / "a1-twin"
    build.mkdir()
    (build / "drives.json").write_text(json.dumps([{"scene": "s1"}, {"scene": "s2"}]))
    sibling = {
        "drives": [
            {"scene": "s1", "scene_token": "OLD1"},
            {"scene": "s2", "scene_token": "OLD2"},
        ]
    }
    (tmp_path / "a1.json").write_text(json.dumps(sibling))
    defined = {
        "drives": [
            {"scene": "s1", "scene_token": "NEW1"},
            {"scene": "s2", "scene_token": "NEW2"},
        ]
    }
    assert open_area(tmp_path, build).drive_tokens(defined) == ["NEW1", "NEW2"]
    assert open_area(tmp_path, build).drive_tokens() == ["OLD1", "OLD2"]


# --- M6b2: generate / CLI support helpers ---

from twin.labeltool import generate


def _minimal_raster_data(site="s1", x0=0.0, y1=20.0):
    from twin.labelraster import blank_window

    data = blank_window(site, x0, y1, [])
    data["no_imagery"] = True
    return data


def _patch_export_window(monkeypatch, capture=None, data=None):
    calls = []
    capture = capture if capture is not None else {}
    capture["calls"] = calls

    def fake_export_window(store, runs, *, site, x0, y1, **kwargs):
        calls.append({"store": store, "runs": list(runs), "site": site, "x0": x0, "y1": y1, **kwargs})
        if callable(data):
            return data(site=site, x0=x0, y1=y1, runs=runs, **kwargs)
        if data is not None:
            out = dict(data)
            # fake window intentionally differs from the 1600x1500 fixture images; real dimensions are pinned by tests/test_labelraster.py
            out.setdefault("site", site)
            out.setdefault("window", {"x0": x0, "y1": y1, "g": kwargs.get("cell", 0.05), "w": kwargs.get("width", 1600), "h": kwargs.get("height", 1500)})
            return out
        out = _minimal_raster_data(site=site, x0=x0, y1=y1)
        # fake window intentionally differs from the 1600x1500 fixture images; real dimensions are pinned by tests/test_labelraster.py
        out["window"] = {"x0": x0, "y1": y1, "g": kwargs.get("cell", 0.05), "w": kwargs.get("width", 1600), "h": kwargs.get("height", 1500)}
        return out

    # generate does lazy `from twin import labelraster` and calls export_window
    import twin.labelraster as lr

    monkeypatch.setattr(lr, "export_window", fake_export_window)
    return capture


def assert_window_covers(info, minx, miny, maxx, maxy, margin=WINDOW_MARGIN_M):
    x0, y1 = info["x0"], info["y1"]
    g = info.get("cell", info.get("g"))
    w = info.get("width", info.get("w"))
    h = info.get("height", info.get("h"))
    assert x0 <= minx - margin + 1e-9
    assert y1 >= maxy + margin - 1e-9
    assert x0 + w * g >= maxx + margin - 1e-9
    assert y1 - h * g <= miny - margin + 1e-9


def _write_draft(path, site, n=15):
    draft = _draft()
    draft["set"] = site
    # trim/extend to n
    if n <= 15:
        draft["surfaces"] = draft["surfaces"][:n]
    else:
        extra = []
        for i in range(16, n + 1):
            extra.append({"id": f"t{i:03d}", "type": "curb", "geom": "polyline", "xy": [[1, 1], [2, 2]], "px": [[20, 380], [40, 360]], "evidence": "intensity", "by": "operator"})
        draft["surfaces"] = draft["surfaces"] + extra
    path.write_text(json.dumps(draft))
    return path


def test_generate_resolves_area_outside_store(tmp_path, monkeypatch):
    store = tmp_path / "store"
    areas_root = tmp_path / "areasroot"
    area_def = {
        "name": "demo",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    build = areas_root / "demo-twin"
    (build / "5_features").mkdir(parents=True)
    (areas_root / "demo.json").write_text(json.dumps(area_def))
    (build / "drives.json").write_text(json.dumps([]))
    _patch_export_window(monkeypatch)
    out = generate(store, "s1", area="demo", areas_root=areas_root)
    assert out == store / "labels" / "s1" / "tool.html"
    assert out.is_file()


def test_generate_accepts_explicit_window(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[-10, -10], [120, -10], [120, 120], [-10, 120], [-10, -10]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    cap = _patch_export_window(monkeypatch)
    out = generate(store, "s1", area="a1", x0=5.0, y1=80.0)
    assert out.is_file()
    assert cap["calls"]
    call = cap["calls"][0]
    assert call["x0"] == 5.0
    assert call["y1"] == 80.0
    assert call["width"] == 1600
    assert call["height"] == 1500
    assert call["cell"] == pytest.approx(0.05)
    html = out.read_text()
    m = re.search(r"const DATA=(.*?);", html, re.DOTALL)
    assert m
    d = json.loads(m.group(1))
    window = d["window"]
    assert window["w"] == 1600
    assert window["h"] == 1500
    assert window["g"] == pytest.approx(0.05)
    assert '"window_fallback":false' in html


def test_generate_creates_empty_site_for_b_and_c(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [60, 0], [60, 60], [0, 60], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    _patch_export_window(monkeypatch)
    for site in ("site-b", "site-c"):
        out = generate(store, site, area="a1")
        assert out.is_file()
        assert labels.read_labels(store, site)["features"] == []
        assert labels.read_site(store, site).role == "audit"


def test_two_sites_from_different_polygons_get_different_windows(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area1 = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    area2 = {
        "name": "a2",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[100, 100], [120, 100], [120, 120], [100, 120], [100, 100]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area1, [])
    _mk_area_build(store, "a2", area2, [])
    cap = _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1")
    generate(store, "s2", area="a2")
    assert len(cap["calls"]) == 2
    w1 = (cap["calls"][0]["x0"], cap["calls"][0]["y1"])
    w2 = (cap["calls"][1]["x0"], cap["calls"][1]["y1"])
    assert w1 != w2


def test_generate_writes_page_under_store_only(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    _patch_export_window(monkeypatch)
    out = generate(store, "s1", area="a1")
    assert out == store / "labels" / "s1" / "tool.html"
    files = sorted(p.name for p in (store / "labels" / "s1").iterdir())
    assert "tool.html" in files
    # only store labels dir has this tool html for site
    assert not (tmp_path / "tool.html").exists()


def test_generate_keeps_existing_site_meta_and_labels_bytes(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    # add a feature so labels bytes are non-trivial
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "keep", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    site_bytes = (store / "labels" / "s1" / "site.json").read_bytes()
    labels_bytes = (store / "labels" / "s1" / "labels.geojson").read_bytes()
    _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1")
    assert (store / "labels" / "s1" / "site.json").read_bytes() == site_bytes
    assert (store / "labels" / "s1" / "labels.geojson").read_bytes() == labels_bytes


def test_generate_imports_before_window(tmp_path, monkeypatch):
    store = tmp_path / "store"
    # small site/area polygon so imported far point expands the auto window
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    d = _draft()
    d["set"] = "s1"
    d["surfaces"] = [{"id": "far", "type": "curb", "geom": "polyline", "xy": [[150, 150], [160, 160]], "px": [[0, 0], [1, 1]], "evidence": "intensity", "by": "operator"}]
    dpath = tmp_path / "d.json"
    dpath.write_text(json.dumps(d))
    cap = _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1", import_path=dpath, replace=True)
    assert cap["calls"]
    # imported geometry reaches 160,160 so auto window must be computed after import
    assert cap["calls"][0]["x0"] == pytest.approx(-2.0)
    assert cap["calls"][0]["y1"] == pytest.approx(162.0)
    assert cap["calls"][0]["width"] == 3200
    assert cap["calls"][0]["height"] == 3200
    assert cap["calls"][0]["cell"] == pytest.approx(0.05125)
    assert labels.read_labels(store, "s1")["features"][0]["properties"]["id"] == "far"


def test_generate_requires_area_when_site_missing(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _patch_export_window(monkeypatch)
    with pytest.raises(DraftError):
        generate(store, "s1")


def test_generate_rejects_half_a_window(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _patch_export_window(monkeypatch)
    with pytest.raises(DraftError):
        generate(store, "s1", area="a", x0=1.0)
    with pytest.raises(DraftError):
        generate(store, "s1", area="a", y1=1.0)


def test_generate_existing_site_without_runs_raises(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    _patch_export_window(monkeypatch)
    with pytest.raises(DraftError, match="no resolvable runs"):
        generate(store, "s1", area="a1")


def test_generate_new_site_without_runs_writes_blank_page(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    _patch_export_window(monkeypatch)
    out = generate(store, "s1", area="a1")
    html = out.read_text()
    assert '"no_imagery":true' in html


def test_generate_reset_recreates_existing_site_empty(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "x", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1", reset=True)
    assert labels.read_labels(store, "s1")["features"] == []


def test_generate_reset_refuses_frozen_site(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    labels.approve(store, "s1", "op")
    before = _site_label_bytes(store, "s1")
    _patch_export_window(monkeypatch)
    with pytest.raises(DraftError):
        generate(store, "s1", area="a1", reset=True)
    assert _site_label_bytes(store, "s1") == before


def test_generate_import_replace_gives_exactly_fifteen(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[-50, -50], [200, -50], [200, 200], [-50, 200], [-50, -50]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "extra", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    dpath = _write_draft(tmp_path / "d.json", "s1", 15)
    _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1", import_path=dpath, replace=True)
    assert len(labels.read_labels(store, "s1")["features"]) == 15


def test_generate_without_cv2_writes_partial_page(tmp_path, monkeypatch):
    import builtins
    import sys

    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    # do not patch export_window; block cv2 so real labelraster takes no-cv2 path
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "cv2":
            raise ImportError("blocked")
        return real_import(name, *a, **k)

    monkeypatch.setitem(sys.modules, "cv2", None)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = generate(store, "s1", area="a1")
    assert out.is_file()
    html = out.read_text()
    assert "s1" in html


def test_generate_passes_dataset_root(tmp_path, monkeypatch):
    from twin.dataset import DatasetConfig

    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    cap = _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1")
    assert cap["calls"][0]["nuscenes_root"] == DatasetConfig.from_env().root


def test_gitignore_blocks_generated_pages(tmp_path):
    import subprocess
    from pathlib import Path

    repo = Path.cwd()
    gi = (repo / ".gitignore").read_text()
    assert "/labels/" in gi
    assert "tool.html" in gi
    r1 = subprocess.run(["git", "check-ignore", "-q", "tool.html"], cwd=repo, check=False)
    r2 = subprocess.run(["git", "check-ignore", "-q", "labels/x"], cwd=repo, check=False)
    assert r1.returncode == 0
    assert r2.returncode == 0


def test_generate_reset_preserves_audit_role(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1", reset=True)
    assert labels.read_site(store, "s1").role == "audit"


def test_generate_reset_preserves_non_audit_role(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="dev")
    _patch_export_window(monkeypatch)
    generate(store, "s1", area="a1", reset=True)
    assert labels.read_site(store, "s1").role == "dev"


def _site_label_bytes(store, site):
    base = store / "labels" / site
    return (base / "site.json").read_bytes(), (base / "labels.geojson").read_bytes()


def test_generate_reset_missing_area_leaves_site_unchanged(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "keep", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    before = _site_label_bytes(store, "s1")
    _patch_export_window(monkeypatch)
    with pytest.raises((DraftError, FileNotFoundError)):
        generate(store, "s1", area="missing-area", areas_root=store / "areas", reset=True)
    assert _site_label_bytes(store, "s1") == before


def test_generate_reset_uncovered_explicit_window_leaves_site_unchanged(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "keep", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    before = _site_label_bytes(store, "s1")
    _patch_export_window(monkeypatch)
    with pytest.raises(DraftError):
        generate(store, "s1", area="a1", areas_root=store / "areas", reset=True, x0=1000.0, y1=1000.0)
    assert _site_label_bytes(store, "s1") == before


def test_generate_reset_zero_run_existing_site_raises_and_leaves_unchanged(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "keep", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    before = _site_label_bytes(store, "s1")
    _patch_export_window(monkeypatch)
    with pytest.raises(DraftError, match="no resolvable runs"):
        generate(store, "s1", area="a1", areas_root=store / "areas", reset=True)
    assert _site_label_bytes(store, "s1") == before


def test_generate_reset_bad_import_leaves_site_unchanged(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}, "properties": {"id": "keep", "element": "marking", "type": "solid_line", "origin": "operator"}})
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    before = _site_label_bytes(store, "s1")

    bad = {"set": "other", "version": 1, "surfaces": [{"id": "x", "type": "curb", "geom": "polyline", "xy": [[0, 0], [1, 1]], "by": "operator"}], "supports": [], "devices": []}
    dpath = tmp_path / "bad.json"
    dpath.write_text(json.dumps(bad))
    _patch_export_window(monkeypatch)

    with pytest.raises(DraftError):
        generate(store, "s1", area="a1", areas_root=store / "areas", reset=True, import_path=dpath, replace=True)
    assert _site_label_bytes(store, "s1") == before

# --- transactional reset/create (M6b2 atomicity) ---


def _site_dir_bytes(store, site):
    base = store / "labels" / site
    if not base.exists():
        return None
    return {
        p.relative_to(base).as_posix(): p.read_bytes()
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


def _raise_export(*args, **kwargs):
    raise RuntimeError("boom")


def test_generate_reset_export_failure_restores_site_byte_identical(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]},
            "properties": {
                "id": "keep",
                "element": "marking",
                "type": "solid_line",
                "origin": "operator",
            },
        }
    )
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    (store / "labels" / "s1" / "labels.v1.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"snap":1}]}\n'
    )
    before = _site_dir_bytes(store, "s1")
    assert before is not None
    for name in ("site.json", "labels.geojson", "labels.v1.geojson"):
        assert name in before

    import twin.labelraster as lr

    monkeypatch.setattr(lr, "export_window", _raise_export)
    with pytest.raises(RuntimeError, match="boom"):
        generate(store, "s1", area="a1", areas_root=store / "areas", reset=True)
    assert _site_dir_bytes(store, "s1") == before


def test_generate_new_site_export_failure_removes_labels_dir(tmp_path, monkeypatch):
    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [],
    }
    _mk_area_build(store, "a1", area_def, [])
    site_dir = store / "labels" / "s1"
    assert not site_dir.exists()

    import twin.labelraster as lr

    monkeypatch.setattr(lr, "export_window", _raise_export)
    with pytest.raises(RuntimeError, match="boom"):
        generate(store, "s1", area="a1", areas_root=store / "areas")
    assert not site_dir.exists()


def test_generate_reset_success_replaces_site_contents(tmp_path, monkeypatch):
    import tempfile
    from pathlib import Path

    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]},
            "properties": {
                "id": "old",
                "element": "marking",
                "type": "solid_line",
                "origin": "operator",
            },
        }
    )
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    tmpdir = Path(tempfile.gettempdir())
    before_tmp = set(tmpdir.glob("labeltool-site-*"))
    _patch_export_window(monkeypatch)
    out = generate(store, "s1", area="a1", areas_root=store / "areas", reset=True)
    assert out.is_file()
    assert labels.read_labels(store, "s1")["features"] == []
    assert labels.read_site(store, "s1").frozen is False
    after_tmp = set(tmpdir.glob("labeltool-site-*"))
    assert after_tmp == before_tmp


def test_generate_reset_import_failure_restores_bytes(tmp_path, monkeypatch):
    import sys

    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[-50, -50], [200, -50], [200, 200], [-50, 200], [-50, -50]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]},
            "properties": {
                "id": "keep",
                "element": "marking",
                "type": "solid_line",
                "origin": "operator",
            },
        }
    )
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    (store / "labels" / "s1" / "labels.v1.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"snap":1}]}\n'
    )
    before = _site_dir_bytes(store, "s1")
    dpath = _write_draft(tmp_path / "d.json", "s1", 15)
    _patch_export_window(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("import boom")

    mod = sys.modules[generate.__module__]
    monkeypatch.setattr(mod, "import_draft", boom)
    with pytest.raises(RuntimeError, match="import boom"):
        generate(
            store,
            "s1",
            area="a1",
            areas_root=store / "areas",
            reset=True,
            import_path=dpath,
            replace=True,
        )
    assert _site_dir_bytes(store, "s1") == before


def test_generate_snapshot_failure_leaves_site_unchanged(tmp_path, monkeypatch):
    import shutil
    import tempfile
    from pathlib import Path

    store = tmp_path / "store"
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    _mk_area_build(store, "a1", area_def, ["sc1"])
    full = {"load": "ok", "align": "ok", "ground": "ok"}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    labels.draft(store, "s1", "a1", areas_root=store / "areas", role="audit")
    fc = labels.read_labels(store, "s1")
    fc["features"].append(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]},
            "properties": {
                "id": "keep",
                "element": "marking",
                "type": "solid_line",
                "origin": "operator",
            },
        }
    )
    labels.write_labels(store, "s1", fc, expected_version=labels.read_site(store, "s1").version)
    site_json = (store / "labels" / "s1" / "site.json").read_bytes()
    labels_geo = (store / "labels" / "s1" / "labels.geojson").read_bytes()
    tmpdir = Path(tempfile.gettempdir())
    before_tmp = set(tmpdir.glob("labeltool-site-*"))

    calls = {"n": 0}

    def boom_copytree(*args, **kwargs):
        calls["n"] += 1
        raise OSError("snapshot boom")

    monkeypatch.setattr(shutil, "copytree", boom_copytree)
    _patch_export_window(monkeypatch)
    with pytest.raises(OSError, match="snapshot boom"):
        generate(store, "s1", area="a1", areas_root=store / "areas", reset=True)

    assert calls["n"] == 1
    site_dir = store / "labels" / "s1"
    assert site_dir.is_dir()
    assert (site_dir / "site.json").read_bytes() == site_json
    assert (site_dir / "labels.geojson").read_bytes() == labels_geo
    after_tmp = set(tmpdir.glob("labeltool-site-*"))
    assert after_tmp == before_tmp


def test_generate_area_build_marks_ortho_unavailable(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    _twin_dir, _area_def = _mk_area_source_build(tmp_path)
    # place areas under store/areas? _mk_area_source_build created under tmp_path/areas
    # move? Instead set areas_root
    areas_root = tmp_path / "areas"
    data = _minimal_raster_data("s1", -2.0, 22.0)
    data["no_imagery"] = False
    data["frames"] = []
    cap = _patch_export_window(monkeypatch, data=data)
    from twin.labeltool import generate

    generate(store, "s1", area="a1", areas_root=areas_root)
    assert isinstance(cap["calls"][0]["runs"][0], AreaSource)
    assert cap["calls"][0]["x0"] == pytest.approx(-2.0)
    assert cap["calls"][0]["y1"] == pytest.approx(22.0)
    html = (store / "labels" / "s1" / "tool.html").read_text()
    assert '"unavailable":["ortho","fused"]' in html
    assert "no usable camera frames (check a1-merged/drives and the nuScenes root)" in html


def test_template_missing_guard_and_fallback_branch():
    import importlib.resources as r

    t = r.files("twin").joinpath("templates/label_tool.html").read_text()
    assert 'if(DATA.missing&&DATA.missing.length)' in t
    assert 'Array.isArray(DATA.missing)' in t
    assert 'else if(DATA.window_fallback)showBanner("' in t
    assert 'Site larger than 80×75 m: showing the 80×75 m centred on the extent.' not in t
    assert 'Window does not cover the whole site.' in t


def test_window_for_store_fit_uses_margin(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    _mk_site_with_labels(store, "s", {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]}, features_xy=[[[30, 0], [35, 0]]])
    from twin.labeltool import window_for

    wx0, wy1, info = window_for(store, "s")
    assert wx0 == -2.0
    assert wy1 == 22.0
    assert info["fallback"] is False
    assert_window_covers(info, 0, 0, 35, 20)


def test_store_runs_win_over_area_build(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    _twin_dir, _area_def = _mk_area_source_build(tmp_path)
    areas_root = tmp_path / "areas"
    # create a store run

    from twin.runstore import STAGE_NAMES
    full = {n: "ok" for n in STAGE_NAMES}
    _mk_run(store, "20261101-000000-aaaaaa", "t1", "v1.0-trainval", full)
    # area def drives
    data = _minimal_raster_data("s1", 0.0, 20.0)
    cap = _patch_export_window(monkeypatch, data=data)
    from twin.labeltool import generate

    generate(store, "s1", area="a1", areas_root=areas_root)
    assert cap["calls"][0]["runs"] == [store / "20261101-000000-aaaaaa"]
    assert not isinstance(cap["calls"][0]["runs"][0], AreaSource)
    assert cap["calls"][0]["x0"] == -2.0
    assert cap["calls"][0]["y1"] == 22.0
    html = (store / "labels" / "s1" / "tool.html").read_text()
    assert '"unavailable"' not in html


def test_render_marks_unavailable_backgrounds():
    from twin.labeltool import render

    data = {"site": "s1", "window": {"x0": 0, "y1": 20, "g": 0.05}, "unavailable": ["ortho", "fused"]}
    html = render(data)
    assert "DATA.unavailable" in html
    assert "UNAV.has(b.dataset.bg)" in html
    assert "b.disabled=true" in html
    assert "b.title=" in html
    assert "Unavailable: the area build has no 6_colour orthoimage." in html
    assert "Ortho and Combined unavailable: the area build has no 6_colour orthoimage." in html


def test_fit_window_covers_polygon_with_margin():
    fit = fit_window(0, 0, 120, 110)
    assert fit["x0"] == -2.0
    assert fit["y1"] == 112.0
    assert fit["cell"] == 0.05
    assert fit["downsampled"] is False
    assert_window_covers(fit, 0, 0, 120, 110)


def test_fit_window_keeps_5cm_at_limit():
    fit = fit_window(0, 0, 156, 156)
    assert fit["width"] == 3200
    assert fit["height"] == 3200
    assert fit["cell"] == 0.05
    assert fit["width"] * fit["height"] == MAX_WINDOW_PX
    assert fit["downsampled"] is False


def test_fit_window_downsamples_above_limit():
    fit = fit_window(0, 0, 300, 300)
    assert fit["cell"] > CELL
    assert fit["width"] * fit["height"] <= MAX_WINDOW_PX
    assert max(fit["width"], fit["height"]) <= MAX_WINDOW_SIDE_PX
    assert fit["downsampled"] is True
    assert_window_covers(fit, 0, 0, 300, 300)


def test_fit_window_long_thin_uses_side_cap():
    fit = fit_window(0, 0, 1000, 10)
    assert max(fit["width"], fit["height"]) <= 8192
    assert fit["cell"] > CELL
    assert_window_covers(fit, 0, 0, 1000, 10)


def test_window_for_fits_large_area_polygon(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [120, 0], [120, 110], [0, 110], [0, 0]]]}
    _mk_site_with_labels(store, "s", poly)
    x0, y1, info = window_for(store, "s")
    assert x0 == -2.0
    assert y1 == 112.0
    assert info["cell"] == 0.05
    assert info["fallback"] is False
    assert_window_covers(info, 0, 0, 120, 110)


def test_generate_fits_large_area_polygon(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    areas = store / "areas"
    areas.mkdir()
    build = areas / "a1-twin"
    (build / "5_features").mkdir(parents=True)
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [120, 0], [120, 110], [0, 110], [0, 0]]]}
    (areas / "a1.json").write_text(json.dumps({"name": "a1", "polygon": poly, "drives": [{"scene": "s1", "scene_token": "t1"}]}))
    (build / "drives.json").write_text(json.dumps([{"scene": "s1"}]))
    cap = _patch_export_window(monkeypatch)
    from twin.labeltool import generate
    generate(store, "s1", area="a1", areas_root=areas)
    call = cap["calls"][0]
    assert call["x0"] == pytest.approx(-2.0)
    assert call["y1"] == pytest.approx(112.0)
    assert call["cell"] == pytest.approx(0.05)
    assert_window_covers(call, 0, 0, 120, 110)
    html = (store / "labels" / "s1" / "tool.html").read_text()
    m = re.search(r"const DATA=(.*?);", html, re.DOTALL)
    data = json.loads(m.group(1))
    assert data["window_fallback"] is False
    w = data["window"]
    assert w["g"] == pytest.approx(0.05)
    assert_window_covers(w, 0, 0, 120, 110)
    for (x, y) in [(0, 0), (120, 0), (120, 110), (0, 110)]:
        assert 0 <= (x - w["x0"]) / w["g"] <= w["w"]
        assert 0 <= (w["y1"] - y) / w["g"] <= w["h"]
    assert "Site larger than 80×75 m" not in html


def test_generate_downsamples_area_polygon(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    areas = store / "areas"
    areas.mkdir()
    build = areas / "a1-twin"
    (build / "5_features").mkdir(parents=True)
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [300, 0], [300, 300], [0, 300], [0, 0]]]}
    (areas / "a1.json").write_text(json.dumps({"name": "a1", "polygon": poly, "drives": [{"scene": "s1", "scene_token": "t1"}]}))
    (build / "drives.json").write_text(json.dumps([{"scene": "s1"}]))
    cap = _patch_export_window(monkeypatch)
    from twin.labeltool import generate
    generate(store, "s1", area="a1", areas_root=areas)
    call = cap["calls"][0]
    assert call["x0"] == pytest.approx(-2.0)
    assert call["y1"] == pytest.approx(302.0)
    assert call["cell"] > 0.05
    assert call["width"] * call["height"] <= MAX_WINDOW_PX
    assert_window_covers(call, 0, 0, 300, 300)
    html = (store / "labels" / "s1" / "tool.html").read_text()
    m = re.search(r"const DATA=(.*?);", html, re.DOTALL)
    data = json.loads(m.group(1))
    assert_window_covers(data["window"], 0, 0, 300, 300)
    assert "Site larger than 80×75 m" not in html


def test_template_large_window_keeps_native_snap_and_height():
    from pathlib import Path
    t = Path("twin/templates/label_tool.html").read_text()
    assert "Site larger than 80×75 m: showing the 80×75 m centred on the extent." not in t
    assert "Window does not cover the whole site." in t
    assert "80×75 m at 5 cm" not in t
    assert "W.g" in t
    assert "W.g>0.05+1e-9" in t
    assert "Math.max(0.02" in t
    assert "bd=10/view.k" in t
    assert "c.width=W.w;c.height=W.h" in t
