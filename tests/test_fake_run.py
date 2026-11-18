# Channel fixture: tests/fixtures/ (or tests/conftest.py).
import json
import re
from pathlib import Path

import ezdxf
import ezdxf.recover
import laspy
import numpy as np
import pytest
import yaml
from PIL import Image

from twin.cli import main
from twin.contracts import (
    STAGE_NAMES,
    STAGES,
    AreaIndex,
    Manifest,
    Params,
    Pipeline,
    StageResult,
)
from twin.fake_run import DRIVE_SPECS, FACILITIES, write_fake_runs
from twin.publish import publish_runs

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    base = tmp_path_factory.mktemp("fake")
    write_fake_runs(base / "runs", drives=2)
    return base / "runs"


def _runs(out: Path) -> list[Path]:
    return sorted(p for p in out.iterdir() if p.is_dir() and p.name != "showcase")


def test_run_folder_layout(out):
    runs = _runs(out)
    assert len(runs) == 2
    for run in runs:
        assert RUN_ID.match(run.name)
        for f in ("pipeline.yaml", "params.yaml", "manifest.json"):
            assert (run / f).is_file()
        for name in STAGE_NAMES:
            folder = run / f"{STAGES[name].number}_{name}"
            for output in STAGES[name].outputs:
                assert (folder / output).is_file(), output


def test_manifest_valid_all_stages_ok(out):
    for run in _runs(out):
        m = Manifest.model_validate_json((run / "manifest.json").read_text())
        assert m.run_id == run.name
        assert [s.name for s in m.stages] == list(STAGE_NAMES)
        assert all(s.status == "ok" for s in m.stages)
        assert m.metrics["ground"]["height_valid"] is True
        assert m.metrics["ground"]["rmse_m"] < 0.05
        assert "edge_offset_p50_m" in m.metrics["colour"]
        assert m.metrics["colour"]["edge_offset_p50_m"] is None
        assert "edge_offset_p95_m" in m.metrics["colour"]
        assert m.metrics["colour"]["edge_offset_p95_m"] is None
        assert m.metrics["colour"]["pose_corrections"] is None


def test_fake_accuracy_matches_real_stage(out, tmp_path):
    """The real one-way stage, run on a copy of a fake run, gives the same keys the fake writes."""
    import logging
    import shutil

    from twin import registry
    from twin.contracts import AccuracyParams
    from twin.runner import StageContext

    run = _runs(out)[0]
    copy = tmp_path / run.name
    shutil.copytree(run, copy)
    ctx = StageContext(
        run_dir=copy,
        scene_token="fake-scene-0001",
        seed=0,
        log=logging.getLogger("test"),
    )
    result = registry.lookup("accuracy", "one-way")(ctx, AccuracyParams())
    real = result.metrics
    fake = json.loads((run / "manifest.json").read_text())["metrics"]["accuracy"]

    assert set(fake) == set(real)
    assert fake["method"] == real["method"] and fake["buffer_m"] == real["buffer_m"]
    assert set(fake["qa"]) == set(real["qa"])
    for scope in ("elements", "facilities"):
        assert set(fake[scope]) == set(real[scope]), scope
        for key, entry in real[scope].items():
            assert set(fake[scope][key]) == set(entry), (scope, key)
    assert fake["facilities"] and all(
        set(e) == set(next(iter(real["facilities"].values())))
        for e in fake["facilities"].values()
    )


def test_pipeline_and_params_yaml_round_trip(out):
    for run in _runs(out):
        Pipeline.model_validate(yaml.safe_load((run / "pipeline.yaml").read_text()))
        Params.model_validate(yaml.safe_load((run / "params.yaml").read_text()))


def test_outputs_validate_against_schemas(out):
    for run in _runs(out):
        manifest = json.loads((run / "manifest.json").read_text())
        for name in STAGE_NAMES:
            folder = run / f"{STAGES[name].number}_{name}"
            StageResult.model_validate_json((folder / "stage_result.json").read_text())
        AreaIndex.model_validate_json((out / "showcase" / "area.json").read_text())
        try:
            import jsonschema
        except ImportError:
            continue
        pairs = {
            "manifest": manifest,
            "pipeline": yaml.safe_load((run / "pipeline.yaml").read_text()),
            "params": yaml.safe_load((run / "params.yaml").read_text()),
            "area_index": json.loads((out / "showcase" / "area.json").read_text()),
            "stage_result": json.loads(
                (run / "1_load" / "stage_result.json").read_text()
            ),
        }
        for schema_name, doc in pairs.items():
            schema = json.loads((SCHEMAS / f"{schema_name}.schema.json").read_text())
            jsonschema.validate(doc, schema)


def test_stage_files_are_readable(out):
    run = _runs(out)[0]
    pts = np.load(run / "1_load" / "points.npz")
    assert {"x", "y", "z", "intensity", "sweep"} <= set(pts.files)
    assert len(pts["x"]) > 1000
    las = laspy.read(run / "4_ground" / "ground.laz")
    assert len(las.points) > 1000
    for name in ("markings", "crosswalks", "curbs"):
        doc = json.loads((run / "5_features" / f"{name}.geojson").read_text())
        assert doc["type"] == "FeatureCollection"
    assert (
        (run / "7_profile" / "profile.csv")
        .read_text()
        .startswith("facility,line,s_m,z_m,n")
    )
    assert Image.open(run / "6_colour" / "ortho.png").size == (256, 256)
    assert (run / "10_outputs" / "profile.pdf").read_bytes().startswith(b"%PDF")
    assert (run / "10_outputs" / "plan.pdf").read_bytes().startswith(b"%PDF")
    for dxf in ("plan.dxf", "profile.dxf"):
        doc = ezdxf.readfile(run / "10_outputs" / dxf)
        assert not doc.audit().has_errors


def test_area_index_has_variety(out):
    area = AreaIndex.model_validate_json((out / "showcase" / "area.json").read_text())
    run_ids = {d.run_id for d in area.drives}
    assert len(area.drives) >= 2
    assert {d.run_id for d in area.drives} == {p.name for p in _runs(out)}
    assert {d.scene_token for d in area.drives} == {s.scene_token for s in DRIVE_SPECS}
    assert all(d.name == d.scene_token for d in area.drives)
    assert all(len(d.bbox) == 4 and d.bbox[2] > d.bbox[0] and d.bbox[3] > d.bbox[1] for d in area.drives)
    assert len(area.facilities) >= 6
    assert len({f.id for f in area.facilities}) == len(area.facilities)
    types = {f.type for f in area.facilities}
    assert types == {"intersection", "segment", "access_point"}
    for f in area.facilities:
        assert f.not_scanned_enough == (f.observed_core < 0.5)
        assert f.best_run in f.runs and set(f.runs) <= run_ids
    assert any(f.not_scanned_enough for f in area.facilities)
    assert len(FACILITIES) == len(area.facilities)



def test_showcase_size_under_5mb(out):
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    assert total < 5 * 1024 * 1024


def test_existing_run_is_not_overwritten(out):
    with pytest.raises(FileExistsError):
        write_fake_runs(out, drives=1)


def test_cli_fake_run(tmp_path, capsys):
    assert main(["fake-run", "--out", str(tmp_path), "--drives", "1"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 1
    assert (tmp_path / "showcase" / "area.json").is_file()


def test_real_outputs_stage_end_to_end_with_colour(tmp_path):
    import logging
    import shutil

    from twin import registry
    from twin.runner import StageContext

    (run,) = write_fake_runs(tmp_path / "runs", drives=1)
    with np.load(run / "6_colour" / "rgb.npz") as f:
        rgb, observed = f["rgb"], f["observed"]
    n = len(laspy.read(run / "4_ground" / "ground.laz").points) + len(
        laspy.read(run / "4_ground" / "nonground.laz").points
    )
    assert rgb.shape == (n, 3) and rgb.dtype == np.uint8
    assert observed.shape == (n,) and observed.dtype == bool

    shutil.rmtree(run / "10_outputs")
    (run / "10_outputs").mkdir()
    ctx = StageContext(
        run_dir=run,
        scene_token="fake-scene-0001",
        seed=0,
        log=logging.getLogger("test"),
    )
    result = registry.lookup("outputs", "dxf-pdf")(ctx, None)

    assert result.status == "ok"
    assert result.files == [
        "twin.laz",
        "twin.geojson",
        "plan.dxf",
        "plan.pdf",
        "profile.dxf",
        "profile.pdf",
    ]
    las = laspy.read(run / "10_outputs" / "twin.laz")
    assert las.header.point_format.id == 7
    assert las.red.max() > 0
    doc, auditor = ezdxf.recover.readfile(run / "10_outputs" / "plan.dxf")
    assert not auditor.has_errors
    sight = [e for e in doc.modelspace() if e.dxf.layer == "SIGHTLINES"]
    assert any(e.dxftype() == "LINE" for e in sight)


def test_showcase_has_profile_and_downloads(out):
    for run in _runs(out):
        for f in (
            "manifest.json",
            "twin.geojson",
            "profile.csv",
            "twin.laz",
            "plan.pdf",
        ):
            assert (out / "showcase" / run.name / f).is_file(), f


def test_same_inputs_give_identical_metrics(tmp_path):
    """The fake pipeline run twice gives the same metrics for every stage (issue 139)."""
    metrics = []
    for k in range(2):
        write_fake_runs(tmp_path / f"r{k}", drives=1)
        run = _runs(tmp_path / f"r{k}")[0]
        metrics.append(json.loads((run / "manifest.json").read_text())["metrics"])
    assert metrics[0] == metrics[1]


def _showcase_snapshot(showcase: Path) -> dict:
    snap = {}
    for path in sorted(p for p in showcase.rglob("*") if p.is_file()):
        rel = path.relative_to(showcase).as_posix()
        if rel == "area.json" or path.suffix == ".json":
            snap[rel] = json.loads(path.read_text())
        else:
            snap[rel] = path.read_bytes()
    return snap


def test_fake_showcase_equals_publish_runs(tmp_path):
    out = tmp_path / "runs"
    paths = write_fake_runs(out, drives=2)
    run_ids = [p.name for p in paths]
    ref = tmp_path / "ref"
    publish_runs(run_ids, ref, store=out)
    assert _showcase_snapshot(out / "showcase") == _showcase_snapshot(ref)


def test_fake_run_has_ramps(out):
    run = _runs(out)[0]
    f = run / "5_features" / "ramps.geojson"
    assert f.is_file()
    doc = json.loads(f.read_text())
    assert doc["type"] == "FeatureCollection"
    assert doc["features"]
    qa = json.loads((run / "5_features" / "qa.json").read_text())
    for k in ("n_ramps", "n_curb_ramps", "n_driveway_or_ramp", "n_ramps_ok", "n_ramps_exceeds", "n_ramps_indeterminate"):
        assert k in qa
