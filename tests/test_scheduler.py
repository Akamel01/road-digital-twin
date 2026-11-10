import contextlib
import hashlib
import json
import os
import time

import pytest

from twin import gpulease, jobqueue, registry, runner, scheduler
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


def test_chain_runs_in_order_and_streams(tmp_path, stubs, monkeypatch):
    stubs(0.05)
    monkeypatch.setattr(scheduler, "DEFAULT_COST", {n: scheduler.Cost(8, 1) for n in STAGE_NAMES})
    for scene in "abc":
        jobqueue.add(tmp_path, {"type": "run", "scene": scene})
    _sched(tmp_path, cores=16)  # two tasks at a time
    done = _done(tmp_path)
    assert set(done) == set("abc")
    for job in done.values():
        manifest = json.loads((tmp_path / job["run_id"] / "manifest.json").read_text())
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
    run_id = next(d.name for d in tmp_path.iterdir() if (d / "manifest.json").exists()
                  and json.loads((d / "manifest.json").read_text())["data"]["scene_token"] == "bad")
    manifest = json.loads((tmp_path / run_id / "manifest.json").read_text())
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
    manifest = runner.Manifest.model_validate_json((begun.ctx.run_dir / "manifest.json").read_text())
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
    assert len(json.loads((begun.ctx.run_dir / "manifest.json").read_text())["stages"]) == len(STAGE_NAMES)


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
    manifest = json.loads((tmp_path / done["a"]["run_id"] / "manifest.json").read_text())
    assert [s["name"] for s in manifest["stages"]] == ["load", "mask"]
