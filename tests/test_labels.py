import json

import pytest

from twin.contracts import LabelFeature, SiteMeta
from twin.labels import (
    FrozenSiteError,
    approve,
    draft,
    new_version,
    read_labels,
    read_site,
    set_meta,
    valid_site,
    write_labels,
)


def _write_fc(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2) + "\n")


def _make_area(tmp_path):
    build = tmp_path / "test-twin"
    build.mkdir()
    _write_fc(
        build / "markings.geojson",
        [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "properties": {"id": "m1", "marking_type": "solid"},
            }
        ],
    )
    _write_fc(
        build / "crosswalks.geojson",
        [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"id": "cw1"},
            }
        ],
    )
    _write_fc(
        build / "curbs.geojson",
        [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[2, 0], [2, 1]]},
                "properties": {"id": "c1", "height_m": 0.15},
            }
        ],
    )
    _write_fc(
        build / "ramps.geojson",
        [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[3, 0], [4, 0], [4, 1], [3, 0]]]},
                "properties": {
                    "id": "r1",
                    "kind": "corner",
                    "width_m": 1.2,
                    "run_length_m": 1.5,
                    "running_slope_pct": 8.0,
                    "cross_slope_pct": 2.0,
                    "status": "ok",
                    "n_points": 10,
                },
            }
        ],
    )
    # area definition with polygon next to/for the build
    area_def = {
        "name": "test",
        "polygon": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
    }
    (tmp_path / "test-twin.json").write_text(json.dumps(area_def, indent=2) + "\n")
    return build


def test_schema_round_trip(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")

    meta = read_site(store, "s1")
    assert isinstance(meta, SiteMeta)
    assert meta.crs == "EPSG:32619"
    assert meta.frozen is False
    assert meta.version == 1
    # re-dump site structurally equal
    meta2 = SiteMeta.model_validate_json((store / "labels" / "s1" / "site.json").read_text())
    assert meta2.model_dump(mode="json") == meta.model_dump(mode="json")

    labels = read_labels(store, "s1")
    assert labels["type"] == "FeatureCollection"
    assert len(labels["features"]) == 4
    elems = {f["properties"]["element"] for f in labels["features"]}
    types = {f["properties"]["type"] for f in labels["features"]}
    assert elems == {"marking", "crosswalk", "curb", "curb_ramp"}
    assert types == {"solid_line", "zebra", "curb", "curb_ramp"}
    # validate each feature with contracts and check structural round-trip
    for feat in labels["features"]:
        lf = LabelFeature.model_validate(feat["properties"])
        dumped = lf.model_dump(mode="json")
        # enums preserved
        assert dumped["element"] in {"marking", "crosswalk", "curb", "curb_ramp"}
        assert dumped["type"] in {
            "solid_line",
            "dashed_line",
            "edge_line",
            "stop_line",
            "arrow",
            "text",
            "zebra",
            "parallel",
            "curb",
            "curb_ramp",
        }
        # properties round-trip through model
        assert LabelFeature.model_validate(dumped).model_dump(mode="json") == dumped

    labels2 = read_labels(store, "s1")
    assert labels2 == labels


def test_approval_freezes_and_blocks_write(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")

    meta = approve(store, "s1", "alice", approved_at="2026-01-02T00:00:00+00:00")
    assert meta.frozen is True
    assert meta.approved_by == "alice"
    assert meta.approved_at == "2026-01-02T00:00:00+00:00"
    assert meta.version == 2
    assert (store / "labels" / "s1" / "labels.v1.geojson").is_file()
    assert read_site(store, "s1").crs == "EPSG:32619"

    with pytest.raises(FrozenSiteError):
        write_labels(store, "s1", read_labels(store, "s1"))


def test_new_version_creates_snapshot_and_unfreezes(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    approve(store, "s1", "alice", approved_at="2026-01-02T00:00:00+00:00")
    assert read_site(store, "s1").version == 2
    assert read_site(store, "s1").frozen is True

    meta = new_version(store, "s1")
    assert meta.version == 3
    assert meta.frozen is False
    assert meta.approved_by is None
    assert meta.approved_at is None
    assert (store / "labels" / "s1" / "labels.v2.geojson").is_file()

    # writable again
    labels = read_labels(store, "s1")
    write_labels(store, "s1", labels)
    assert read_site(store, "s1").crs == "EPSG:32619"


def test_stale_version_raises(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    labels = read_labels(store, "s1")
    with pytest.raises(ValueError, match="stale version"):
        write_labels(store, "s1", labels, expected_version=99)
    with pytest.raises(ValueError, match="stale version"):
        write_labels(store, "s1", labels, version=0)


def _make_twin_layout(tmp_path):
    build = tmp_path / "test-twin"
    feats = build / "5_features"
    feats.mkdir(parents=True)
    _write_fc(
        feats / "markings.geojson",
        [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [100, 100]]},
                "properties": {"id": "m1", "marking_type": "solid"},
            }
        ],
    )
    _write_fc(feats / "crosswalks.geojson", [])
    _write_fc(feats / "curbs.geojson", [])
    _write_fc(feats / "ramps.geojson", [])
    area_def = {
        "name": "test",
        "polygon": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
    }
    (tmp_path / "test-twin.json").write_text(json.dumps(area_def, indent=2) + "\n")
    return build


def test_draft_reads_twin_features_and_clips(tmp_path):
    store = tmp_path / "store"
    build = _make_twin_layout(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    labels = read_labels(store, "s1")
    assert len(labels["features"]) == 1
    geom = labels["features"][0]["geometry"]
    # clipped to polygon: endpoint beyond 10 should be trimmed
    coords = geom["coordinates"]
    assert all(0 <= x <= 10 and 0 <= y <= 10 for x, y in coords)
    assert coords != [[0, 0], [100, 100]]


def test_draft_empty_creates_no_features(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    meta = draft(store, "s1", str(build), empty=True, created_at="2026-01-01T00:00:00+00:00")
    assert meta.version == 1
    assert meta.role == "dev"
    labels = read_labels(store, "s1")
    assert labels["features"] == []
    assert meta.source_area is not None


def test_draft_default_still_copies_features(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    labels = read_labels(store, "s1")
    assert len(labels["features"]) == 4



def test_set_meta_updates_control_and_notes(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    meta = set_meta(store, "s1", control="signalised", notes="hello")
    assert meta.control == "signalised"
    assert meta.notes == "hello"
    assert meta.version == 1
    meta2 = read_site(store, "s1")
    assert meta2.control == "signalised"
    assert meta2.notes == "hello"


def test_set_meta_rejects_unknown_control(tmp_path):
    from pydantic import ValidationError
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    with pytest.raises(ValidationError):
        set_meta(store, "s1", control="bogus", notes=None)


def test_set_meta_allowed_on_frozen_site(tmp_path):
    store = tmp_path / "store"
    build = _make_area(tmp_path)
    draft(store, "s1", str(build), created_at="2026-01-01T00:00:00+00:00")
    approve(store, "s1", "alice", approved_at="2026-01-02T00:00:00+00:00")
    meta = set_meta(store, "s1", control="stop_controlled", notes="frozen ok")
    assert meta.control == "stop_controlled"
    assert meta.frozen is True


def test_valid_site_rejects_traversal():
    assert valid_site("../x") is False
    assert valid_site("a\\b") is False
    assert valid_site("") is False
    assert valid_site(".hidden") is False
    assert valid_site("ok.site-1") is True
