import json

import pytest
from filelock import FileLock

from twin import jobqueue, registry
from twin.cli import main
from twin.contracts import STAGE_NAMES, STAGES, StageResult


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})

    def install(failing=None):
        for name in STAGE_NAMES:

            def run(ctx, params, name=name):
                (ctx.stage_dir(name) / "out.txt").write_text(name)
                if name == failing:
                    return StageResult(status="failed", message="boom")
                return StageResult(status="ok")

            registry.register(name, STAGES[name].methods[0])(run)

    return install


def _states(store):
    return {s: len(list((store / "queue" / s).glob("*.json"))) for s in jobqueue.STATES}


def no_hold():
    return None


def test_add_validates_and_lists(tmp_path):
    job_id = jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert _states(tmp_path)["pending"] == 1
    assert jobqueue.list_jobs(tmp_path)[0]["id"] == job_id
    with pytest.raises(ValueError):
        jobqueue.add(tmp_path, {"type": "nope"})
    with pytest.raises(ValueError):
        jobqueue.add(tmp_path, {"type": "rerun", "run_id": "x"})


def test_take_is_oldest_first_and_once(tmp_path):
    a = jobqueue.add(tmp_path, {"type": "run", "scene": "a"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "b"})
    job = jobqueue.take(tmp_path)
    assert job["id"] == a and "started" in job
    assert _states(tmp_path) == {"pending": 1, "running": 1, "done": 0, "failed": 0}


def test_run_job_finishes(tmp_path, stubs):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.process_one(tmp_path, no_hold).startswith("done")
    assert _states(tmp_path)["done"] == 1
    done = jobqueue.list_jobs(tmp_path)[0]
    assert (tmp_path / done["run_id"] / "manifest.json").is_file()
    assert jobqueue.process_one(tmp_path, no_hold) is None


def test_failed_stage_fails_job(tmp_path, stubs):
    stubs(failing="ground")
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.process_one(tmp_path, no_hold).startswith("failed")
    assert _states(tmp_path)["failed"] == 1
    assert jobqueue.list_jobs(tmp_path)[0]["error"]


def test_bad_job_fails_without_stopping_worker(tmp_path, stubs):
    stubs()
    jobqueue.add(
        tmp_path,
        {"type": "rerun", "run_id": "20200101-000000-aaaaaa", "from_stage": "ground"},
    )
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.worker(tmp_path, jobs=2, poll=0, hold=no_hold) == 0
    assert _states(tmp_path)["failed"] == 1 and _states(tmp_path)["done"] == 1


def test_eval_skipped_without_gates(tmp_path, stubs, monkeypatch):
    stubs()
    monkeypatch.setattr(jobqueue.importlib.util, "find_spec", lambda name: None)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1", "eval": True})
    jobqueue.process_one(tmp_path, no_hold)
    assert jobqueue.list_jobs(tmp_path)[0]["eval_result"].startswith("skipped")


def test_eval_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(jobqueue.importlib.util, "find_spec", lambda name: object())
    for code, want in ((0, "go"), (1, "no-go")):
        monkeypatch.setattr(
            jobqueue.subprocess,
            "run",
            lambda cmd, check, code=code: type("R", (), {"returncode": code})(),
        )
        assert jobqueue.run_eval(tmp_path, {}, "r") == (want, None)
    monkeypatch.setattr(
        jobqueue.subprocess,
        "run",
        lambda cmd, check: type("R", (), {"returncode": 2})(),
    )
    assert jobqueue.run_eval(tmp_path, {}, "r")[1]


def test_crash_recovery_requeues_running(tmp_path, stubs):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    jobqueue.take(tmp_path)  # worker dies here
    assert _states(tmp_path)["running"] == 1
    assert jobqueue.worker(tmp_path, jobs=1, poll=0, hold=no_hold) == 0
    assert _states(tmp_path) == {"pending": 0, "running": 0, "done": 1, "failed": 0}


def test_disk_hold_keeps_job_pending(tmp_path, stubs):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    status = jobqueue.process_one(tmp_path, lambda: "0.0 GB free on /; need 10 GB")
    assert status.startswith("held")
    assert _states(tmp_path)["pending"] == 1
    assert jobqueue.disk_hold(((str(tmp_path), 10**9),)) is not None
    assert jobqueue.disk_hold(((str(tmp_path / "missing"), 10**9),)) is None


def test_busy_store_releases_job(tmp_path, stubs):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    with FileLock(str(tmp_path / ".run.lock")):
        assert jobqueue.process_one(tmp_path, no_hold).startswith("held")
    assert _states(tmp_path)["pending"] == 1


def test_second_worker_refused(tmp_path):
    with FileLock(str(tmp_path / "queue" / ".worker.lock")):
        (tmp_path / "queue").mkdir(exist_ok=True)
        assert jobqueue.worker(tmp_path, jobs=1, poll=0, hold=no_hold) == 3


def test_cli_add_and_ls(tmp_path, capsys):
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"type": "run", "scene": "s1"}))
    assert main(["queue", "add", str(job), "--store", str(tmp_path / "st")]) == 0
    job_id = capsys.readouterr().out.strip()
    assert main(["queue", "ls", "--store", str(tmp_path / "st")]) == 0
    assert job_id in capsys.readouterr().out
    job.write_text("{}")
    assert main(["queue", "add", str(job), "--store", str(tmp_path / "st")]) == 2
