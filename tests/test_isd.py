"""Stage 8 isd: synthetic plan, no data. Approaches leave an intersection core of half-width 10 m at the origin."""

import json
import logging

import numpy as np

from twin import registry
from twin.contracts import IsdParams
from twin.runner import StageContext
from twin.sightline import INDETERMINATE
from twin.stages.ground import _write_laz

CELL = 0.5
ORIGIN = (-130.0, -130.0)
N = 520  # 260 m square, so approaches on every side are covered
REQUIRED = 0.278 * 50.0 * 7.5  # 104.25 m, default params
CORE = 10.0
LENGTH = 110.0
EYE_SETBACK = 4.4
DIRS = {"N": (0.0, 1.0), "E": (1.0, 0.0), "S": (0.0, -1.0), "W": (-1.0, 0.0)}


def _surface(count=50):
    return {
        "z": np.zeros((N, N)),
        "count": np.full((N, N), count, dtype=np.int64),
        "origin": np.array(ORIGIN, dtype=float),
        "cell_m": np.float64(CELL),
    }


def _fields(xyz):
    n = len(xyz)
    return {
        "x": xyz[:, 0],
        "y": xyz[:, 1],
        "z": xyz[:, 2],
        "intensity": np.full(n, 10, np.uint16),
        "sweep": np.zeros(n, np.int32),
    }


def _grid(x, ys, zs):
    """Points on a plane at x, over ys and zs (dense enough that a sight line cannot slip between them)."""
    yy, zz = np.meshgrid(ys, zs)
    return np.column_stack([np.full(yy.size, x), yy.ravel(), zz.ravel()])


def _intersection(dirs):
    """Legs start on the core edge and run 110 m outward. Each eye sits 4.4 m back from the core edge."""
    legs, eyes = [], []
    for name in dirs:
        dx, dy = DIRS[name]
        start = [CORE * dx, CORE * dy]
        far = [(CORE + LENGTH) * dx, (CORE + LENGTH) * dy]
        eye = [(CORE + EYE_SETBACK) * dx, (CORE + EYE_SETBACK) * dy]
        legs.append(
            {
                "approach": name,
                "geometry": {"type": "LineString", "coordinates": [start, far]},
            }
        )
        eyes.append(
            {
                "approach": name,
                "source": "setback",
                "geometry": {"type": "Point", "coordinates": eye},
            }
        )
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-CORE, -CORE],
                    [CORE, -CORE],
                    [CORE, CORE],
                    [-CORE, CORE],
                    [-CORE, -CORE],
                ]
            ],
        },
        "properties": {
            "id": "I-test",
            "type": "intersection",
            "legs": legs,
            "eye_points": eyes,
        },
    }


def _write_run(
    tmp_path, feature, nonground=None, parked=None, height_valid=True, observed=1.0
):
    run = tmp_path / "run"
    load = run / "1_load"
    load.mkdir(parents=True)
    ident = {"matrix": np.eye(4).tolist()}
    (load / "poses.json").write_text(json.dumps({"poses": [ident]}))
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


def _legs(out):
    doc = json.loads((out / "isd.json").read_text())
    return {leg["leg"]: leg for leg in doc["facilities"][0]["legs"]}


def test_cross_each_approach_has_left_and_right(tmp_path):
    ctx, out = _write_run(tmp_path, _intersection(["N", "E", "S", "W"]))
    assert _run(ctx).status == "ok"
    legs = _legs(out)
    assert set(legs) == {"N", "E", "S", "W"}
    for leg in legs.values():
        assert leg["required_m"] == round(REQUIRED, 2)
        assert leg["status"] == "ok"
        for side in ("left", "right"):
            assert leg[side]["status"] == "ok"
            assert leg[side]["available_m"] == round(REQUIRED, 2)
            assert leg[side]["available_with_parked_m"] == round(REQUIRED, 2)
    # N viewer faces south: west is on its right, east on its left.
    assert legs["N"]["right"]["leg"] == "W"
    assert legs["N"]["left"]["leg"] == "E"


def test_wall_on_east_leg_shortens_only_views_along_east(tmp_path):
    # Wall across the east approach, 40 m out from its core edge (x = 10 + 40), 3 m high, wide enough to cover
    # every sight line from the north and south approaches.
    wall = _grid(50.0, np.arange(-60.0, 60.0001, 0.2), np.arange(0.2, 3.0001, 0.2))
    ctx, out = _write_run(tmp_path, _intersection(["N", "E", "S", "W"]), nonground=wall)
    _run(ctx)
    legs = _legs(out)
    # Views along the east approach from north and south: shortened to about 40 m.
    assert abs(legs["N"]["left"]["available_m"] - 40.0) <= 0.5 + 1e-6
    assert abs(legs["S"]["right"]["available_m"] - 40.0) <= 0.5 + 1e-6
    # Views along the other approaches are unchanged.
    assert legs["N"]["right"]["available_m"] == round(REQUIRED, 2)
    assert legs["S"]["left"]["available_m"] == round(REQUIRED, 2)
    assert legs["E"]["left"]["available_m"] == round(REQUIRED, 2)
    assert legs["E"]["right"]["available_m"] == round(REQUIRED, 2)
    assert legs["W"]["left"]["available_m"] == round(REQUIRED, 2)
    assert legs["W"]["right"]["available_m"] == round(REQUIRED, 2)


def test_t_stem_has_both_sides_through_legs_have_one_null(tmp_path):
    # Through approaches E and W, stem S. Opposite approaches are not crossings.
    ctx, out = _write_run(tmp_path, _intersection(["E", "S", "W"]))
    _run(ctx)
    legs = _legs(out)
    assert legs["S"]["left"] is not None and legs["S"]["right"] is not None
    assert legs["E"]["right"] is None and legs["E"]["left"]["leg"] == "S"
    assert legs["W"]["left"] is None and legs["W"]["right"]["leg"] == "S"
    assert legs["E"]["status"] == "ok"
    assert "no crossing approach" in legs["E"]["reason"]


def test_parked_row_blocks_only_with_parked(tmp_path):
    # Parked vehicles across the east approach, 60 m out from its core edge (x = 70).
    row = _grid(70.0, np.arange(-60.0, 60.0001, 0.2), np.arange(0.5, 1.5001, 0.2))
    ctx, out = _write_run(tmp_path, _intersection(["N", "E", "S", "W"]), parked=row)
    _run(ctx)
    north_left = _legs(out)["N"]["left"]
    assert north_left["available_m"] == round(REQUIRED, 2)
    assert north_left["available_with_parked_m"] <= north_left["available_m"]
    assert abs(north_left["available_with_parked_m"] - 60.0) <= 0.5 + 1e-6


def test_height_invalid_is_indeterminate(tmp_path):
    ctx, out = _write_run(
        tmp_path, _intersection(["N", "E", "S", "W"]), height_valid=False
    )
    _run(ctx)
    for leg in _legs(out).values():
        assert leg["status"] == INDETERMINATE
        assert leg["left"]["available_m"] is None
        assert leg["right"]["available_m"] is None


def test_not_scanned_facility_is_skipped(tmp_path):
    ctx, out = _write_run(tmp_path, _intersection(["N", "E", "S", "W"]), observed=0.2)
    result = _run(ctx)
    doc = json.loads((out / "isd.json").read_text())
    assert doc["facilities"] == []
    assert doc["not_scanned_enough"] == ["I-test"]
    assert result.metrics["not_scanned_enough"] == ["I-test"]
    assert result.metrics["case"] and isinstance(result.metrics["facilities"], list)
