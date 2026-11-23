import json

import numpy as np
import pytest

from twin.areastore import open_area

POLY = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
DRIVES = [
    {"scene": "s2", "correction": {"yaw_deg": 90.0, "dx_m": 1.0, "dy_m": 2.0, "dz_m": 3.0}},
    {"scene": "s1"},
    {"scene": "s9"},
]


def _mk(tmp_path, *, twin_features=True):
    root = tmp_path / "store" / "areas"
    (root / "a1-merged").mkdir(parents=True)
    (root / "a1-merged" / "merged.npz").write_bytes(b"")
    (root / "a1-merged" / "drives.json").write_text(json.dumps(DRIVES))
    (root / "a1-twin").mkdir()
    if twin_features:
        (root / "a1-twin" / "markings.geojson").write_text("{}")
    (root / "a1.json").write_text(
        json.dumps({"polygon": POLY, "drives": [{"scene": "s1", "scene_token": "t1"}, {"scene": "s2", "scene_token": "t2"}]})
    )
    return tmp_path / "store", root


def test_open_by_every_ref_form(tmp_path):
    store, root = _mk(tmp_path)
    for ref in ("a1", root / "a1-twin", root / "a1-merged", root / "a1.json"):
        a = open_area(store, ref)
        assert (a.name, a.root, a.twin_dir, a.merged_dir) == ("a1", root, root / "a1-twin", root / "a1-merged")
        assert "polygon" in a.definition()


def test_areas_root_outside_store(tmp_path):
    _, root = _mk(tmp_path)
    assert open_area(tmp_path / "elsewhere", "a1", areas_root=root).root == root


def test_build_dir_prefers_twin_with_features(tmp_path):
    store, root = _mk(tmp_path)
    assert open_area(store, "a1").build_dir() == root / "a1-twin"


def test_build_dir_falls_back_to_merged(tmp_path):
    store, root = _mk(tmp_path, twin_features=False)
    assert open_area(store, "a1").build_dir() == root / "a1-merged"


def test_build_dir_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_area(tmp_path, "nope").build_dir()


def test_drives_order_tokens_and_missing_drive(tmp_path):
    store, root = _mk(tmp_path)
    ds = open_area(store, "a1").drives()
    assert [d.scene for d in ds] == ["s2", "s1", "s9"]
    assert [d.token for d in ds] == ["t2", "t1", None]  # s9 is not in the definition
    assert ds[0].dir == root / "a1-merged" / "drives" / "s2"
    assert open_area(store, "a1").drive_tokens() == ["t2", "t1"]
    assert np.allclose(ds[1].transform(), np.eye(4))
    assert np.allclose(ds[0].transform()[:3, 3], [1, 2, 3])


def test_drives_use_twin_copy_when_no_merged_file(tmp_path):
    store, root = _mk(tmp_path)
    (root / "a1-merged" / "drives.json").unlink()
    (root / "a1-twin" / "drives.json").write_text(json.dumps([{"scene": "s1"}]))
    assert open_area(store, "a1").drive_tokens() == ["t1"]


def test_missing_definition_raises(tmp_path):
    store, root = _mk(tmp_path)
    (root / "a1.json").unlink()
    a = open_area(store, "a1")
    with pytest.raises(FileNotFoundError):
        a.definition()
    assert a.drive_tokens() == []


def test_lone_polygon_json_is_the_fallback_and_two_are_ambiguous(tmp_path):
    store, root = _mk(tmp_path)
    (root / "a1.json").rename(root / "other.json")
    assert "polygon" in open_area(store, "a1").definition()
    (root / "third.json").write_text(json.dumps({"polygon": POLY}))
    with pytest.raises(ValueError):
        open_area(store, "a1").definition()


def test_drives_read_from_the_build_the_ref_named(tmp_path):
    root = tmp_path / "areas"
    (root / "a2-merged").mkdir(parents=True)
    (root / "a2.json").write_text(json.dumps({"polygon": {}, "drives": [{"scene": "s1", "scene_token": "t1"}]}))
    (root / "a2-merged" / "drives.json").write_text(json.dumps([{"scene": "s1"}]))
    (root / "a2-twin").mkdir()  # twin folder exists but has no drives.json yet (before the first area twin build)
    assert open_area(tmp_path, root / "a2-twin").drive_tokens() == []
    assert open_area(tmp_path, root / "a2-merged").drive_tokens() == ["t1"]
    assert open_area(tmp_path, "a2").drive_tokens() == ["t1"]


def test_a_named_build_that_is_not_built_yet_has_no_drives(tmp_path):
    root = tmp_path / "areas"
    (root / "a3-merged").mkdir(parents=True)
    (root / "a3.json").write_text(json.dumps({"polygon": {}, "drives": [{"scene": "s1", "scene_token": "t1"}]}))
    (root / "a3-merged" / "drives.json").write_text(json.dumps([{"scene": "s1"}]))
    a = open_area(tmp_path, root / "a3-twin")  # autopilot asks before the first area twin build
    assert (a.name, a.root) == ("a3", root)
    assert a.drive_tokens() == []
    assert open_area(tmp_path, "a3-twin").drive_tokens() == []
    assert open_area(tmp_path, "a3-merged").drive_tokens() == ["t1"]


def _area_outside(tmp_path):
    root = tmp_path / "areas"
    build = root / "demo-twin"
    build.mkdir(parents=True)
    (build / "markings.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (root / "demo.json").write_text(json.dumps({"polygon": POLY}))
    return root, build


def test_open_area_inside_store(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    build = store / "demo-twin"
    build.mkdir()
    (build / "markings.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (store / "areas").mkdir(exist_ok=True)
    (store / "areas" / "demo.json").write_text(json.dumps({"polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}))
    a = open_area(store, "demo")
    bd, ad = a.build_dir(), a.definition()
    assert bd == build
    assert "polygon" in ad


def test_open_area_outside_store(tmp_path):
    root, build = _area_outside(tmp_path)
    store = tmp_path / "store"
    a = open_area(store, "demo", areas_root=root)
    bd, ad = a.build_dir(), a.definition()
    assert bd == build
    assert "polygon" in ad


def test_open_area_accepts_build_path(tmp_path):
    _root, build = _area_outside(tmp_path)
    store = tmp_path / "store"
    a = open_area(store, str(build))
    bd, ad = a.build_dir(), a.definition()
    assert bd == build
    assert "polygon" in ad


def test_open_area_accepts_area_json(tmp_path):
    root, build = _area_outside(tmp_path)
    store = tmp_path / "store"
    json_path = root / "demo.json"
    a = open_area(store, str(json_path), areas_root=root)
    bd, _ad = a.build_dir(), a.definition()
    # sibling build found
    assert bd == build


def test_build_dir_preserves_store_name_candidate(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    build = store / "demo"
    build.mkdir()
    (build / "markings.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    bd = open_area(store, "demo").build_dir()
    assert bd == build


def test_build_dir_areas_root_candidates_first(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    # both store/demo and areas_root/demo-twin exist with equal features
    b1 = store / "demo"
    b1.mkdir()
    (b1 / "markings.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    root = tmp_path / "areas"
    root.mkdir()
    b2 = root / "demo-twin"
    b2.mkdir()
    (b2 / "markings.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    bd = open_area(store, "demo", areas_root=root).build_dir()
    assert bd == b2


def test_definition_prefers_exact_sibling_over_wildcard(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    build = store / "demo-twin"
    build.mkdir()
    # two jsons in parent
    (store / "demo.json").write_text(json.dumps({"polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}))
    (store / "other.json").write_text(json.dumps({"polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}))
    ad = open_area(store, build).definition()
    # exact sibling demo.json wins -> name demo; just ensure returns dict with polygon
    assert "polygon" in ad


def test_definition_rejects_ambiguous_polygon_json(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    build = store / "demo-twin"
    build.mkdir()
    (store / "a.json").write_text(json.dumps({"polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}))
    (store / "b.json").write_text(json.dumps({"polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}))
    import pytest
    with pytest.raises((FileNotFoundError, ValueError)):
        open_area(store, build).definition()


def test_cloud_dir_only_for_the_named_build_holding_merged_npz(tmp_path):
    store, root = _mk(tmp_path)
    assert open_area(store, "a1-merged").cloud_dir() == root / "a1-merged"
    assert open_area(store, "a1-twin").cloud_dir() is None
    assert open_area(store, "areas/a1-merged").cloud_dir() == root / "a1-merged"  # relative to the store
    assert open_area(store, "20261123-run").cloud_dir() is None


def test_drive_records_are_the_named_builds_entries(tmp_path):
    store, _root = _mk(tmp_path)
    assert [r["scene"] for r in open_area(store, "a1-merged").drive_records()] == ["s2", "s1", "s9"]
    assert open_area(store, "a1-twin").drive_records() == []
