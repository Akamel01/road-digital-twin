import json
from pathlib import Path

import pytest

from twin import labels
from twin.labeltool import import_draft

DRAFT_A = Path.home() / "inputs" / "324" / "draft-A.json"


@pytest.mark.itest
@pytest.mark.skipif(not DRAFT_A.is_file(), reason="draft-A.json not available")
def test_draft_a_fifteen_surface_round_trip(tmp_path):
    store = tmp_path / "store"
    site = "seaport-intersection-A"
    # minimal site to import into
    (store / "labels" / site).mkdir(parents=True, exist_ok=True)
    meta = {
        "id": site,
        "role": "audit",
        "polygon": {"type": "Polygon", "coordinates": [[[332380, 4690000], [332480, 4690000], [332480, 4690100], [332380, 4690100], [332380, 4690000]]]},
        "version": 1,
        "approved_by": None,
        "approved_at": None,
        "crs": "EPSG:32619",
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_area": "seaport-intersection-A",
        "frozen": False,
    }
    (store / "labels" / site / "site.json").write_text(json.dumps(meta))
    (store / "labels" / site / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))

    data = json.loads(DRAFT_A.read_text())
    n = import_draft(store, site, DRAFT_A, replace=True)
    assert n == 15
    fc = labels.read_labels(store, site)
    feats = fc["features"]
    assert len(feats) == 15

    by_id = {f["properties"]["id"]: f for f in feats}
    draft_surfaces = data.get("surfaces") or data.get("surface_features") or []
    assert len(draft_surfaces) == 15

    # counts/types sanity from ledger: 5 double-yellow, 3 solid-white, 2 dashed-white, 2 ladder, 2 curb, 1 stop line
    raw_counts = {}
    for s in draft_surfaces:
        raw_counts[s["type"]] = raw_counts.get(s["type"], 0) + 1
    assert raw_counts.get("lane line, double yellow") == 5
    assert raw_counts.get("lane line, solid white") == 3
    assert raw_counts.get("lane line, dashed white") == 2
    assert raw_counts.get("crosswalk, ladder") == 2
    assert raw_counts.get("curb") == 2
    assert raw_counts.get("stop line") == 1

    for s in draft_surfaces:
        f = by_id[s["id"]]
        assert f["properties"]["source_marking_type"] == s["type"]
        assert f["properties"]["origin"] == "operator"
        # open ring comparison and closure
        coords = f["geometry"]["coordinates"]
        if f["geometry"]["type"] == "Polygon":
            ring = coords[0]
            assert ring[0] == ring[-1]
            open_ring = ring[:-1] if ring[0] == ring[-1] else ring
            assert open_ring == s["xy"]
        else:
            assert coords == s["xy"]

    meta2 = labels.read_site(store, site)
    assert meta2.version == 1
    assert meta2.frozen is False

    # idempotent second import
    n2 = import_draft(store, site, DRAFT_A, replace=True)
    assert n2 == 15
    assert len(labels.read_labels(store, site)["features"]) == 15


@pytest.mark.itest
@pytest.mark.skipif(not DRAFT_A.is_file(), reason="draft-A.json not available")
def test_draft_a_px_reconstruction(tmp_path):
    store = tmp_path / "store"
    site = "seaport-intersection-A"
    (store / "labels" / site).mkdir(parents=True, exist_ok=True)
    meta = {
        "id": site,
        "role": "audit",
        "polygon": {"type": "Polygon", "coordinates": [[[332380, 4690000], [332480, 4690000], [332480, 4690100], [332380, 4690100], [332380, 4690000]]]},
        "version": 1,
        "approved_by": None,
        "approved_at": None,
        "crs": "EPSG:32619",
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_area": "seaport-intersection-A",
        "frozen": False,
    }
    (store / "labels" / site / "site.json").write_text(json.dumps(meta))
    (store / "labels" / site / "labels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))

    data = json.loads(DRAFT_A.read_text())
    import_draft(store, site, DRAFT_A, replace=True)
    fc = labels.read_labels(store, site)
    by_id = {f["properties"]["id"]: f for f in fc["features"]}

    x0, y1, g = 332390.0, 4690090.0, 0.05
    for s in (data.get("surfaces") or data.get("surface_features") or []):
        f = by_id[s["id"]]
        coords = f["geometry"]["coordinates"]
        ring = coords[0] if f["geometry"]["type"] == "Polygon" else coords
        # compare pointwise; open ring for polygon
        if f["geometry"]["type"] == "Polygon" and len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        for (x, y), (pxx, pxy) in zip(ring, s["px"]):
            rx = (x - x0) / g
            ry = (y1 - y) / g
            assert abs(round(rx, 2) - pxx) <= 0.02 or abs(rx - pxx) <= 0.02
            assert abs(round(ry, 2) - pxy) <= 0.02 or abs(ry - pxy) <= 0.02
