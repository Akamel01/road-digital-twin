"""Stage 1 load: pure functions and the assembly/write path on a synthetic dataset. No devkit, no network."""

import json
import logging
import math
from types import SimpleNamespace

import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import box

from twin.facilities import MapView
from twin.stages import load
from twin.stages.load import (
    OUTPUT_FILES,
    assemble,
    boxes_per_sweep,
    dynamic_tracks,
    interpolate_box,
    name_facilities,
    run_crs,
    slerp,
    sweep_to_global,
    to_run_pose,
    write_outputs,
    yaw_of,
)

ORIGIN = load.MAP_ORIGIN_LATLON
TR = run_crs(ORIGIN)
IDENT = [1.0, 0.0, 0.0, 0.0]


def _yaw_quat(deg):
    h = math.radians(deg) / 2
    return [math.cos(h), 0.0, 0.0, math.sin(h)]


def _box(cx, cy, yaw_deg, parked=False):
    return {
        "center": [cx, cy, 0.0],
        "size": [4.0, 2.0, 1.5],
        "rotation": _yaw_quat(yaw_deg),
        "parked": parked,
    }


# ------------------------------------------------------------------ boxes


def test_box_midpoint_centre_and_yaw_slerp():
    a = _box(0.0, 0.0, 0.0)
    b = _box(10.0, 4.0, 90.0)
    got = interpolate_box(a, b, 0, 1000, 500)
    assert got["center"] == pytest.approx([5.0, 2.0, 0.0])
    assert got["size"] == pytest.approx([4.0, 2.0, 1.5])
    assert yaw_of(got["rotation"]) == pytest.approx(math.radians(45))


def test_box_endpoints_match_keyframes():
    a = _box(0.0, 0.0, 0.0)
    b = _box(10.0, 4.0, 90.0)
    assert interpolate_box(a, b, 0, 1000, 0)["center"] == pytest.approx([0, 0, 0])
    assert interpolate_box(a, b, 0, 1000, 1000)["center"] == pytest.approx([10, 4, 0])


def test_yaw_slerp_takes_short_arc():
    # 170 deg to -170 deg is 20 deg through 180, not 340 deg through 0.
    mid = slerp(_yaw_quat(170), _yaw_quat(-170), 0.5)
    assert abs(abs(yaw_of(mid)) - math.pi) < 1e-9


def test_box_not_extrapolated():
    a, b = _box(0, 0, 0), _box(1, 0, 0)
    with pytest.raises(ValueError):
        interpolate_box(a, b, 0, 1000, 1001)
    with pytest.raises(ValueError):
        interpolate_box(a, b, 0, 1000, -1)


def test_parked_from_nearest_keyframe_tie_goes_earlier():
    a = _box(0, 0, 0, parked=True)
    b = _box(1, 0, 0, parked=False)
    assert interpolate_box(a, b, 0, 1000, 400)["parked"] is True
    assert interpolate_box(a, b, 0, 1000, 600)["parked"] is False
    assert interpolate_box(a, b, 0, 1000, 500)["parked"] is True


def test_boxes_per_sweep_dynamic_agents_only_and_keyframe_end():
    kf = [
        {
            "timestamp": 0,
            "anns": [
                {"instance": "car", "category": "vehicle.car", **_box(0, 0, 0)},
                {
                    "instance": "ped",
                    "category": "human.pedestrian.adult",
                    **_box(5, 5, 0),
                },
                {"instance": "dog", "category": "animal", **_box(7, 0, 0)},
                {
                    "instance": "barrier",
                    "category": "movable_object.barrier",
                    **_box(9, 9, 0),
                },
                {
                    "instance": "sign",
                    "category": "static_object.bicycle_rack",
                    **_box(2, 2, 0),
                },
            ],
        },
        {
            "timestamp": 1000,
            "anns": [
                {"instance": "car", "category": "vehicle.car", **_box(10, 0, 0)},
                {
                    "instance": "ped",
                    "category": "human.pedestrian.adult",
                    **_box(5, 5, 0),
                },
                {"instance": "dog", "category": "animal", **_box(7, 0, 0)},
            ],
        },
    ]
    tracks = dynamic_tracks(kf)
    # Pedestrians, animals and vehicles get boxes; barriers and static objects do not.
    assert sorted(tracks) == ["car", "dog", "ped"]
    out = boxes_per_sweep(tracks, [0, 500, 1000, 1500])
    assert [len(g) for g in out] == [3, 3, 3, 0]  # 1500 is past the last keyframe
    cats = {b["token"]: b["category"] for b in out[0]}
    assert cats == {
        "car": "vehicle.car",
        "ped": "human.pedestrian.adult",
        "dog": "animal",
    }
    car = next(b for b in out[1] if b["token"] == "car")
    assert car["center"] == pytest.approx([5, 0, 0])
    car_last = next(b for b in out[2] if b["token"] == "car")
    assert car_last["center"] == pytest.approx([10, 0, 0])  # exactly on last keyframe


def test_barrier_is_not_boxed_but_pedestrian_is():
    kf = [
        {
            "timestamp": 0,
            "anns": [
                {
                    "instance": "p",
                    "category": "human.pedestrian.adult",
                    **_box(0, 0, 0),
                },
                {
                    "instance": "b",
                    "category": "movable_object.barrier",
                    **_box(1, 1, 0),
                },
            ],
        },
        {
            "timestamp": 1000,
            "anns": [
                {
                    "instance": "p",
                    "category": "human.pedestrian.adult",
                    **_box(2, 0, 0),
                },
                {
                    "instance": "b",
                    "category": "movable_object.barrier",
                    **_box(1, 1, 0),
                },
            ],
        },
    ]
    tracks = dynamic_tracks(kf)
    assert "p" in tracks
    assert "b" not in tracks
    assert [b["token"] for b in boxes_per_sweep(tracks, [500])[0]] == ["p"]


def test_name_is_facility_id_when_geometry_breaks_naming():
    fac = {
        "id": "S-1234",
        "type": "segment",
        "centreline": {"type": "Polygon"},
    }  # malformed
    assert name_facilities([fac], [("Main Street", None)]) == ["S-1234"]


def test_osm_cache_dir_defaults_to_data_osm_and_honours_env(monkeypatch):
    monkeypatch.delenv("TWIN_OSM_CACHE", raising=False)
    assert str(load.osm_cache_dir()) == "/data/osm"
    monkeypatch.setenv("TWIN_OSM_CACHE", "/tmp/elsewhere")
    assert str(load.osm_cache_dir()) == "/tmp/elsewhere"


# ------------------------------------------------------------------ georeference


def test_sweep_to_global_known_transform():
    cs = {"translation": [1.0, 2.0, 3.0], "rotation": _yaw_quat(90)}
    ego = {"translation": [10.0, 20.0, 0.0], "rotation": IDENT}
    out = sweep_to_global(np.array([[1.0, 0.0, 0.0, 0.5]]), cs, ego)
    # sensor (1,0,0) -> rotate 90 deg -> (0,1,0) -> +cs t -> (1,3,3) -> +ego t -> (11,23,3)
    assert out.shape == (1, 3)
    assert out[0] == pytest.approx([11.0, 23.0, 3.0])


def test_run_crs_maps_origin_to_expected_utm():
    lat, lon = ORIGIN
    expected = Transformer.from_crs(
        "EPSG:4326", "EPSG:32619", always_xy=True
    ).transform(lon, lat)
    got = TR.transform(0.0, 0.0)
    assert got[0] == pytest.approx(expected[0], abs=0.01)
    assert got[1] == pytest.approx(expected[1], abs=0.01)


def test_run_crs_keeps_grid_convergence():
    x0, y0 = TR.transform(0.0, 0.0)
    x1, y1 = TR.transform(0.0, 1000.0)  # 1 km north in the local tmerc
    # Convergence at Boston is about 1.3 deg, so the offset is roughly 20 m east per km.
    assert abs(x1 - x0) > 10.0
    assert (y1 - y0) != pytest.approx(1000.0, abs=1e-6)


def test_to_run_pose_turns_rotation_by_convergence():
    m = np.eye(4)
    m[0, 3], m[1, 3] = 0.0, 0.0
    run = to_run_pose(m, TR)
    theta = load.convergence(TR, 0.0, 0.0)
    # Identity local rotation: the yaw in the run CRS is the convergence angle.
    assert math.atan2(run[1, 0], run[0, 0]) == pytest.approx(theta, abs=1e-9)


# ------------------------------------------------------------------ fake dataset


class FakeSource:
    """The five methods assemble() uses, as plain dicts. Three sweeps, two keyframes."""

    def __init__(self):
        self.times = [0, 500_000, 1_000_000]
        self.egos = [0.0, 10.0, 20.0]

    def sweep_records(self, scene_token):
        return [
            {
                "token": f"sd{i}",
                "timestamp": t,
                "calibrated_sensor": {"translation": [0, 0, 1.8], "rotation": IDENT},
                "ego_pose": {"translation": [x, 0.0, 0.0], "rotation": IDENT},
            }
            for i, (t, x) in enumerate(zip(self.times, self.egos))
        ]

    def sweep_points(self, rec):
        # one ground point per sweep, 1 m ahead of the sensor, intensity 10 * sweep index
        i = int(rec["token"][2:])
        return np.array([[1.0, 0.0, -1.8, 10.0 * i], [2.0, 0.0, -1.8, 10.0 * i + 1]])

    def keyframes(self, scene_token):
        return [
            {
                "timestamp": 0,
                "anns": [
                    {
                        "instance": "car",
                        "category": "vehicle.car",
                        **_box(0, 0, 0, True),
                    },
                    {
                        "instance": "ped",
                        "category": "human.pedestrian.adult",
                        **_box(3, 3, 0),
                    },
                ],
            },
            {
                "timestamp": 1_000_000,
                "anns": [
                    {
                        "instance": "car",
                        "category": "vehicle.car",
                        **_box(10, 4, 90, False),
                    }
                ],
            },
        ]

    def cameras(self, scene_token):
        return [
            {
                "channel": f"CAM_{c}",
                "sample_token": "s0",
                "timestamp_us": 0,
                "image": f"samples/CAM_{c}/x.jpg",
                "intrinsics": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "extrinsics": {"translation": [1, 0, 1.5], "rotation_wxyz": IDENT},
            }
            for c in ("FRONT", "BACK")
        ]

    def map_view(self, patch):
        return MapView(road_segments=[], lanes=[], extent=box(*patch))

    def map_layers(self, patch):
        return [("drivable_area", "da1", box(0, -5, 30, 5))]


@pytest.fixture
def scene():
    return assemble(FakeSource(), "scene-0", TR)


def test_assemble_shapes_and_frames(scene):
    assert len(scene.sweeps) == 3
    assert len(scene.x) == 6  # 2 points per sweep
    assert set(scene.sweep.tolist()) == {0, 1, 2}
    # sweep 0, first point: sensor (1,0,-1.8); sensor sits 1.8 m up, so map (1, 0, 0)
    ux, uy = TR.transform(1.0, 0.0)
    assert scene.x[0] == pytest.approx(ux, abs=1e-6)
    assert scene.y[0] == pytest.approx(uy, abs=1e-6)
    assert scene.z[0] == pytest.approx(0.0, abs=1e-9)
    assert scene.sweeps[0]["matrix"][0][3] == pytest.approx(TR.transform(0.0, 0.0)[0])


def test_boxes_are_in_run_crs(scene):
    # sweep 1 is halfway: map centre (5, 2) -> run CRS
    (box1,) = scene.boxes[1]
    assert box1["token"] == "car"
    assert box1["parked"] is True
    ux, uy = TR.transform(5.0, 2.0)
    assert box1["center"][0] == pytest.approx(ux, abs=1e-6)
    assert box1["center"][1] == pytest.approx(uy, abs=1e-6)


def test_write_outputs_matches_contract(scene, tmp_path):
    names = name_facilities(scene.facilities, None)
    write_outputs(tmp_path, scene, names)
    assert all((tmp_path / f).is_file() for f in OUTPUT_FILES)

    with np.load(tmp_path / "points.npz") as f:
        assert f["x"].dtype == np.float64
        assert (
            f["x"].shape
            == f["y"].shape
            == f["z"].shape
            == f["intensity"].shape
            == f["sweep"].shape
            == (6,)
        )

    poses = json.loads((tmp_path / "poses.json").read_text())
    assert poses["crs"] == "EPSG:32619"
    assert len(poses["poses"]) == 3
    assert np.array(poses["poses"][0]["matrix"]).shape == (4, 4)

    boxes = json.loads((tmp_path / "boxes.json").read_text())
    assert [s["sweep"] for s in boxes["sweeps"]] == [0, 1, 2]
    assert boxes["sweeps"][1]["boxes"][0]["parked"] is True

    ref = json.loads((tmp_path / "reference.geojson").read_text())
    assert ref["features"][0]["properties"] == {
        "layer": "drivable_area",
        "token": "da1",
    }
    assert ref["crs"]["properties"]["name"] == "EPSG:32619"

    cams = json.loads((tmp_path / "cameras.json").read_text())
    assert len(cams["cameras"]) == 2
    assert cams["cameras"][0]["extrinsics"]["translation"] == [1, 0, 1.5]

    facs = json.loads((tmp_path / "facilities.geojson").read_text())
    assert facs["features"] == []


# ------------------------------------------------------------------ naming and the stage


def test_names_fall_back_to_ids_without_streets():
    fac = {
        "id": "I-abcd",
        "type": "intersection",
        "core": box(0, 0, 1, 1).__geo_interface__,
    }
    assert name_facilities([fac], None) == ["I-abcd"]
    assert name_facilities([fac], []) == ["I-abcd"]


def test_run_writes_outputs_and_falls_back_when_network_fails(tmp_path, monkeypatch):
    scene = assemble(FakeSource(), "scene-0", TR)
    monkeypatch.setattr(load, "load_scene", lambda root, token, params=None: scene)

    def offline(bbox, cache_dir):
        raise OSError("no network")

    monkeypatch.setattr(load, "fetch_streets", offline)
    ctx = SimpleNamespace(
        stage_dir=lambda name: tmp_path / "1_load",
        scene_token="scene-0",
        log=logging.getLogger("test"),
    )
    (tmp_path / "1_load").mkdir()
    result = load.run(ctx, None)

    assert result.status == "ok"
    assert result.metrics["n_sweeps"] == 3
    assert result.metrics["n_points"] == 6
    assert result.metrics["osm_names"] is None
    assert all((tmp_path / "1_load" / f).is_file() for f in OUTPUT_FILES)


class SegSource(FakeSource):
    """Lidarseg labels on sweep 0 only (a keyframe); the other sweeps have none."""

    def sweep_labels(self, rec):
        return np.array([24, 17], np.uint8) if rec["token"] == "sd0" else None

    def driveable_index(self):
        return 24


def test_lidarseg_label_on_keyframes_and_sentinel_elsewhere(tmp_path):
    sc = assemble(SegSource(), "scene-0", TR)
    assert sc.lidarseg.tolist() == [24, 17, 255, 255, 255, 255]
    write_outputs(tmp_path, sc, [])
    with np.load(tmp_path / "points.npz") as f:
        assert f["lidarseg"].dtype == np.uint8
    meta = json.loads((tmp_path / "lidarseg.json").read_text())
    assert meta == {"driveable_index": 24, "sentinel": 255, "n_labelled": 2}


def test_no_lidarseg_source_gives_all_sentinel(scene):
    assert (scene.lidarseg == 255).all() and scene.driveable_index is None
