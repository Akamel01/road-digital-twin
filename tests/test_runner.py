import re

import pytest
import yaml
from filelock import FileLock

from twin import registry, runner
from twin.cli import main
from twin.contracts import (
    STAGE_NAMES,
    STAGES,
    Manifest,
    Params,
    Pipeline,
    PipelineStage,
    StageResult,
)

RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")


@pytest.fixture
def stubs(monkeypatch):
    """Empty registry plus stub stages that write one file each."""
    monkeypatch.setattr(registry, "_REGISTRY", {})

    def install(failing: str | None = None):
        for name in STAGE_NAMES:

            def run(ctx, params, name=name):
                (ctx.stage_dir(name) / "out.txt").write_text(name)
                if name == failing:
                    return StageResult(status="failed", message="boom")
                return StageResult(status="ok", metrics={"n": 1})

            registry.register(name, STAGES[name].methods[0])(run)

    return install


def _manifest(run_dir):
    return Manifest.model_validate_json((run_dir / "manifest.json").read_text())


def test_happy_path_manifest_valid_and_all_ok(tmp_path, stubs):
    stubs()
    run_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    assert RUN_ID.fullmatch(run_id)
    run_dir = tmp_path / run_id
    assert (run_dir / "pipeline.yaml").is_file()
    assert yaml.safe_load((run_dir / "params.yaml").read_text())["seed"] == 0
    manifest = _manifest(run_dir)
    assert [s.name for s in manifest.stages] == list(STAGE_NAMES)
    assert {s.status for s in manifest.stages} == {"ok"}
    assert manifest.stages[0].files == ["out.txt"]
    assert manifest.stages[0].seconds >= 0
    assert manifest.metrics["load"] == {"n": 1}
    assert manifest.data.scene_token == "scene-1"
    assert (run_dir / "1_load" / "out.txt").read_text() == "load"
    assert (run_dir / "10_outputs").is_dir()


def test_failing_stage_stops_and_exit_1(tmp_path, stubs, capsys):
    stubs(failing="mask")
    rc = main(["run", "--scene", "scene-1", "--store", str(tmp_path)])
    assert rc == 1
    run_id = capsys.readouterr().out.strip()
    manifest = _manifest(tmp_path / run_id)
    assert [(s.name, s.status) for s in manifest.stages] == [
        ("load", "ok"),
        ("mask", "failed"),
    ]


def test_invalid_params_exit_2_and_no_folder(tmp_path, stubs, capsys):
    stubs()
    params = tmp_path / "params.yaml"
    params.write_text("ground:\n  voxel_m: 0.01\n")
    rc = main(
        [
            "run",
            "--scene",
            "scene-1",
            "--params",
            str(params),
            "--store",
            str(tmp_path / "runs"),
        ]
    )
    assert rc == 2
    assert "voxel_m" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_unregistered_method_exit_2(tmp_path, stubs, capsys):
    stubs()
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        "align:\n  method: dataset-poses\n"
    )  # listed in contracts, not registered
    rc = main(
        [
            "run",
            "--scene",
            "scene-1",
            "--pipeline",
            str(pipeline),
            "--store",
            str(tmp_path / "runs"),
        ]
    )
    assert rc == 2
    assert not (tmp_path / "runs").exists()


def test_runs_never_overwritten(tmp_path, stubs, monkeypatch):
    stubs()
    ids = iter(
        ["20260101-000000-aaaaaa", "20260101-000000-aaaaaa", "20260101-000000-bbbbbb"]
    )
    monkeypatch.setattr(runner, "_make_run_id", lambda: next(ids))
    first = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    second = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    assert first == "20260101-000000-aaaaaa"
    assert second == "20260101-000000-bbbbbb"
    assert _manifest(tmp_path / first).run_id == first


def test_disabled_optional_stage_skipped(tmp_path, stubs):
    stubs()
    pipeline = Pipeline(colour=PipelineStage(method="zbuffer-topk", enabled=False))
    run_id = runner.start_run(tmp_path, "scene-1", pipeline, Params())
    run_dir = tmp_path / run_id
    manifest = _manifest(run_dir)
    colour = next(s for s in manifest.stages if s.name == "colour")
    assert colour.status == "skipped"
    assert colour.files == []
    assert not (run_dir / "6_colour").exists()
    assert "colour" not in manifest.metrics


GB = 1024**3


@pytest.fixture(autouse=True)
def roomy_disk(monkeypatch):
    monkeypatch.setattr(runner, "free_bytes", lambda path: 100 * GB)


def test_second_run_refused_while_lock_held(tmp_path, stubs, capsys):
    stubs()
    holder = FileLock(str(tmp_path / runner.LOCK_FILE))
    holder.acquire()
    try:
        (tmp_path / runner.CURRENT_FILE).write_text("20990101-000000-abcdef")
        assert main(["run", "--scene", "scene-1", "--store", str(tmp_path)]) == 2
    finally:
        holder.release()
    err = capsys.readouterr().err
    assert "another run is in progress (20990101-000000-abcdef)" in err
    assert not any(p.name.startswith("2") for p in tmp_path.iterdir())


def test_lock_released_after_run(tmp_path, stubs):
    stubs()
    runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    assert not (tmp_path / runner.CURRENT_FILE).exists()
    runner.start_run(tmp_path, "scene-1", Pipeline(), Params())


def test_cancel_between_stages_marks_rest_cancelled(
    tmp_path, stubs, monkeypatch, capsys
):
    stubs()
    key = ("mask", STAGES["mask"].methods[0])
    original = registry.lookup(*key)

    def cancelling(ctx, params):
        result = original(ctx, params)
        runner.cancel(tmp_path, ctx.run_dir.name)  # requested while mask runs
        return result

    monkeypatch.setitem(registry._REGISTRY, key, cancelling)
    assert main(["run", "--scene", "scene-1", "--store", str(tmp_path)]) == 1
    assert "cancelled" in capsys.readouterr().err

    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    manifest = _manifest(run_dir)
    statuses = {s.name: s.status for s in manifest.stages}
    assert [statuses[n] for n in STAGE_NAMES[:2]] == ["ok", "ok"]
    assert all(statuses[n] == "cancelled" for n in STAGE_NAMES[2:])
    cancelled = next(s for s in manifest.stages if s.name == "ground")
    assert cancelled.seconds == 0 and cancelled.files == []
    assert (run_dir / "1_load" / "out.txt").read_text() == "load"
    assert (run_dir / "2_mask" / "out.txt").read_text() == "mask"
    assert not (run_dir / "3_ground").exists()


def test_cancel_unknown_run_exit_2(tmp_path, capsys):
    assert main(["cancel", "20990101-000000-abcdef", "--store", str(tmp_path)]) == 2
    assert "not found" in capsys.readouterr().err


def test_low_disk_refused_before_any_folder(tmp_path, stubs, monkeypatch, capsys):
    stubs()
    monkeypatch.setattr(runner, "free_bytes", lambda path: 5 * GB)
    store = tmp_path / "store"
    with pytest.raises(ValueError, match="need 10 GB"):
        runner.start_run(store, "scene-1", Pipeline(), Params())
    assert not any(p.is_dir() for p in store.iterdir())
    assert main(["run", "--scene", "scene-1", "--store", str(store)]) == 2
    assert "need 10 GB" in capsys.readouterr().err


def _load_stub(metrics):
    def run(ctx, params):
        (ctx.stage_dir("load") / "out.txt").write_text("load")
        return StageResult(status="ok", metrics=metrics)

    return run


def test_manifest_osm_names_lifted_from_load_metric(tmp_path, stubs):
    stubs()
    osm = {"overpass_query_date": "2026-11-08", "licence": "ODbL"}
    registry._REGISTRY[("load", "nuscenes")] = _load_stub({"osm_names": osm})
    run_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    manifest = _manifest(tmp_path / run_id)
    assert manifest.data.osm_names is not None
    assert manifest.data.osm_names.overpass_query_date.isoformat() == "2026-11-08"
    assert manifest.data.osm_names.licence == "ODbL"


def test_manifest_osm_names_null_when_load_has_no_query(tmp_path, stubs):
    stubs()
    registry._REGISTRY[("load", "nuscenes")] = _load_stub({"osm_names": None})
    run_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    assert _manifest(tmp_path / run_id).data.osm_names is None
