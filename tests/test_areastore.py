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
