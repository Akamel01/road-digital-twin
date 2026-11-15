import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from twin import autopilot, health, jobqueue, site
from twin.cli import main

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
OK = {"worker": 1, "autopilot": 1, "telemetry": 1}


def _health(**over):
    base = {
        "updated": "x",
        "processes": {n: {"alive": True, "uptime_s": 9, "restarts_1h": 0} for n in OK},
        "queue": {"running": 1, "pending": 0},
        "tiers": {"P3 sweep": {"queued": None, "finished": None, "failed": {"at": "t", "error": "boom /home/a/x"}}},
        "idle_min": {"cpu": 0, "gpu": 0, "queue": 0, "all": 0},
        "paused": {},
        "fail_streaks": {},
        "disk_free_gb": {"/": 40.0, "/data": 900.0},
        "gpu": {},
        "progress": {},
        "throughput": {},
        "preflight": None,
    }
    return {**base, **over}


def _active(h):
    return {k for k, v in health.alarms(h).items() if v}


def test_each_alarm_rule():
    assert _active(_health()) == set()
    assert _active(_health(idle_min={"all": 31})) == {"idle"}
    assert _active(_health(idle_min={"all": 30})) == set()
    assert _active(_health(paused={"P3": "ValueError"})) == {"paused"}
    h = _health()
    h["processes"]["autopilot"]["restarts_1h"] = 4
    assert _active(h) == {"restarts"}
    h["processes"]["autopilot"]["restarts_1h"] = 3
    assert _active(h) == set()
    assert _active(_health(disk_free_gb={"/": 14.9, "/data": 1})) == {"disk"}
    assert _active(_health(preflight={"ok": False, "error": "no gpu"})) == {"preflight"}
    assert _active(_health(preflight={"ok": True})) == set()


class FakeGh:
    def __init__(self):
        self.calls, self.labels, self.n = [], [], 40

    def __call__(self, *a):
        self.calls.append(a)
        if a[:2] == ("label", "list"):
            return json.dumps([{"name": x} for x in self.labels])
        if a[:2] == ("label", "create"):
            self.labels.append(a[2])
        if a[:2] == ("issue", "create"):
            self.n += 1
            return f"https://github.com/o/r/issues/{self.n}\n"
        return ""

    def verbs(self):
        return [" ".join(c[:2]) for c in self.calls if c[0] == "issue"]


def test_open_dedupe_comment_and_close(tmp_path):
    gh, idle = FakeGh(), _health(idle_min={"all": 45})
    assert health.sync(tmp_path, idle, gh, NOW) == ["opened idle"]
    assert "box-alarm" in gh.labels  # created when missing
    assert health.sync(tmp_path, idle, gh, NOW + timedelta(minutes=59)) == []  # deduped
    assert health.sync(tmp_path, idle, gh, NOW + timedelta(minutes=61)) == ["commented idle"]
    assert health.sync(tmp_path, idle, gh, NOW + timedelta(minutes=90)) == []  # an hour from the comment
    assert health.sync(tmp_path, _health(), gh, NOW + timedelta(minutes=95)) == ["closed idle"]
    assert gh.verbs() == ["issue create", "issue comment", "issue close"]
    assert health.sync(tmp_path, _health(), gh, NOW + timedelta(hours=3)) == []
    # one issue per kind
    both = _health(idle_min={"all": 45}, disk_free_gb={"/": 1.0})
    assert sorted(health.sync(tmp_path, both, gh, NOW)) == ["opened disk", "opened idle"]


def test_public_copy_has_no_errors():
    pub = health.public(_health(paused={"P3": "secret /home/x"}, preflight={"ok": False, "error": "host a"}))
    text = json.dumps(pub)
    assert "boom" not in text and "/home" not in text and "host a" not in text


def test_idle_minutes():
    def row(m, cpu=1.0, gpu=0.0, run=0):
        return {"ts": NOW - timedelta(minutes=m), "cpu_avg_pct": cpu, "gpu_util_pct": gpu,
                "queue_running": run, "queue_pending": 0}  # fmt: skip

    rows = [row(m) for m in range(40, 0, -1)] + [row(0)]
    rows[0:5] = [row(m, cpu=90) for m in range(40, 35, -1)]
    assert health.idle_minutes(rows, NOW)["all"] == 35.0
    assert health.idle_minutes([row(10, run=1), row(5, run=1), row(0, run=1)], NOW)["all"] == 0.0
    assert health.idle_minutes([row(60)], NOW)["all"] == 0.0  # stale telemetry is not idle


def test_processes_ignore_non_python():
    ps = ("  900 python /x/.venv/bin/twin autopilot --store s\n"
          "   50 python /x/.venv/bin/twin autopilot --store s\n"
          "  10 ssh ssh host twin worker\n"
          "  70 bash echo twin box monitor\n")  # fmt: skip
    p = health.processes(ps)
    assert p["autopilot"] == {"alive": True, "uptime_s": 900}
    assert not p["worker"]["alive"] and not p["telemetry"]["alive"]


def test_collect_and_run_write_health_json(tmp_path):
    jobqueue.add(tmp_path, {"type": "run", "scene": "s"})
    gh = FakeGh()
    h = health.run(tmp_path, gh=gh)
    assert json.loads((tmp_path / "health.json").read_text())["queue"]["pending"] == 1
    assert h["processes"]["worker"]["alive"] in (True, False)


def test_progress_best_and_latest(tmp_path):
    out = tmp_path / "published" / "latest"
    out.mkdir(parents=True)
    m = "align.cross_drive_ground_p95_m"
    trend = [{"built_at": str(i), "verdict": "no-go", "metrics": {m: v}} for i, v in enumerate((4.0, 1.0, 2.0))]
    (out / "trend.json").write_text(json.dumps(trend))
    p = health.progress(tmp_path)["metrics"][m]
    assert (p["latest"], p["best"], p["gate"]) == (2.0, 1.0, "G2")


def test_site_bundle_carries_public_health(tmp_path):
    (tmp_path / "health.json").write_text(json.dumps(_health()))
    src = tmp_path / "areas" / "a1"
    src.mkdir(parents=True)
    import numpy as np

    np.savez(src / "merged.npz", x=np.arange(5.0), y=np.arange(5.0), z=np.arange(5.0), drive=np.zeros(5, "u1"))
    (src / "gates.json").write_text(json.dumps({"run_id": "r", "verdict": "no-go", "gates_version": 2, "gates": {}}))
    site.latest_payload(tmp_path, "areas/a1")
    pub = json.loads((site.latest_dir(tmp_path) / "health.json").read_text())
    assert "boom" not in json.dumps(pub)


def test_cli_health_no_alert(tmp_path, capsys):
    assert main(["health", "--store", str(tmp_path), "--no-alert"]) == 0
    assert (tmp_path / "health.json").is_file()


# --- self-heal (autopilot) -----------------------------------------------------------------
def _failing_p3(store, n_fail, finished):
    for i in range(n_fail):
        jid = jobqueue.add(store, {"type": "run", "scene": "x", "sweep": "s", "tags": ["autopilot"]})
        job = jobqueue.take(store)
        jobqueue.finish(store, job, "ValueError: bad")
        p = Path(store) / "queue" / "failed" / f"{jid}.json"
        d = json.loads(p.read_text())
        d["finished"] = finished
        p.write_text(json.dumps(d))


def test_paused_source_retries_after_6h_then_stays_paused_on_failure(tmp_path, monkeypatch):
    t0 = datetime.now(UTC)
    _failing_p3(tmp_path, 10, t0.isoformat(timespec="seconds"))
    state = {}
    autopilot.fail_streaks(tmp_path, state)
    assert "P3" in state["paused"]
    autopilot.retry_paused(tmp_path, state, t0 + timedelta(hours=5))
    assert "P3" in state["paused"]  # too early
    autopilot.retry_paused(tmp_path, state, t0 + timedelta(hours=6, minutes=1))
    assert "P3" not in state["paused"] and "P3" in state["retrying"]
    autopilot.fail_streaks(tmp_path, state)  # old failures do not count again
    assert "P3" not in state["paused"]
    later = (t0 + timedelta(hours=7)).isoformat(timespec="seconds")
    _failing_p3(tmp_path, 1, later)
    autopilot.retry_paused(tmp_path, state, t0 + timedelta(hours=7))
    assert "P3" in state["paused"] and not state["retrying"]  # failed again: stays paused
    autopilot.retry_paused(tmp_path, state, t0 + timedelta(hours=8))
    assert "P3" in state["paused"]  # next retry is 6 h after the re-pause


def test_retry_that_passes_resumes(tmp_path):
    t0 = datetime.now(UTC) - timedelta(minutes=1)
    state = {"paused": {"P4": "x"}, "paused_at": {"P4": (t0 - timedelta(hours=7)).isoformat()}}
    autopilot.retry_paused(tmp_path, state, t0)
    assert "P4" in state["retrying"]
    jobqueue.add(tmp_path, {"type": "run", "scene": "x", "prefetch": "k", "tags": ["autopilot"]})
    jobqueue.finish(tmp_path, jobqueue.take(tmp_path))
    autopilot.retry_paused(tmp_path, state, t0 + timedelta(minutes=5))
    assert not state["retrying"] and not state["paused"]


# --- supervisor ------------------------------------------------------------------------------
def _wait(pred, secs=20):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


def test_supervisor_restarts_a_killed_process(tmp_path):
    tag = f"fakesvc-{os.getpid()}"
    script = tmp_path / tag  # the process name carries a unique tag, so the pattern is unique
    script.write_text("#!/bin/bash\nexec sleep 300\n")
    script.chmod(0o755)
    conf = tmp_path / "conf"
    conf.write_text(f"fake|{tag[:-1]}[{tag[-1]}]|exec -a {tag} sleep 300|{tmp_path}/fake.log\n")
    env = {**os.environ, "SUP_CONF": str(conf), "SUP_INTERVAL": "1", "SUP_STORE": str(tmp_path), "SUP_HEALTH": ""}
    sup = subprocess.Popen(["bash", str(Path(__file__).parents[1] / "scripts" / "twin-supervisor.sh")], env=env)
    pids = lambda: subprocess.run(["pgrep", "-f", f"{tag[:-1]}[{tag[-1]}]"], capture_output=True, text=True, check=False).stdout.split()
    try:
        assert _wait(lambda: len(pids()) == 1)
        first = pids()
        subprocess.run(["kill", *first], check=True)
        assert _wait(lambda: pids() and pids() != first)
        log = (tmp_path / "supervisor.log").read_text()
        assert log.count("fake was down: restarted") == 2  # first start, then the restart
        assert "fake" in (tmp_path / "supervisor-restarts.log").read_text()
    finally:
        sup.terminate()
        sup.wait()
        subprocess.run(["kill", *pids()], check=False)
