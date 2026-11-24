import json
from pathlib import Path

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
    assert (tmp_path / done["run_id"] / "run.json").is_file()
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


import os
import sys


def test_serial_job_runs_in_scope_with_its_cap(tmp_path, stubs, monkeypatch):
    stubs()
    calls_file = tmp_path / "caps.txt"

    class RecordingLauncher:
        systemd = None
        cgroup = None

        def enter(self, cap, key):
            with open(calls_file, "a") as f:
                f.write(f"{cap}\n")
            return True

        def oom_killed(self, key):
            return False

        def cleanup(self, key):
            pass

    def _launcher():
        inst = RecordingLauncher()
        jobqueue.memcap._LAUNCHER = inst
        return inst

    monkeypatch.setattr(jobqueue.memcap, "_LAUNCHER", None)
    monkeypatch.setattr(jobqueue.memcap, "launcher", _launcher)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.process_one(tmp_path, no_hold).startswith("done")
    assert _states(tmp_path)["done"] == 1
    assert calls_file.read_text().strip() == "8.0"


def test_serial_job_cap_override_from_job_field(tmp_path, stubs, monkeypatch):
    stubs()
    calls_file = tmp_path / "caps.txt"

    class RecordingLauncher:
        systemd = None
        cgroup = None

        def enter(self, cap, key):
            with open(calls_file, "a") as f:
                f.write(f"{cap}\n")
            return True

        def oom_killed(self, key):
            return False

        def cleanup(self, key):
            pass

    def _launcher():
        inst = RecordingLauncher()
        jobqueue.memcap._LAUNCHER = inst
        return inst

    monkeypatch.setattr(jobqueue.memcap, "_LAUNCHER", None)
    monkeypatch.setattr(jobqueue.memcap, "launcher", _launcher)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1", "mem_cap_gb": 5})
    assert jobqueue.process_one(tmp_path, no_hold).startswith("done")
    assert calls_file.read_text().strip() == "5.0"


def test_serial_job_cap_killed_marks_failed_oom_cap(tmp_path, stubs, monkeypatch):
    import os as _os

    stubs()
    real_execute = jobqueue.execute

    def fake_execute(store, job):
        counter_file = Path(store) / "exec_counter.txt"
        n = 0
        if counter_file.exists():
            n = int(counter_file.read_text())
        n += 1
        counter_file.write_text(str(n))
        if n == 1:
            _os._exit(9)
        return real_execute(store, job)

    monkeypatch.setattr(jobqueue, "execute", fake_execute)
    monkeypatch.setattr(jobqueue.memcap, "oom_killed", lambda key: True)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.worker(tmp_path, jobs=2, poll=0, hold=no_hold) == 0
    jobs = jobqueue.list_jobs(tmp_path)
    states = [j["state"] for j in jobs]
    assert "failed" in states and "done" in states
    failed = [j for j in jobs if j["state"] == "failed"][0]
    assert failed["error"] == "oom-cap"


def test_err_with_a_cap_kill_maps_to_oom_cap(tmp_path, stubs, monkeypatch):
    stubs()

    def fake_execute(store, job):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobqueue, "execute", fake_execute)
    monkeypatch.setattr(jobqueue.memcap, "oom_killed", lambda key: True)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.process_one(tmp_path, no_hold).startswith("failed")
    job = jobqueue.list_jobs(tmp_path)[0]
    assert job["state"] == "failed" and job["error"] == "oom-cap"


@pytest.mark.skipif(sys.platform != "linux", reason="/proc/self/fd")
def test_serial_jobs_leave_no_children_or_fds(tmp_path, stubs, monkeypatch):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    before = len(os.listdir("/proc/self/fd"))
    assert jobqueue.worker(tmp_path, jobs=3, poll=0, hold=no_hold) == 0
    after = len(os.listdir("/proc/self/fd"))
    assert _states(tmp_path)["done"] == 3
    assert after - before <= 1
