import collections

import pytest
import yaml

from twin import registry, runner
from twin.cli import main
from twin.contracts import STAGE_NAMES, STAGES, Manifest, Params, Pipeline, StageResult

calls: collections.Counter = collections.Counter()


@pytest.fixture
def stubs(monkeypatch):
    """Empty registry plus stub stages that write one file each and count calls."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    calls.clear()

    def install(failing: str | None = None):
        for name in STAGE_NAMES:

            def run(ctx, params, name=name):
                calls[name] += 1
                (ctx.stage_dir(name) / "out.txt").write_text(f"{name} {calls[name]}")
                if name == failing:
                    return StageResult(status="failed", message="boom")
                return StageResult(status="ok", metrics={"n": calls[name]})

            registry.register(name, STAGES[name].methods[0])(run)

    return install


def _manifest(run_dir):
    return Manifest.model_validate_json((run_dir / "manifest.json").read_text())


def _snapshot(path):
    return {
        p.relative_to(path).as_posix(): (p.read_bytes(), p.stat().st_ino)
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def test_earlier_outputs_are_hard_links_and_parent_recorded(tmp_path, stubs):
    stubs()
    parent_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    parent_dir = tmp_path / parent_id
    before = _snapshot(parent_dir)

    run_id = runner.rerun(tmp_path, parent_id, "ground")
    run_dir = tmp_path / run_id
    assert run_id != parent_id

    for name in ("load", "mask", "align"):
        folder = f"{STAGES[name].number}_{name}"
        src = parent_dir / folder / "out.txt"
        dst = run_dir / folder / "out.txt"
        assert dst.read_text() == src.read_text()
        assert dst.stat().st_ino == src.stat().st_ino

    manifest = _manifest(run_dir)
    assert manifest.parent is not None
    assert manifest.parent.run_id == parent_id
    assert manifest.parent.from_stage == "ground"
    assert [s.name for s in manifest.stages] == list(STAGE_NAMES)
    assert manifest.metrics["load"] == {"n": 1}
    assert manifest.stages[0].files == ["out.txt"]

    # stages from ground on re-ran, earlier ones did not
    assert all(calls[n] == 1 for n in ("load", "mask", "align"))
    assert all(calls[n] == 2 for n in STAGE_NAMES[3:] if n != "semantics")  # off by default

    # the parent folder is only read
    assert _snapshot(parent_dir) == before
    assert _manifest(parent_dir).parent is None


def test_earlier_params_change_refused_naming_stage(tmp_path, stubs):
    stubs()
    parent_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    with pytest.raises(ValueError, match="re-run from stage mask"):
        runner.rerun(
            tmp_path, parent_id, "ground", params={"mask": {"box_margin_m": 0.5}}
        )
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 1
    assert calls["load"] == 1


def test_earlier_method_change_refused(tmp_path, stubs):
    stubs()
    parent_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    with pytest.raises(ValueError, match="re-run from stage align"):
        runner.rerun(
            tmp_path,
            parent_id,
            "ground",
            pipeline={"align": {"method": "dataset-poses"}},
        )


def test_change_from_stage_accepted(tmp_path, stubs):
    stubs()
    parent_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    run_id = runner.rerun(
        tmp_path, parent_id, "ground", params={"ground": {"voxel_m": 0.1}}
    )
    run_dir = tmp_path / run_id
    assert (
        yaml.safe_load((run_dir / "params.yaml").read_text())["ground"]["voxel_m"]
        == 0.1
    )
    # other params default to the parent's
    assert _manifest(run_dir).params.mask.box_margin_m == 0.3
    assert calls["ground"] == 2


def test_refused_when_parent_earlier_stage_failed(tmp_path, stubs):
    stubs(failing="mask")
    parent_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    with pytest.raises(ValueError, match="stage mask is failed"):
        runner.rerun(tmp_path, parent_id, "ground")
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 1


def test_cli_rerun_prints_id_and_exit_codes(tmp_path, stubs, capsys):
    stubs()
    parent_id = runner.start_run(tmp_path, "scene-1", Pipeline(), Params())
    capsys.readouterr()

    assert main(["rerun", parent_id, "--from", "isd", "--store", str(tmp_path)]) == 0
    new_id = capsys.readouterr().out.strip()
    assert _manifest(tmp_path / new_id).parent.from_stage == "isd"

    overrides = tmp_path / "over.yaml"
    overrides.write_text("mask:\n  box_margin_m: 0.5\n")
    assert (
        main(
            [
                "rerun",
                parent_id,
                "--from",
                "ground",
                "--params",
                str(overrides),
                "--store",
                str(tmp_path),
            ]
        )
        == 2
    )
    assert "re-run from stage mask" in capsys.readouterr().err
