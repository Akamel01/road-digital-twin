import re

import pytest
import yaml

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
