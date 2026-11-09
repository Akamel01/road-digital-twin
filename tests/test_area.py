import json

import pytest
import shapely

from twin.area import make_area, resolve_tokens

A, B = "a" * 32, "b" * 32


def write_tables(root, poses):
    """poses: {scene name: [(x, y)]}, one ego pose each (sweep poses count the same as keyframes)."""
    v = root / "v1.0-test"
    v.mkdir(parents=True)
    scenes, samples, sds, egos = [], [], [], []
    for i, (name, pts) in enumerate(poses.items()):
        desc = "Rain, night" if name == "scene-2" else "sunny"
        scenes.append(
            {"token": f"sc{i}", "name": name, "log_token": "log", "description": desc}
        )
        samples.append({"token": f"smp{i}", "scene_token": f"sc{i}"})
        for j, (x, y) in enumerate(pts):
            egos.append({"token": f"e{i}{j}", "translation": [x, y, 0]})
            sds.append({"sample_token": f"smp{i}", "ego_pose_token": f"e{i}{j}"})
    scenes.append(
        {"token": "so", "name": "scene-9", "log_token": "log2", "description": "x"}
    )
    samples.append({"token": "smpo", "scene_token": "so"})
    egos.append({"token": "eo", "translation": [5, 5, 0]})
    sds.append({"sample_token": "smpo", "ego_pose_token": "eo"})
    logs = [
        {"token": "log", "location": "boston-seaport", "date_captured": "2018-09-18"},
        {
            "token": "log2",
            "location": "singapore-onenorth",
            "date_captured": "2018-09-18",
        },
    ]
    tables = [
        ("scene", scenes),
        ("sample", samples),
        ("sample_data", sds),
        ("ego_pose", egos),
        ("log", logs),
    ]
    for n, t in tables:
        (v / f"{n}.json").write_text(json.dumps(t))


def test_area_drives_rain_and_held_out(tmp_path):
    write_tables(
        tmp_path,
        {
            "scene-1": [(100, 100), (5, 5)],  # one pose inside the buffer only
            "scene-2": [(0, 5)],  # inside, rain
            "scene-3": [(100, 100)],  # never near
        },
    )
    polys = {A: shapely.box(-10, -10, 0, 0), B: shapely.box(500, 500, 510, 510)}
    area = make_area("t", polys, [A[:8]], 10.0, tmp_path, "v1.0-test", "boston-seaport")
    got = {d["scene"]: d for d in area["drives"]}
    assert sorted(got) == ["scene-1", "scene-2"]  # scene-9 is on another map
    assert got["scene-2"]["rain"] and not got["scene-2"]["build_input"]
    assert not got["scene-1"]["rain"] and got["scene-1"]["build_input"]
    assert got["scene-1"]["date"] == "2018-09-18"
    assert area["epsg"] == 32619 and area["polygon"]["type"] == "Polygon"
    again = make_area(
        "t",
        polys,
        [A[:8]],
        10.0,
        tmp_path,
        "v1.0-test",
        "boston-seaport",
        include_rain=True,
    )
    assert all(d["build_input"] for d in again["drives"])


def test_prefix_must_be_unique_and_long_enough():
    known = {A: 0, "aaaaaaaabbbb": 0}
    for bad in ("aaaaaaaa", "aaaa", "zzzzzzzz"):
        with pytest.raises(ValueError):
            resolve_tokens([bad], known)
    assert resolve_tokens(["aaaaaaaabb"], known) == ["aaaaaaaabbbb"]
