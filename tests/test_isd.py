"""Stage 8 isd: synthetic flat road, one intersection leg due east. No data, no devkit."""

import json
import logging

import numpy as np

from twin import registry
from twin.contracts import IsdParams
from twin.runner import StageContext
from twin.sightline import INDETERMINATE
from twin.stages.ground import _write_laz

CELL = 0.5
ORIGIN = (-10.0, -10.0)
N = 260  # 130 m square: x and y from -10 to 120
REQUIRED = 0.278 * 50.0 * 7.5  # 104.25 m, default params
LEG_END = (110.0, 0.0)


def _surface(count=50):
    return {
        "z": np.zeros((N, N)),
        "count": np.full((N, N), count, dtype=np.int64),
        "origin": np.array(ORIGIN, dtype=float),
        "cell_m": np.float64(CELL),
    }


def _points(xs, ys, zs):
    xyz = np.column_stack(
        [np.asarray(xs, float), np.asarray(ys, float), np.asarray(zs, float)]
    )
    return xyz.reshape(-1, 3)


def _fields(xyz):
    n = len(xyz)
    return {
        "x": xyz[:, 0],
        "y": xyz[:, 1],
        "z": xyz[:, 2],
        "intensity": np.full(n, 10, np.uint16),
        "sweep": np.zeros(n, np.int32),
    }


def _write_run(tmp_path, nonground=None, parked=None, height_valid=True, observed=1.0):
    run = tmp_path / "run"
    load = run / "1_load"
    load.mkdir(parents=True)
    ident = {"matrix": np.eye(4).tolist()}
    (load / "poses.json").write_text(json.dumps({"poses": [ident]}))
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-5, -5], [5, -5], [5, 5], [-5, 5], [-5, -5]]],
        },
        "properties": {
            "id": "I-test",
            "type": "intersection",
            "legs": [
                {
                    "approach": "E",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0], list(LEG_END)],
                    },
                }
            ],
            "eye_points": [
                {
                    "approach": "E",
                    "source": "setback",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                }
            ],
        },
    }
    (load / "facilities.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]})
    )
    align = run / "3_align"
    align.mkdir()
    (align / "poses.json").write_text(json.dumps({"poses": [ident]}))
    mask = run / "2_mask"
    mask.mkdir()
    parked_xyz = np.empty((0, 3)) if parked is None else parked
    np.savez_compressed(mask / "parked.npz", **_fields(parked_xyz))
    ground = run / "4_ground"
    ground.mkdir()
    np.savez_compressed(ground / "surface.npz", **_surface())
    ng = np.empty((0, 3)) if nonground is None else nonground
    _write_laz(ground / "nonground.laz", ng, np.zeros(len(ng)), 1)
    qa = {"height_valid": height_valid, "observed_core": {"I-test": observed}}
    (ground / "qa.json").write_text(json.dumps(qa))
    ctx = StageContext(
        run_dir=run,
        scene_token="s",
        seed=0,
        log=logging.getLogger("test"),
        min_observed=0.5,
    )
    return ctx, run / "8_isd"


def _run(ctx):
    return registry.lookup("isd", "aashto-b")(ctx, IsdParams())


def _leg(out):
    doc = json.loads((out / "isd.json").read_text())
    return doc["facilities"][0]["legs"][0]


def test_open_road_meets_required(tmp_path):
    ctx, out = _write_run(tmp_path)
    assert _run(ctx).status == "ok"
    leg = _leg(out)
    assert leg["required_m"] == round(REQUIRED, 2)
    assert leg["status"] == "ok"
    assert leg["available_m"] == round(REQUIRED, 2)
    assert leg["available_with_parked_m"] == round(REQUIRED, 2)


def test_wall_at_40_m_limits_available(tmp_path):
    ys = np.linspace(-5, 5, 41)
    zs = np.linspace(0.2, 3.0, 15)
    yy, zz = np.meshgrid(ys, zs)
    wall = _points(np.full(yy.size, 40.0), yy.ravel(), zz.ravel())
    ctx, out = _write_run(tmp_path, nonground=wall)
    _run(ctx)
    leg = _leg(out)
    assert leg["status"] == "short"
    assert abs(leg["available_m"] - 40.0) <= 0.5
    assert leg["available_with_parked_m"] <= leg["available_m"]


def test_parked_box_blocks_only_with_parked(tmp_path):
    ys = np.linspace(-1, 1, 20)
    zs = np.linspace(0.5, 1.5, 10)
    yy, zz = np.meshgrid(ys, zs)
    box = _points(np.full(yy.size, 60.0), yy.ravel(), zz.ravel())
    ctx, out = _write_run(tmp_path, parked=box)
    _run(ctx)
    leg = _leg(out)
    assert leg["available_m"] == round(REQUIRED, 2)
    assert leg["available_with_parked_m"] < leg["available_m"]
    assert abs(leg["available_with_parked_m"] - 60.0) <= 0.5


def test_height_invalid_is_indeterminate(tmp_path):
    ctx, out = _write_run(tmp_path, height_valid=False)
    _run(ctx)
    leg = _leg(out)
    assert leg["status"] == INDETERMINATE
    assert leg["available_m"] is None


def test_not_scanned_facility_is_skipped(tmp_path):
    ctx, out = _write_run(tmp_path, observed=0.2)
    result = _run(ctx)
    doc = json.loads((out / "isd.json").read_text())
    assert doc["facilities"] == []
    assert doc["not_scanned_enough"] == ["I-test"]
    assert result.metrics["not_scanned_enough"] == ["I-test"]
