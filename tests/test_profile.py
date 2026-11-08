"""Stage 7 profile: synthetic ground surface and facilities, no devkit, no data."""

import json
import logging

import numpy as np

from twin import registry
from twin.contracts import ProfileParams
from twin.runner import StageContext

SLOPE = 0.02
CELL = 0.5


def _surface(origin=(0.0, -1.0), nx=100, ny=40):
    """Grid of 0.5 m cells, every cell observed, z = SLOPE * x at the cell centre."""
    xs = origin[0] + (np.arange(nx) + 0.5) * CELL
    z = np.tile(SLOPE * xs, (ny, 1))
    return {
        "z": z,
        "count": np.full((ny, nx), 5, dtype=np.int64),
        "origin": np.array(origin, dtype=float),
        "cell_m": np.float64(CELL),
    }


def _feature(fid, coords, observed_ok=True, centreline=True, kind="segment"):
    line = {"type": "LineString", "coordinates": coords}
    props = {"id": fid, "type": kind, "name": fid}
    if centreline:
        props["centreline"] = line
    x0, x1 = coords[0][0], coords[-1][0]
    ring = [[x0, 8], [x1, 8], [x1, 12], [x0, 12], [x0, 8]]
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": props,
    }


def _write_run(tmp_path, features, observed, height_valid=True):
    run = tmp_path / "run"
    (run / "1_load").mkdir(parents=True)
    (run / "1_load" / "facilities.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features})
    )
    (run / "4_ground").mkdir()
    surf = _surface()
    np.savez_compressed(run / "4_ground" / "surface.npz", **surf)
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
    assert lines[0] == "facility,s_m,z_m,n"
    return [line.split(",") for line in lines[1:]]


def test_profile_recovers_synthetic_slope(tmp_path):
    line = [[2.0, 10.0], [40.0, 10.0]]
    ctx, out = _write_run(tmp_path, [_feature("S-1", line)], observed={"S-1": 1.0})
    result = registry.lookup("profile", "centreline")(ctx, ProfileParams())
    assert result.status == "ok"
    rows = [r for r in _rows(out) if r[0] == "S-1"]
    s = np.array([float(r[1]) for r in rows])
    z = np.array([float(r[2]) for r in rows])
    slope, _ = np.polyfit(s, z, 1)
    assert abs(slope - SLOPE) < 1e-3
    assert len(rows) == 39  # one sample per metre from 0 to 38 m, plus the end at 38 m
    assert (out / "centrelines.geojson").is_file()


def test_facility_below_min_observed_skipped(tmp_path):
    features = [
        _feature("S-scanned", [[2.0, 10.0], [20.0, 10.0]]),
        _feature("I-empty", [[2.0, 10.0], [20.0, 10.0]], kind="intersection"),
    ]
    ctx, out = _write_run(
        tmp_path, features, observed={"S-scanned": 0.9, "I-empty": 0.1}
    )
    result = registry.lookup("profile", "centreline")(ctx, ProfileParams())
    assert result.metrics["not_scanned_enough"] == ["I-empty"]
    assert {r[0] for r in _rows(out)} == {"S-scanned"}
    geo = json.loads((out / "centrelines.geojson").read_text())
    assert [f["properties"]["facility"] for f in geo["features"]] == ["S-scanned"]


def test_height_invalid_writes_no_heights(tmp_path):
    ctx, out = _write_run(
        tmp_path,
        [_feature("S-1", [[2.0, 10.0], [20.0, 10.0]])],
        observed={"S-1": 1.0},
        height_valid=False,
    )
    result = registry.lookup("profile", "centreline")(ctx, ProfileParams())
    assert result.metrics["height_valid"] is False
    assert _rows(out) == []
    assert (out / "centrelines.geojson").is_file()
