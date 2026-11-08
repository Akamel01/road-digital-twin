from filelock import FileLock

from twin.contracts import Manifest
from twin.fake_run import write_fake_runs
from twin.runner import CURRENT_FILE, INTERRUPTED, LOCK_FILE, recover_interrupted


def _make_running(run_dir, stage_name):
    path = run_dir / "manifest.json"
    manifest = Manifest.model_validate_json(path.read_text())
    for stage in manifest.stages:
        if stage.name == stage_name:
            stage.status = "running"
    path.write_text(manifest.model_dump_json(indent=2))
    return manifest.run_id


def test_running_stage_marked_failed_and_locks_cleared(tmp_path):
    run_dirs = write_fake_runs(tmp_path / "store", drives=1)
    run_id = _make_running(run_dirs[0], "ground")
    (tmp_path / "store" / CURRENT_FILE).write_text(run_id)
    (tmp_path / "store" / LOCK_FILE).write_text("")

    assert recover_interrupted(tmp_path / "store") == [run_id]

    manifest = Manifest.model_validate_json((run_dirs[0] / "manifest.json").read_text())
    assert not [s for s in manifest.stages if s.status == "running"]
    assert [s.status for s in manifest.stages if s.name == "ground"] == ["failed"]
    assert manifest.metrics["ground"]["message"] == INTERRUPTED
    assert not (tmp_path / "store" / CURRENT_FILE).exists()
    assert not (tmp_path / "store" / LOCK_FILE).exists()


def test_no_running_stage_changes_nothing(tmp_path):
    run_dirs = write_fake_runs(tmp_path / "store", drives=1)
    before = (run_dirs[0] / "manifest.json").read_text()

    assert recover_interrupted(tmp_path / "store") == []
    assert (run_dirs[0] / "manifest.json").read_text() == before


def test_live_lock_holder_is_left_alone(tmp_path):
    run_dirs = write_fake_runs(tmp_path / "store", drives=1)
    run_id = _make_running(run_dirs[0], "ground")
    (tmp_path / "store" / CURRENT_FILE).write_text(run_id)
    held = FileLock(str(tmp_path / "store" / LOCK_FILE), thread_local=False)
    held.acquire()
    try:
        assert recover_interrupted(tmp_path / "store") == []
        manifest = Manifest.model_validate_json((run_dirs[0] / "manifest.json").read_text())
        assert [s.status for s in manifest.stages if s.name == "ground"] == ["running"]
        assert (tmp_path / "store" / CURRENT_FILE).exists()
    finally:
        held.release()


def test_missing_store_is_noop(tmp_path):
    assert recover_interrupted(tmp_path / "nope") == []
