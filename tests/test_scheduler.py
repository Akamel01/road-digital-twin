import contextlib
import hashlib
import json
import multiprocessing
import os
import time

import pytest

from twin import gpulease, jobqueue, memcap, registry, runner, scheduler
from twin.contracts import STAGE_NAMES, STAGES, ManifestStage, Pipeline, StageResult
from twin.parallel import pmap


@pytest.fixture
def stubs(monkeypatch):
    """Fast stages. Each logs start/end to <store>/log; ground exits hard when TWIN_DIE is set."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(jobqueue, "disk_hold", lambda *a: None)

    def install(sleep=0.0):
        for name in STAGE_NAMES:

            def run(ctx, params, name=name):
                log = ctx.run_dir.parent / "log"
                with log.open("a") as f:
                    f.write(f"s {name} {ctx.scene_token} {time.time()}\n")
                if STAGES[name].number > 1:
                    prev = STAGE_NAMES[STAGES[name].number - 2]
                    assert ctx.input_dir(prev)  # the previous stage finished first
                if name == "ground" and os.environ.get("TWIN_DIE") == ctx.scene_token:
                    os._exit(9)
                time.sleep(sleep)
                assert pmap(abs, [-1, -2, -3], 2) == [1, 2, 3]  # a task may fork a pool
                data = hashlib.sha256(f"{ctx.scene_token}{name}".encode()).hexdigest()
                (ctx.stage_dir(name) / "out.txt").write_text(data)
                with log.open("a") as f:
                    f.write(f"e {name} {ctx.scene_token} {time.time()}\n")
                return StageResult(status="ok")

            registry.register(name, STAGES[name].methods[0])(run)

    return install


def _sched(store, **kw):
    kw.setdefault("cores", 8)
    kw.setdefault("gb", 64)
    kw.setdefault("hold", lambda: None)
    kw.setdefault("max_tasks", 8)
    s = scheduler.Scheduler(store, **kw)
    s.run(poll=0.05, exit_when_idle=True)
    return s


def _done(store):
    return {j["scene"]: j for j in jobqueue.list_jobs(store) if j["state"] == "done"}


def _log(store):
    return [line.split() for line in (store / "log").read_text().splitlines()]


@pytest.fixture(autouse=True)
def _inert_memcap_launcher():
    saved_launcher = memcap._LAUNCHER
    saved_warned = memcap._WARNED
    saved_overrides = set(memcap._WARNED_OVERRIDES)
    saved_reader = memcap._WARNED_READER
    memcap.set_launcher(memcap.Launcher(None, None))
    yield
    memcap._LAUNCHER = saved_launcher
    memcap._WARNED = saved_warned
    memcap._WARNED_OVERRIDES = saved_overrides
    memcap._WARNED_READER = saved_reader


def test_chain_runs_in_order_and_streams(tmp_path, stubs, monkeypatch):
    stubs(0.05)
    monkeypatch.setattr(scheduler, "DEFAULT_COST", {n: scheduler.Cost(8, 1) for n in STAGE_NAMES})
    for scene in "abc":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})
    _sched(tmp_path, cores=16)  # two tasks at a time
    done = _done(tmp_path)
    assert set(done) == set("abc")
    for job in done.values():
        manifest = json.loads((tmp_path / job["run_id"] / "run.json").read_text())
        assert [s["name"] for s in manifest["stages"]] == list(STAGE_NAMES)
    # streaming: scene b starts its first stage before scene a ends its last
    first_b = min(float(t) for k, n, sc, t in _log(tmp_path) if k == "s" and sc == "b")
    last_a = max(float(t) for k, n, sc, t in _log(tmp_path) if k == "e" and sc == "a")
    assert first_b < last_a


def test_budget_limits_concurrency(tmp_path, stubs, monkeypatch):
    stubs(0.1)
    monkeypatch.setattr(scheduler, "DEFAULT_COST", {n: scheduler.Cost(2, 1) for n in STAGE_NAMES})
    for scene in "abcde":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})
    s = _sched(tmp_path, cores=4)
    events = sorted((float(t), 1 if k == "s" else -1) for k, n, sc, t in _log(tmp_path))
    level = peak = 0
    for _, d in events:
        level += d
        peak = max(peak, level)
    assert peak == 2  # 4 cores / 2 per task
    assert len(_done(tmp_path)) == 5 and not s.running


def test_priority_beats_age(tmp_path, stubs):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "old"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "urgent", "priority": 0})
    jobqueue.add(tmp_path, {"type": "run", "scene": "new"})
    _sched(tmp_path, max_tasks=1)
    assert [sc for k, n, sc, t in _log(tmp_path) if k == "s" and n == "load"] == ["urgent", "old", "new"]
    assert jobqueue.priority({"type": "prgate"}) == 0
    assert jobqueue.priority({"type": "run", "sweep": "x"}) == 3
    assert jobqueue.priority({"type": "run"}) == 1


def test_gpu_task_reserves_cores(tmp_path, monkeypatch):
    """A GPU task that waits only for cores holds them back from later CPU tasks."""
    costs = {n: scheduler.Cost(1, 1) for n in STAGE_NAMES}
    costs["colour"] = scheduler.Cost(3, 1)
    monkeypatch.setattr(scheduler, "DEFAULT_COST", costs)
    s = scheduler.Scheduler(tmp_path, cores=4, gb=64, hold=lambda: None)
    started = []
    monkeypatch.setattr(s, "_start", lambda t: started.append(t.name))
    gpu = scheduler.Active({"id": "1", "type": "run", "scene": "g"}, tmp_path, Pipeline(), STAGE_NAMES.index("colour"))
    cpu = scheduler.Active({"id": "2", "type": "run", "scene": "c"}, tmp_path, Pipeline(), STAGE_NAMES.index("profile"))
    busy = scheduler.Cost(2, 1)  # something already running on 2 of the 4 cores
    s.active = [gpu, cpu]
    s.running = [scheduler.Running(scheduler.Task(gpu, "x", None, (), busy), None, None, busy)]
    s.admit()
    assert started == []  # profile needs 1 core and 1 is free, but colour's 3 are reserved
    s.running = []
    s.admit()
    assert started == ["colour", "profile"]  # idle box: both start (3 + 1 cores)
    s.release_gpu()


def test_gpu_lease_held_across_gpu_tasks(tmp_path, stubs, monkeypatch):
    """Two colour tasks back to back: one unload at the start, one release at the end."""
    stubs()
    events = []
    monkeypatch.setattr(gpulease, "unload_all", lambda urls, record: events.append("unload"))
    monkeypatch.setattr(gpulease, "free_mib", lambda: None)
    monkeypatch.setattr(gpulease, "endpoints", list)
    real = gpulease.lease

    @contextlib.contextmanager
    def spy(record, *a, **kw):
        with real(record, *a, **kw):
            yield record
        events.append("release")

    monkeypatch.setattr(gpulease, "lease", spy)
    for scene in "ab":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})
    _sched(tmp_path, max_tasks=1)  # one at a time: the colour tasks cannot overlap
    colours = [n for k, n, sc, t in _log(tmp_path) if k == "e" and n == "colour"]
    assert colours == ["colour", "colour"] and len(_done(tmp_path)) == 2
    assert events == ["unload", "release"]
    assert "gpu_lease" in _done(tmp_path)["a"]


def test_dead_task_fails_its_run_only(tmp_path, stubs, monkeypatch):
    stubs()
    monkeypatch.setenv("TWIN_DIE", "bad")
    jobqueue.add(tmp_path, {"type": "run", "scene": "bad"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "good"})
    _sched(tmp_path)
    states = {j["scene"]: j["state"] for j in jobqueue.list_jobs(tmp_path)}
    assert states == {"bad": "failed", "good": "done"}
    run_id = next(d.name for d in tmp_path.iterdir() if (d / "run.json").exists()
                  and json.loads((d / "run.json").read_text())["data"]["scene_token"] == "bad")
    manifest = json.loads((tmp_path / run_id / "run.json").read_text())
    assert [s["status"] for s in manifest["stages"]][-1] == "failed"


def test_restart_resumes_interrupted_run(tmp_path, stubs):
    stubs()
    jid = jobqueue.add(tmp_path, {"type": "run", "scene": "r"})
    job = jobqueue.take(tmp_path)
    args = runner._checked("r", {}, {})
    begun = runner._create_locked(tmp_path, None, "r", *args, None, None, None)
    for i in range(3):
        runner.run_stage_task(begun.ctx.run_dir, i)
    # the worker died inside ground: a running entry and a partial folder are left
    manifest = runner.Manifest.model_validate_json((begun.ctx.run_dir / "run.json").read_text())
    manifest.stages.append(ManifestStage(name="ground", method="ransac-tiles", status="running",
                                         started=manifest.stages[0].started, seconds=0, files=[]))
    runner._write_manifest(begun.ctx.run_dir, manifest)
    (begun.ctx.stage_dir("ground")).mkdir()
    (begun.ctx.stage_dir("ground") / "partial.txt").write_text("x")
    jobqueue._write(jobqueue._dir(tmp_path, "running") / f"{jid}.json", {**job, "new_run": begun.ctx.run_dir.name})
    assert jobqueue.recover(tmp_path) == [jid]
    _sched(tmp_path)
    assert _done(tmp_path)["r"]["run_id"] == begun.ctx.run_dir.name
    assert not (begun.ctx.stage_dir("ground") / "partial.txt").exists()
    assert len(json.loads((begun.ctx.run_dir / "run.json").read_text())["stages"]) == len(STAGE_NAMES)


def test_one_worker_equals_many(tmp_path, stubs):
    stubs(0.02)
    outs = {}
    for tag, n in (("one", 1), ("many", 8)):
        store = tmp_path / tag
        for scene in "abcd":
            jobqueue.add(store, {"type": "run", "scene": scene})
        _sched(store, max_tasks=n)
        outs[tag] = {
            scene: {p.relative_to(store / j["run_id"]).as_posix(): p.read_bytes()
                    for p in (store / j["run_id"]).rglob("out.txt")}
            for scene, j in _done(store).items()
        }
    assert outs["one"] == outs["many"] and len(outs["one"]["a"]) > 5


def test_stop_after_ends_the_run_early(tmp_path, stubs):
    stubs()
    jobqueue.add(tmp_path, {"type": "run", "scene": "a", "stop_after": "mask"})
    _sched(tmp_path)
    done = _done(tmp_path)
    manifest = json.loads((tmp_path / done["a"]["run_id"] / "run.json").read_text())
    assert [s["name"] for s in manifest["stages"]] == ["load", "mask"]


def test_drain_under_constant_load_exits_75(tmp_path, stubs, monkeypatch):
    stubs(0.05)
    monkeypatch.setattr(
        scheduler, "DEFAULT_COST", {n: scheduler.Cost(8, 1) for n in STAGE_NAMES}
    )
    for scene in "abc":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})

    calls = {"n": 0}

    def changed(self):
        calls["n"] += 1
        return None if calls["n"] == 1 else ("old", "new")

    monkeypatch.setattr(scheduler.CodeWatch, "changed", changed)

    exited = {}

    def fake_exit(code):
        exited["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(scheduler.sys, "exit", fake_exit)

    with pytest.raises(SystemExit):
        s = scheduler.Scheduler(
            tmp_path, cores=16, gb=64, hold=lambda: None, max_tasks=8
        )
        s.run(poll=0.05, exit_when_idle=True)
    assert exited.get("code") == 75


def test_drain_timeout_forces_exit_75(tmp_path, stubs, monkeypatch):
    stubs(0.05)
    monkeypatch.setattr(
        scheduler, "DEFAULT_COST", {n: scheduler.Cost(8, 1) for n in STAGE_NAMES}
    )
    for scene in "ab":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})

    calls = {"n": 0}

    def changed(self):
        calls["n"] += 1
        return None if calls["n"] == 1 else ("old", "new")

    monkeypatch.setattr(scheduler.CodeWatch, "changed", changed)
    monkeypatch.setattr(scheduler.Scheduler, "DRAIN_TIMEOUT", 0)

    exited = {}

    def fake_exit(code):
        exited["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(scheduler.sys, "exit", fake_exit)

    with pytest.raises(SystemExit):
        s = scheduler.Scheduler(
            tmp_path, cores=16, gb=64, hold=lambda: None, max_tasks=8
        )
        s.run(poll=0.05, exit_when_idle=True)
    assert exited.get("code") == 75


def test_no_change_normal_admission(tmp_path, stubs, monkeypatch):
    stubs(0.0)
    monkeypatch.setattr(scheduler.CodeWatch, "changed", lambda self: None)
    for scene in "ab":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})
    s = scheduler.Scheduler(tmp_path, cores=16, gb=64, hold=lambda: None, max_tasks=8)
    s.run(poll=0.05, exit_when_idle=True)
    assert set(_done(tmp_path)) == {"a", "b"}



class RecordingLauncher:
    def __init__(self, path):
        self.path = path

    def argv(self, cmd, cap_gb):
        return list(cmd)

    def enter(self, cap_gb, key):
        with open(self.path, "a") as f:
            f.write(f"{cap_gb}\n")
        return True

    def oom_killed(self, key):
        return False

    def cleanup(self, key):
        pass


def test_stage_child_enters_scope_with_stage_cap(tmp_path, monkeypatch):
    rec = tmp_path / "rec.txt"
    rl = RecordingLauncher(rec)
    memcap.set_launcher(rl)
    s = scheduler.Scheduler(tmp_path, cores=4, gb=64, hold=lambda: None, max_tasks=4)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s"})
    job = jobqueue.take(tmp_path)
    a = scheduler.Active(job, None, None, 0)
    s.active.append(a)
    task = scheduler.Task(a, "load", lambda: None, (), scheduler.Cost(1, 1), stage=True)
    s._start(task)
    s.reap(5)
    assert rec.read_text().splitlines() == ["8.0"]


def test_stage_cap_env_override_reaches_the_child(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_MEM_CAP_STAGE_LOAD_GB", "3")
    rec = tmp_path / "rec.txt"
    memcap.set_launcher(RecordingLauncher(rec))
    s = scheduler.Scheduler(tmp_path, cores=4, gb=64, hold=lambda: None, max_tasks=4)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s"})
    job = jobqueue.take(tmp_path)
    a = scheduler.Active(job, None, None, 0)
    s.active.append(a)
    task = scheduler.Task(a, "load", lambda: None, (), scheduler.Cost(1, 1), stage=True)
    s._start(task)
    s.reap(5)
    assert rec.read_text().splitlines() == ["3.0"]


@pytest.mark.parametrize("name", ["eval", "publish", "prgate"])
def test_whole_task_cap_reaches_the_child(tmp_path, monkeypatch, name):
    rec = tmp_path / "rec.txt"
    memcap.set_launcher(RecordingLauncher(rec))
    s = scheduler.Scheduler(tmp_path, cores=4, gb=64, hold=lambda: None, max_tasks=4)
    if name == "prgate":
        jobqueue.add(tmp_path, {"type": "prgate", "pr": "p", "sha": "s"})
    else:
        jobqueue.add(tmp_path, {"type": name, "run_id": "r"})
    job = jobqueue.take(tmp_path)
    a = scheduler.Active(job, None, None, 0)
    s.active.append(a)

    def fn(*a, **k):
        return None

    task = scheduler.Task(a, name, fn, (), scheduler.Cost(1, 1), stage=False)
    s._start(task)
    s.reap(5)
    assert rec.read_text().splitlines() == ["8.0"]


def test_cap_killed_stage_fails_job_oom_cap(tmp_path, stubs, monkeypatch):
    stubs()
    monkeypatch.setenv("TWIN_DIE", "bad")
    monkeypatch.setattr(memcap, "oom_killed", lambda key: True)
    jobqueue.add(tmp_path, {"type": "run", "scene": "bad"})
    jobqueue.add(tmp_path, {"type": "run", "scene": "good"})
    _sched(tmp_path)
    states = {j["scene"]: j["state"] for j in jobqueue.list_jobs(tmp_path)}
    assert states == {"bad": "failed", "good": "done"}
    bad_job = next(j for j in jobqueue.list_jobs(tmp_path) if j["scene"] == "bad")
    assert bad_job.get("error") == "oom-cap"


def test_cap_kill_overrides_a_reported_err(tmp_path, monkeypatch):
    memcap.set_launcher(memcap.Launcher(None, None))
    monkeypatch.setattr(memcap, "oom_killed", lambda key: True)
    s = scheduler.Scheduler(tmp_path, cores=4, gb=64, hold=lambda: None, max_tasks=4)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s"})
    job = jobqueue.take(tmp_path)
    a = scheduler.Active(job, None, None, 0)
    s.active.append(a)

    def boom():
        raise ValueError("boom")

    task = scheduler.Task(a, "load", boom, (), scheduler.Cost(1, 1), stage=False)
    s._start(task)
    s.reap(5)
    failed = [j for j in jobqueue.list_jobs(tmp_path) if j["state"] == "failed"]
    assert failed and failed[0].get("error") == "oom-cap"


def test_reap_tolerates_a_keyless_running(tmp_path, monkeypatch):
    memcap.set_launcher(memcap.Launcher(None, None))
    calls = {"oom": 0, "cleanup": 0}

    def oom(key):
        calls["oom"] += 1
        return False

    def cleanup(key):
        calls["cleanup"] += 1

    monkeypatch.setattr(memcap, "oom_killed", oom)
    monkeypatch.setattr(memcap, "cleanup_scope", cleanup)

    ctx = multiprocessing.get_context("fork")

    def noop():
        pass

    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=noop)
    proc.start()
    child.close()

    jobqueue.add(tmp_path, {"type": "run", "scene": "s"})
    job = jobqueue.take(tmp_path)
    a = scheduler.Active(job, None, None, 0)
    s = scheduler.Scheduler(tmp_path, cores=4, gb=64, hold=lambda: None, max_tasks=4)
    s.active.append(a)
    task = scheduler.Task(a, "load", lambda: None, (), scheduler.Cost(1, 1))
    r = scheduler.Running(task, proc, parent, scheduler.Cost(1, 1))
    s.running.append(r)
    s.reap(5)
    assert calls == {"oom": 0, "cleanup": 0}
