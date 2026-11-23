import sys

import pytest

from twin import jobqueue, prgate, runner
from twin import reload as reload_mod
from twin.reload import CodeWatch


def test_head_change_detection(monkeypatch):
    vals = iter(["aaa", "aaa", "aaa", "bbb"])
    monkeypatch.setattr(runner, "repo_head", lambda: next(vals))
    w = CodeWatch()
    w.start()
    assert w.changed() is None
    assert w.changed() == ("aaa", "bbb")


def test_worker_no_restart_mid_job(monkeypatch, tmp_path):
    # HEAD changes only after job started; check occurs before process_one
    calls = {"proc": 0}
    heads = iter(["h1", "h1", "h2", "h2"])
    monkeypatch.setattr(runner, "repo_head", lambda: next(heads))
    monkeypatch.setattr(jobqueue, "process_one", lambda store, hold=jobqueue.disk_hold: (calls.__setitem__("proc", calls["proc"] + 1) or "done x"))
    # avoid real lock issues: monkeypatch FileLock? Use jobs=1
    import twin.jobqueue as jq
    jq.worker(tmp_path, jobs=1, poll=0)
    assert calls["proc"] == 1


def test_autopilot_restart_path(monkeypatch, tmp_path):
    # CodeWatch.changed returns change on first loop; sys.exit(75)
    monkeypatch.setattr(reload_mod.CodeWatch, "changed", lambda self: ("old", "new"))
    monkeypatch.setattr("twin.autopilot.step", lambda *a, **k: "ok")
    exited = {}
    def fake_exit(code):
        exited["code"] = code
        raise SystemExit(code)
    monkeypatch.setattr(sys, "exit", fake_exit)
    with pytest.raises(SystemExit):
        from twin import autopilot
        autopilot.autopilot_command(tmp_path, poll=0, once=True)
    assert exited["code"] == 75


def test_pull_failure_path(monkeypatch, tmp_path, capsys):
    import subprocess
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0] if a else [], 1, stdout="", stderr="nope")
    monkeypatch.setattr(subprocess, "run", fake_run)
    # need git commit function
    from twin.autopilot import RealWorld

    class World(RealWorld):
        def main_commit(self):
            return "abc123"

    # store state
    (tmp_path / "autopilot").mkdir(parents=True, exist_ok=True)
    state = {"p2": {}, "p2b": {}}
    import json
    (tmp_path / "autopilot" / "state.json").write_text(json.dumps(state))
    from twin import autopilot
    autopilot.p2_area(tmp_path, state, World())
    out = capsys.readouterr().out
    assert "pull failed" in out


def test_p0_cap_handling(monkeypatch, tmp_path):
    calls = []
    def gh(*args):
        calls.append(args)
        if args[:2] == ("pr", "diff"):
            return "twin/stages/ground.py\n"
        if args[0] == "pr":
            return __import__("json").dumps([{"number": 3, "headRefOid": "e" * 40, "labels": []}])
        raise prgate.PrGateError("reached the maximum number of statuses")
    # set_status path: poll calls set_status which calls gh; make gh raise cap on status
    # We'll monkeypatch set_status to raise cap
    # ensure na file none
    prgate.poll(tmp_path, gh=gh)
    import json
    na_file = tmp_path / "queue" / "prgate-na.json"
    # cap path adds sha to na
    assert na_file.exists()
    assert "e" * 40 in json.loads(na_file.read_text())
