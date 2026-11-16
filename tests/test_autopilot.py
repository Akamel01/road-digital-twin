import json
from datetime import UTC, datetime, timedelta

from twin import autopilot, jobqueue, prgate
from twin.cli import main
from twin.contracts import Params


def _pending(store, n):
    """n jobs taken by the scheduler (the active count the autopilot reads)."""
    for _ in range(n):
        jobqueue.add(store, {"type": "run", "scene": "x"})
        jobqueue.take(store)


def _fakes(monkeypatch, calls, adds=1):
    def make(name):
        def source(store, state):
            calls.append(name)
            return adds

        return source

    monkeypatch.setattr(autopilot, "p0_prgate", make("P0"))
    monkeypatch.setattr(autopilot, "SOURCES", tuple((n, make(n)) for n in ("P2", "P3", "P4")))


def test_low_water_refill(tmp_path, monkeypatch):
    calls = []
    _fakes(monkeypatch, calls, adds=1)
    _pending(tmp_path, autopilot.LOW_WATER)
    autopilot.step(tmp_path)
    assert calls == ["P0"]  # at the mark: only the cheap P0 poll, no refill
    calls.clear()
    jobqueue.finish(tmp_path, jobqueue.list_jobs(tmp_path)[0])  # one below the mark
    out = autopilot.step(tmp_path)
    assert calls == ["P0", "P2", "P3", "P4"], out


def test_stops_at_target(tmp_path, monkeypatch):
    calls = []
    _fakes(monkeypatch, calls, adds=autopilot.TARGET)
    autopilot.step(tmp_path)
    assert calls == ["P0", "P2"]  # P2 filled the queue: P3 and P4 not asked


def test_source_order_and_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot.shutil, "which", lambda _: "/bin/gh")
    prs = json.dumps([{"number": 7, "headRefOid": "a" * 40, "labels": [{"name": "method"}]}])
    gh = lambda *a: "twin/stages/ground.py" if a[:2] == ("pr", "diff") else prs
    real = prgate.poll
    monkeypatch.setattr(prgate, "poll", lambda store, extra=None: real(store, gh=gh, extra=extra))
    monkeypatch.setattr(autopilot, "main_commit", lambda: None)
    monkeypatch.setattr(autopilot, "ranked_areas", dict)
    autopilot.step(tmp_path)
    job = jobqueue.list_jobs(tmp_path)[0]
    assert job["type"] == "prgate" and job["tags"] == ["autopilot"]
    assert jobqueue.priority(job) == 0


def test_p0_skips_without_gh(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot.shutil, "which", lambda _: None)
    assert autopilot.p0_prgate(tmp_path, {}) == 0


def test_kill_switch(tmp_path, monkeypatch):
    calls = []
    _fakes(monkeypatch, calls)
    (tmp_path / autopilot.PAUSE_FILE).touch()
    assert autopilot.step(tmp_path) == "paused"
    assert calls == [] and jobqueue.list_jobs(tmp_path) == []
    (tmp_path / autopilot.PAUSE_FILE).unlink()
    autopilot.step(tmp_path)
    assert calls[0] == "P0"


def test_p4_holds_on_low_disk_and_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot.telemetry, "free_gb", lambda p: 5.0)
    assert autopilot.p4_prefetch(tmp_path, {}) == 0
    assert jobqueue.list_jobs(tmp_path) == []
    nus = tmp_path / "nus"
    nus.mkdir()
    names = [f"scene-{i:04d}" for i in range(9)]
    (nus / "scene.json").write_text(json.dumps([{"name": n, "token": f"t{n}"} for n in names]))
    monkeypatch.setattr(autopilot, "NUSCENES", nus)
    monkeypatch.setattr(autopilot.telemetry, "free_gb", lambda p: 300.0)
    monkeypatch.setattr(autopilot, "ranked_areas", lambda: {"l/a": names, "l/b": names, "l/c": names})
    state = {}
    assert autopilot.p4_prefetch(tmp_path, state) == autopilot.PREFETCH_SCENES
    autopilot.p4_prefetch(tmp_path, state)
    assert autopilot.p4_prefetch(tmp_path, state) == autopilot.PREFETCH_SCENES  # a third area: no cap
    assert autopilot.p4_prefetch(tmp_path, state) == 0  # ranking exhausted
    monkeypatch.setattr(autopilot.telemetry, "free_gb", lambda p: 30.0 if p == "/" else 50.0)
    monkeypatch.setattr(autopilot, "ranked_areas", lambda: {"l/d": names})
    assert autopilot.p4_prefetch(tmp_path, state) == 0  # store filesystem under 100 GB: held
    jobs = jobqueue.list_jobs(tmp_path)
    assert len(jobs) == 3 * autopilot.PREFETCH_SCENES
    assert all(j["priority"] == 4 and j["tags"] == ["autopilot"] for j in jobs)
    assert all(j["stop_after"] == "mask" for j in jobs)


def test_narrow_and_stall(tmp_path, monkeypatch):
    rows = [{"overrides": {"ground.tile_m": v, "features.min_points": 20 + i}} for i, v in enumerate((3.0, 4.0))]
    sp = autopilot.narrow(rows)
    assert 2.5 < sp["params"]["ground.tile_m"]["min"] < 3.0 < sp["params"]["ground.tile_m"]["max"]
    boards = iter([
        {"target": "T", "waiting": 0, "rows": [{"verdict": "go", "score": 1.0, "overrides": rows[0]["overrides"]}]},
    ] * 4)
    monkeypatch.setattr(autopilot, "_board", lambda s, i: next(boards))
    monkeypatch.setattr(autopilot, "_latest_scored", lambda s: "seed")
    queued = []
    monkeypatch.setattr(autopilot.sweep, "queue_sweep", lambda s, t, sp, extra: queued.append(sp) or "n")
    monkeypatch.setattr(autopilot.json, "loads", lambda t, real=json.loads: {"variants": [1, 2]} if t == "V" else real(t))
    (tmp_path / "sweeps" / "n").mkdir(parents=True)
    (tmp_path / "sweeps" / "n" / "sweep.json").write_text("V")
    state = {}
    for _ in range(5):
        autopilot.p3_sweep(tmp_path, state)
    # round 1 from the seed, then three flat boards end the line: no 4th round
    assert len(queued) == 3 and state["p3"]["stopped"]
    # the stalled line is replaced by a new one (no base run here, so nothing queued yet)
    assert autopilot.p3_sweep(tmp_path, state) == 0 and len(queued) == 3


def test_cli_once(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "main_commit", lambda: None)
    monkeypatch.setattr(autopilot.shutil, "which", lambda _: None)
    monkeypatch.setattr(autopilot, "ranked_areas", dict)
    assert main(["autopilot", "--store", str(tmp_path), "--once"]) == 0
    assert (tmp_path / "autopilot" / "state.json").is_file()


def test_p3_skips_other_dataset_version(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "dataset_version", lambda: "v1.0-trainval")
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "manifest.json").write_text(json.dumps({"data": {"nuscenes_version": "v1.0-mini"}}))
    (tmp_path / "sweeps" / "s1").mkdir(parents=True)
    (tmp_path / "sweeps" / "s1" / "sweep.json").write_text(json.dumps({"target": "base", "variants": []}))
    assert autopilot._latest_scored(tmp_path) is None
    assert autopilot.p3_sweep(tmp_path, {}) == 0


def test_skip_source(tmp_path, monkeypatch):
    calls = []
    _fakes(monkeypatch, calls)
    autopilot.step(tmp_path, skip=("P3",))
    assert calls == ["P0", "P2", "P4"]


def _base(store, run_id, version="v1.0-trainval", accuracy="ok", parent=None):
    (store / run_id).mkdir()
    m = {"data": {"nuscenes_version": version}, "stages": [{"name": "accuracy", "status": accuracy}]}
    (store / run_id / "manifest.json").write_text(json.dumps({**m, "parent": parent}))


def test_stalled_p3_starts_new_line(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "dataset_version", lambda: "v1.0-trainval")
    _base(tmp_path, "20261110-000001-aaaaaa")
    _base(tmp_path, "20261110-000002-bbbbbb")
    _base(tmp_path, "20261110-000003-cccccc", accuracy="failed")  # not dry
    _base(tmp_path, "20261110-000004-dddddd", version="v1.0-mini")
    assert autopilot.base_runs(tmp_path) == ["20261110-000001-aaaaaa", "20261110-000002-bbbbbb"]
    monkeypatch.setattr(autopilot.sweep, "queue_sweep", lambda s, t, sp, extra: seen.append((t, sp)) or "n")
    monkeypatch.setattr(autopilot.json, "loads", lambda t, real=json.loads: {"variants": [1, 2]} if t == "V" else real(t))
    (tmp_path / "sweeps" / "n").mkdir(parents=True)
    (tmp_path / "sweeps" / "n" / "sweep.json").write_text("V")
    seen = []
    state = {"p3": {"sweep": "old", "best": [0, 1.0], "stall": 0, "round": 3, "stopped": True}}
    assert autopilot.p3_sweep(tmp_path, state) == 2  # no seed needed after a stalled line
    assert autopilot.p3_sweep(tmp_path, {}) == 2  # no board at all: also a new line
    state["p3"]["stopped"] = True
    autopilot.p3_sweep(tmp_path, state)
    (t0, sp0), (_, _), (t2, _sp2) = seen
    assert t0 != t2  # the base run rotates
    assert {k.split(".")[0] for k in sp0["params"]} == {"ground"}
    assert state["p3"]["sweep"] == "n" and state["p3"]["stall"] == 0


def test_group_space_uses_contract_ranges():
    for g in autopilot.GROUPS:
        sp = autopilot.group_space(g, 0)
        assert sp["params"] and all(k.startswith(g + ".") for k in sp["params"])
        assert all(v["min"] < v["max"] for v in sp["params"].values())


def _failed(store, n, error, sweep_id="s", tags=("autopilot",)):
    for _ in range(n):
        jobqueue.add(store, {"type": "run", "scene": "x", "sweep": sweep_id, "tags": list(tags)})
        jobqueue.finish(store, jobqueue.take(store), error)


def test_fail_streak_pauses_source(tmp_path, monkeypatch):
    calls = []
    _fakes(monkeypatch, calls)
    _failed(tmp_path, 6, "RuntimeError: GEOS")
    _failed(tmp_path, 4, None)
    autopilot.step(tmp_path)
    alarm = tmp_path / "autopilot" / "alarm.txt"
    assert "P3 paused" in alarm.read_text() and "GEOS" in alarm.read_text()
    assert "P3" not in calls and "P2" in calls  # only the failing source stops
    alarm.unlink()
    calls.clear()
    autopilot.step(tmp_path)  # alarm cleared: resumes, old failures no longer count
    assert "P3" in calls and not alarm.exists()


def test_mixed_errors_do_not_alarm(tmp_path, monkeypatch):
    _fakes(monkeypatch, [])
    for i in range(10):
        _failed(tmp_path, 1, f"RuntimeError: e{i}")
    autopilot.step(tmp_path)
    assert not (tmp_path / "autopilot" / "alarm.txt").exists()


def test_idle_alarm(tmp_path, capsys):
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

    def write(cpu, gpu, running=0):
        rows = ["ts,cpu_avg_pct,gpu_util_pct,queue_running,queue_pending"]
        for m in range(31):
            ts = (now - timedelta(minutes=30 - m)).isoformat(timespec="seconds")
            rows.append(f"{ts},{cpu},{gpu},{running},0")
        (tmp_path / "telemetry").mkdir(exist_ok=True)
        (tmp_path / "telemetry" / "2026-11-10.csv").write_text("\n".join(rows) + "\n")

    write(10, 0, running=1)
    assert not autopilot.idle_alarm(tmp_path, {}, now)  # busy queue
    write(60, 0)
    assert not autopilot.idle_alarm(tmp_path, {}, now)  # CPU busy
    write(10, 0)
    state = {}
    assert autopilot.idle_alarm(tmp_path, state, now)
    assert "ALARM idle" in capsys.readouterr().out
    assert not autopilot.idle_alarm(tmp_path, state, now)  # once per window


def test_p2b_reevals_when_gates_change(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "main_commit", lambda: "a" * 40)
    ran = []
    monkeypatch.setattr(autopilot, "_detached", lambda s, name, cmd: ran.append(name) or (999999, "x"))
    monkeypatch.setattr(autopilot, "_alive", lambda pid: False)
    state = {"p2": {"built": "a" * 40}, "p2b": {"gates": "old"}}
    autopilot.p2_area(tmp_path, state)
    assert ran == ["p2b"] and state["p2b"]["gates"] == autopilot.gates_hash()
    state["p2b"]["running"] = False
    autopilot.p2_area(tmp_path, state)
    assert ran == ["p2b"]  # gates unchanged since


def test_g2_history_and_ratchet(tmp_path, capsys):
    out = tmp_path / "areas" / "seaport-twin"
    out.mkdir(parents=True)

    def build(run_id, value, threshold=0.20):
        status = "go" if value <= threshold else "no-go"
        rep = {"run_id": run_id, "gates": {"G2": {"checks": [{"metric": "align.cross_drive_ground_p95_m", "op": "<=", "value": value, "threshold": threshold, "status": status}]}}}
        (out / "gates.json").write_text(json.dumps(rep))
        autopilot.record_g2(tmp_path)

    build("20261110-000001-aaaaaa", 0.15)
    build("20261110-000001-aaaaaa", 0.15)  # same build re-evaluated: one entry
    build("20261110-000002-bbbbbb", 0.30)  # fails: the streak restarts
    build("20261110-000003-cccccc", 0.12)
    build("20261110-000004-dddddd", 0.11)
    assert "ratchet" not in capsys.readouterr().out
    build("20261110-000005-eeeeee", 0.10)
    assert "G2 ratchet due: lower to 0.1" in capsys.readouterr().out
    history = json.loads((tmp_path / "autopilot" / "g2_history.json").read_text())
    assert len(history) == 5 and history[-1]["status"] == "go"


def test_latest_build_published_after_p2_and_p2b_and_failures_do_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "main_commit", lambda: None)
    monkeypatch.setattr(autopilot, "_alive", lambda pid: False)
    monkeypatch.setattr(autopilot, "_exit_code", lambda job: "1")  # a no-go eval
    for hook in ("leave_one_drive_out", "rain_test", "record_g2"):
        monkeypatch.setattr(autopilot, hook, lambda *a: 0)
    calls = []

    def fake(store, area, dry_run=False):
        calls.append(area)
        if len(calls) == 2:
            raise autopilot.site.SiteStop("no token")
        if len(calls) == 3:
            raise RuntimeError("boom")
        return "ok"

    monkeypatch.setattr(autopilot.site, "publish_latest", fake)
    autopilot.p2_area(tmp_path, {"p2": {"building": "a" * 40, "pid": 1}})
    autopilot.p2_area(tmp_path, {"p2": {"built": "a" * 40}, "p2b": {"running": True, "gates": autopilot.gates_hash()}})
    autopilot.p2_area(tmp_path, {"p2": {"building": "b" * 40, "pid": 1}})  # SiteStop, then RuntimeError: no raise
    assert calls == ["seaport-twin"] * 3


def test_narrow_stays_inside_contract_range():
    rows = [{"overrides": {"features.cluster_eps_m": v}} for v in (0.05, 0.06)]
    space = autopilot.narrow(rows)["params"]["features.cluster_eps_m"]
    lo, _ = (Params().bounds("features.cluster_eps_m") or (None, None))
    assert space["min"] >= lo


def test_p2_chain_is_merge_then_twin_then_eval_on_the_twin_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "main_commit", lambda: "a" * 40)
    monkeypatch.setattr(autopilot, "_alive", lambda pid: False)
    cmds = []
    monkeypatch.setattr(autopilot, "_detached", lambda s, name, cmd: cmds.append(cmd) or (999999, "x"))
    autopilot.p2_area(tmp_path, {})
    merge, twin, ev = (c.strip() for c in cmds[0].split("&&"))
    assert "area merge seaport" in merge and "area twin seaport" in twin
    assert "eval areas/seaport-twin" in ev


def test_new_main_queues_a_baseline_run_once(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "main_commit", lambda: "a" * 40)
    monkeypatch.setattr(autopilot, "_alive", lambda pid: False)
    monkeypatch.setattr(autopilot, "_detached", lambda s, name, cmd: (999999, "x"))
    added = []
    monkeypatch.setattr(autopilot.jobqueue, "add", lambda store, job: added.append(job) or "id")
    state = {}
    autopilot.p2_area(tmp_path, state)
    assert added == [{"type": "run", "scene": autopilot.prgate.SCENE, "eval": True, "tags": ["autopilot", "baseline"]}]
    state["p2"].update(built="a" * 40, building=None, pid=None)
    monkeypatch.setattr(autopilot, "_exit_code", lambda job: "1")
    autopilot.p2_area(tmp_path, state)
    assert len(added) == 1  # the same commit is not queued again


def _area(store, scenes):
    """An area definition (scene names -> tokens "tok-<name>") and a twin build that used them."""
    d = store / "areas" / autopilot.TWIN
    d.mkdir(parents=True)
    (d / "drives.json").write_text(json.dumps([{"scene": s} for s in scenes]))
    drives = [{"scene": s, "scene_token": f"tok-{s}"} for s in [*scenes, "unused"]]
    (store / "areas" / f"{autopilot.AREA}.json").write_text(json.dumps({"drives": drives}))


def test_new_main_queues_one_run_per_area_scene_unless_current(tmp_path, monkeypatch):
    commit = "a" * 40
    _area(tmp_path, ["scene-1", "scene-2"])
    current = tmp_path / "r-current"
    current.mkdir()
    (current / "manifest.json").write_text(json.dumps({"code": {"git_sha": commit}}))
    monkeypatch.setattr(autopilot.prgate, "pick_baseline", lambda store, scene: current if scene == "tok-scene-2" else None)
    monkeypatch.setattr(autopilot, "main_commit", lambda: commit)
    monkeypatch.setattr(autopilot, "_alive", lambda pid: False)
    monkeypatch.setattr(autopilot, "_detached", lambda s, name, cmd: (999999, "x"))
    added = []
    monkeypatch.setattr(autopilot.jobqueue, "add", lambda store, job: added.append(job) or "id")
    autopilot.p2_area(tmp_path, {})
    assert [j["scene"] for j in added[1:]] == ["tok-scene-1"]  # added[0] is the scene-0757 baseline


def test_showcase_waits_for_drive_runs_then_publishes_once(tmp_path, monkeypatch):
    _area(tmp_path, ["scene-1"])
    published = []
    monkeypatch.setattr(autopilot.site, "publish_run", lambda store, twin: published.append(twin) or "published x")
    jobqueue.add(tmp_path, {"type": "run", "scene": "tok-scene-1"})
    monkeypatch.setattr(autopilot, "main_commit", lambda: "a" * 40)
    monkeypatch.setattr(autopilot, "_alive", lambda pid: False)
    monkeypatch.setattr(autopilot, "_exit_code", lambda job: "1")
    monkeypatch.setattr(autopilot, "publish_latest", lambda store: None)
    monkeypatch.setattr(autopilot, "_detached", lambda s, name, cmd: (999999, "x"))
    state = {"p2": {"building": "a" * 40, "built": "a" * 40, "pid": None}, "p2b": {"gates": autopilot.gates_hash()}}
    autopilot.p2_area(tmp_path, state)
    assert published == [] and state["p2"]["showcase_pending"]
    for f in (tmp_path / "queue" / "pending").glob("*.json"):
        f.unlink()  # the drive run finished
    autopilot.p2_area(tmp_path, state)
    autopilot.p2_area(tmp_path, state)
    assert published == [autopilot.TWIN] and not state["p2"]["showcase_pending"]


def test_pull_redeploys_only_when_web_changed(tmp_path, monkeypatch):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True).stdout.strip()  # fmt: skip
    git("init", "-q")
    for path in ("web/page.ts", "twin/code.py"):
        (repo / path).parent.mkdir(exist_ok=True)
        (repo / path).write_text("1\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (repo / "twin" / "code.py").write_text("2\n")
    git("commit", "-qam", "twin only")
    twin_only = git("rev-parse", "HEAD")
    (repo / "web" / "page.ts").write_text("2\n")
    git("commit", "-qam", "web")
    web = git("rev-parse", "HEAD")
    monkeypatch.setattr(autopilot, "REPO_ROOT", repo)
    calls = []
    monkeypatch.setattr(autopilot.site, "redeploy", lambda store, *a, **k: calls.append(store) or "redeployed x")
    autopilot.redeploy_web(tmp_path, base, twin_only)
    assert calls == []  # twin/-only commit: no redeploy
    autopilot.redeploy_web(tmp_path, twin_only, web)
    assert calls == [tmp_path]  # web/ touched: redeployed once
    monkeypatch.setattr(autopilot.site, "redeploy", lambda *a, **k: (_ for _ in ()).throw(autopilot.site.SiteStop("no token")))
    autopilot.redeploy_web(tmp_path, base, web)  # failure is logged, not raised
