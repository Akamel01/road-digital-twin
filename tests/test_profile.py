"""Stage 7 profile: synthetic ground surface and facilities, no devkit, no data."""

import json
import logging

import numpy as np
from shapely.geometry import Point, shape

from twin import registry
from twin.contracts import ProfileParams
from twin.runner import StageContext

SLOPE = 0.02
CELL = 0.5
ORIGIN = (-50.0, -50.0)
N_CELLS = 200  # 100 m square around the origin


def _surface():
    """Grid of 0.5 m cells, every cell observed, z = SLOPE * x at the cell centre."""
    xs = ORIGIN[0] + (np.arange(N_CELLS) + 0.5) * CELL
    z = np.tile(SLOPE * xs, (N_CELLS, 1))
    return {
        "z": z,
        "count": np.full((N_CELLS, N_CELLS), 5, dtype=np.int64),
        "origin": np.array(ORIGIN, dtype=float),
        "cell_m": np.float64(CELL),
    }


def _ls(coords):
    return {"type": "LineString", "coordinates": coords}


def _square(half):
    ring = [[-half, -half], [half, -half], [half, half], [-half, half], [-half, -half]]
    return {"type": "Polygon", "coordinates": [ring]}


def _intersection(fid, legs, half=10.0):
    """legs: {name: far end point}. Each leg starts on the core edge, in the direction of its far end."""
    leg_recs = []
    for name, (x, y) in legs.items():
        k = half / max(abs(x), abs(y))  # axis-aligned legs only: start on the core edge
        leg_recs.append({"approach": name, "geometry": _ls([[x * k, y * k], [x, y]])})
    return {
        "type": "Feature",
        "geometry": _square(half),
        "properties": {
            "id": fid,
            "type": "intersection",
            "name": fid,
            "legs": leg_recs,
        },
    }


CROSS = {"N": (0.0, 40.0), "S": (0.0, -40.0), "E": (40.0, 0.0), "W": (-40.0, 0.0)}
T_JUNCTION = {"N": (0.0, 40.0), "S": (0.0, -40.0), "W": (-40.0, 0.0)}


def _write_run(tmp_path, features, observed, height_valid=True):
    run = tmp_path / "run"
    (run / "1_load").mkdir(parents=True)
    (run / "1_load" / "facilities.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features})
    )
    (run / "4_ground").mkdir()
    np.savez_compressed(run / "4_ground" / "surface.npz", **_surface())
    qa = {"height_valid": height_valid, "observed_core": observed}
    (run / "4_ground" / "qa.json").write_text(json.dumps(qa))
    ctx = StageContext(
        run_dir=run,
        scene_token="s",
        seed=0,
        log=logging.getLogger("test"),
        min_observed=0.5,
    )
    return ctx, run / "7_profile"


def _rows(out):
    lines = (out / "profile.csv").read_text().strip().split("\n")
    assert lines[0] == "facility,line,s_m,z_m,n"
    return [line.split(",") for line in lines[1:]]


def _run(ctx):
    return registry.lookup("profile", "centreline")(ctx, ProfileParams())


def _geo(out):
    return {
        f["properties"]["line"]: shape(f["geometry"])
        for f in json.loads((out / "centrelines.geojson").read_text())["features"]
    }


def test_cross_gives_two_through_lines(tmp_path):
    ctx, out = _write_run(
        tmp_path, [_intersection("I-cross", CROSS)], observed={"I-cross": 1.0}
    )
    result = _run(ctx)
    assert result.status == "ok"
    geo = _geo(out)
    assert set(geo) == {"I-cross/N-S", "I-cross/E-W"}
    for line in geo.values():
        assert line.distance(Point(0, 0)) < 1e-9  # continues across the centre


def test_cross_through_line_recovers_slope(tmp_path):
    ctx, out = _write_run(
        tmp_path, [_intersection("I-cross", CROSS)], observed={"I-cross": 1.0}
    )
    _run(ctx)
    rows = [r for r in _rows(out) if r[1] == "I-cross/E-W"]
    s = np.array([float(r[2]) for r in rows])
    z = np.array([float(r[3]) for r in rows])
    assert s[0] == 0.0 and abs(s[-1] - 80.0) < 1e-6  # full through length, end included
    slope, _ = np.polyfit(s, z, 1)
    # the E-W line runs from E to W (label order), so z falls along it
    assert abs(slope + SLOPE) < 1e-3


def test_t_gives_through_line_and_stem(tmp_path):
    ctx, out = _write_run(
        tmp_path, [_intersection("I-t", T_JUNCTION)], observed={"I-t": 1.0}
    )
    _run(ctx)
    geo = _geo(out)
    assert set(geo) == {"I-t/N-S", "I-t/W"}
    assert geo["I-t/N-S"].distance(Point(0, 0)) < 1e-9
    assert geo["I-t/W"].distance(Point(0, 0)) < 1e-9  # stem starts at the centre


def test_segment_uses_stored_centreline(tmp_path):
    seg = {
        "type": "Feature",
        "geometry": _square(3.0),
        "properties": {
            "id": "S-1",
            "type": "segment",
            "name": "S-1",
            "centreline": _ls([[-20.0, 0.0], [20.0, 0.0]]),
        },
    }
    ctx, out = _write_run(tmp_path, [seg], observed={"S-1": 1.0})
    _run(ctx)
    assert set(_geo(out)) == {"S-1/main"}


def test_facility_below_min_observed_skipped(tmp_path):
    seg = {
        "type": "Feature",
        "geometry": _square(3.0),
        "properties": {
            "id": "S-low",
            "type": "segment",
            "name": "S-low",
            "centreline": _ls([[-20.0, 0.0], [20.0, 0.0]]),
        },
    }
    ctx, out = _write_run(
        tmp_path,
        [seg, _intersection("I-empty", CROSS)],
        observed={"S-low": 0.9, "I-empty": 0.1},
    )
    result = _run(ctx)
    assert result.metrics["not_scanned_enough"] == ["I-empty"]
    assert {r[0] for r in _rows(out)} == {"S-low"}
    assert set(_geo(out)) == {"S-low/main"}


def test_height_invalid_still_writes_heights(tmp_path):
    ctx, out = _write_run(
        tmp_path,
        [_intersection("I-cross", CROSS)],
        observed={"I-cross": 1.0},
        height_valid=False,
    )
    result = _run(ctx)
    assert result.metrics["height_valid"] is False
    assert len(_rows(out)) > 0
    assert set(_geo(out)) == {"I-cross/N-S", "I-cross/E-W"}
