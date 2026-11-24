import json
import subprocess
from datetime import UTC, datetime, timedelta

from twin import autopilot, jobqueue, site
from twin.autopilot import RealWorld
from twin.contracts import Params


class FakeWorld:
    """The autopilot's outside world, faked. Every call is logged in `calls`; the knobs are plain attributes."""

    def __init__(self, **knobs):
        self.calls = []
        self.commit = None  # main on GitHub
        self.gh_installed = True
        self.prs = []  # the `gh pr list` json
        self.diff = ""  # what `gh pr diff --name-only` prints
        self.free = 1000.0  # GB, a number or a function of the path
        self.ranked = {}
        self.tokens = {}  # scene name -> token; None: unreadable
        self.version = "v1.0-trainval"
        self.board = None  # the leaderboard every sweep has
        self.sweep_variants = 2
        self.exit = "1"  # exit code of a finished detached shell
        self.baselines = {}  # scene token -> newest full run folder
        self.changed = lambda old, new: None  # paths changed between two commits
        self.latest_effects = []  # publish_latest: an exception to raise, or None, per call
        self.redeploy_effect = None
        self.started, self.queued, self.published, self.redeployed = [], [], [], []
        self.cap_calls = []
        self.ram = (0.0, 1024.0)
        self.__dict__.update(knobs)

    def asked(self):
        """Which sources a step asked, in order, read off the calls each one makes first."""
        marks = {"has_gh": "P0", "main_commit": "P2", "dataset_version": "P3", "free_gb": "P4"}
        return list(dict.fromkeys(marks[c] for c in self.calls if c in marks))

    # git
    def main_commit(self):
        self.calls.append("main_commit")
        return self.commit

    def head(self):
        return "h" * 40

    def pull(self):
        return True, "Already up to date."

    def changed_files(self, old, new):
        return self.changed(old, new)

    # GitHub
    def has_gh(self):
        self.calls.append("has_gh")
        return self.gh_installed

    def gh(self, *args):
        return self.diff if args[:2] == ("pr", "diff") else json.dumps(self.prs)

    # disk and nuScenes
    def free_gb(self, path):
        self.calls.append("free_gb")
        return self.free(path) if callable(self.free) else self.free

    def ranked_areas(self):
        return self.ranked

    def scene_tokens(self):
        return self.tokens

    # detached shells
    def start(self, store, name, cmd, cap_gb=0.0):
        self.started.append((name, cmd))
        self.cap_calls.append((name, cap_gb))
        return 999999, "x"

    def ram_gb(self):
        return self.ram if not callable(self.ram) else self.ram()

    def alive(self, pid):
        return False

    def exit_code(self, job):
        return self.exit

    # the site
    def publish_latest(self, store, twin):
        self.published.append(("latest", twin))
        effect = self.latest_effects.pop(0) if self.latest_effects else None
        if effect:
            raise effect
        return "ok"

    def publish_run(self, store, twin):
        self.published.append(("run", twin))
        return "published x"

    def redeploy(self, store):
        self.redeployed.append(store)
        if self.redeploy_effect:
            raise self.redeploy_effect
        return "redeployed x"

    # runs and sweeps
    def dataset_version(self):
        self.calls.append("dataset_version")
        return self.version

    def pick_baseline(self, store, scene):
        return self.baselines.get(scene)

    def leaderboard(self, store, sweep_id):
        return self.board

    def queue_sweep(self, store, target, space, extra):
        self.queued.append((target, space))
        folder = store / "sweeps" / "n"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sweep.json").write_text(json.dumps({"variants": list(range(self.sweep_variants))}))
        return "n"


def _pending(store, n):
    """n jobs taken by the scheduler (the active count the autopilot reads)."""
    for _ in range(n):
        jobqueue.add(store, {"type": "run", "scene": "x"})
        jobqueue.take(store)


def _base(store, run_id, version="v1.0-trainval", accuracy="ok", parent=None):
    (store / run_id).mkdir()
    m = {"data": {"nuscenes_version": version}, "stages": [{"name": "accuracy", "status": accuracy}]}
    (store / run_id / "run.json").write_text(json.dumps({**m, "parent": parent}))


def test_low_water_refill(tmp_path):
    world = FakeWorld()
    _pending(tmp_path, autopilot.LOW_WATER)
    autopilot.step(tmp_path, world=world)
    assert world.asked() == ["P0"]  # at the mark: only the cheap P0 poll, no refill
    world.calls.clear()
    jobqueue.finish(tmp_path, jobqueue.list_jobs(tmp_path)[0])  # one below the mark
    out = autopilot.step(tmp_path, world=world)
    assert world.asked() == ["P0", "P2", "P3", "P4"], out


def test_stops_at_target(tmp_path):
    _base(tmp_path, "20261110-000001-aaaaaa")
    world = FakeWorld(sweep_variants=autopilot.TARGET)
    autopilot.step(tmp_path, world=world)
    assert world.asked() == ["P0", "P2", "P3"]  # P3 filled the queue: P4 not asked


def test_source_order_and_tags(tmp_path):
    prs = [{"number": 7, "headRefOid": "a" * 40, "labels": [{"name": "method"}]}]
    world = FakeWorld(prs=prs, diff="twin/stages/ground.py")
    autopilot.step(tmp_path, world=world)
    job = jobqueue.list_jobs(tmp_path)[0]
    assert job["type"] == "prgate" and job["tags"] == ["autopilot"]
    assert jobqueue.priority(job) == 0


def test_p0_skips_without_gh(tmp_path):
    assert autopilot.p0_prgate(tmp_path, {}, FakeWorld(gh_installed=False)) == 0


def test_kill_switch(tmp_path):
    world = FakeWorld()
    (tmp_path / autopilot.PAUSE_FILE).touch()
    assert autopilot.step(tmp_path, world=world) == "paused"
    assert world.calls == [] and jobqueue.list_jobs(tmp_path) == []
    (tmp_path / autopilot.PAUSE_FILE).unlink()
    autopilot.step(tmp_path, world=world)
    assert world.asked()[0] == "P0"


def test_p4_holds_on_low_disk_and_limits(tmp_path):
    names = [f"scene-{i:04d}" for i in range(9)]
    world = FakeWorld(free=5.0, tokens={n: f"t{n}" for n in names})
    assert autopilot.p4_prefetch(tmp_path, {}, world) == 0
    assert jobqueue.list_jobs(tmp_path) == []
    world.free = 300.0
    world.ranked = {"l/a": names, "l/b": names, "l/c": names}
    state = {}
    assert autopilot.p4_prefetch(tmp_path, state, world) == autopilot.PREFETCH_SCENES
    autopilot.p4_prefetch(tmp_path, state, world)
    assert autopilot.p4_prefetch(tmp_path, state, world) == autopilot.PREFETCH_SCENES  # a third area: no cap
    assert autopilot.p4_prefetch(tmp_path, state, world) == 0  # ranking exhausted
    world.free = lambda p: 30.0 if p == "/" else 50.0
    world.ranked = {"l/d": names}
    assert autopilot.p4_prefetch(tmp_path, state, world) == 0  # store filesystem under 100 GB: held
    jobs = jobqueue.list_jobs(tmp_path)
    assert len(jobs) == 3 * autopilot.PREFETCH_SCENES
    assert all(j["priority"] == 4 and j["tags"] == ["autopilot"] for j in jobs)
    assert all(j["stop_after"] == "mask" for j in jobs)


def test_narrow_and_stall(tmp_path):
    rows = [{"overrides": {"ground.tile_m": v, "features.min_points": 20 + i}} for i, v in enumerate((3.0, 4.0))]
    sp = autopilot.narrow(rows)
    assert 2.5 < sp["params"]["ground.tile_m"]["min"] < 3.0 < sp["params"]["ground.tile_m"]["max"]
    board = {"target": "T", "waiting": 0, "rows": [{"verdict": "go", "score": 1.0, "overrides": rows[0]["overrides"]}]}
    world = FakeWorld(board=board)
    _base(tmp_path, "base")
    (tmp_path / "sweeps" / "seed").mkdir(parents=True)
    (tmp_path / "sweeps" / "seed" / "sweep.json").write_text(json.dumps({"target": "base", "variants": []}))
    state = {}
    for _ in range(5):
        autopilot.p3_sweep(tmp_path, state, world)
    # round 1 from the seed, then three flat boards end the line: no 4th round
    assert len(world.queued) == 3 and state["p3"]["stopped"]
    # the stalled line is replaced by a new one (no base run here, so nothing queued yet)
    assert autopilot.p3_sweep(tmp_path, state, world) == 0 and len(world.queued) == 3


def test_cli_once(tmp_path):
    world = FakeWorld(gh_installed=False)
    assert autopilot.autopilot_command(tmp_path, 0, True, world=world) == 0
    assert (tmp_path / "autopilot" / "state.json").is_file()


def test_p3_skips_other_dataset_version(tmp_path):
    world = FakeWorld(version="v1.0-trainval")
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "run.json").write_text(json.dumps({"data": {"nuscenes_version": "v1.0-mini"}}))
    (tmp_path / "sweeps" / "s1").mkdir(parents=True)
    (tmp_path / "sweeps" / "s1" / "sweep.json").write_text(json.dumps({"target": "base", "variants": []}))
    assert autopilot._latest_scored(tmp_path, world) is None
    assert autopilot.p3_sweep(tmp_path, {}, world) == 0


def test_skip_source(tmp_path):
    world = FakeWorld()
    autopilot.step(tmp_path, skip=("P3",), world=world)
    assert world.asked() == ["P0", "P2", "P4"]


def test_stalled_p3_starts_new_line(tmp_path):
    world = FakeWorld(version="v1.0-trainval")
    _base(tmp_path, "20261110-000001-aaaaaa")
    _base(tmp_path, "20261110-000002-bbbbbb")
    _base(tmp_path, "20261110-000003-cccccc", accuracy="failed")  # not dry
    _base(tmp_path, "20261110-000004-dddddd", version="v1.0-mini")
    assert autopilot.base_runs(tmp_path, world) == ["20261110-000001-aaaaaa", "20261110-000002-bbbbbb"]
    state = {"p3": {"sweep": "old", "best": [0, 1.0], "stall": 0, "round": 3, "stopped": True}}
    assert autopilot.p3_sweep(tmp_path, state, world) == 2  # no seed needed after a stalled line
    assert autopilot.p3_sweep(tmp_path, {}, world) == 2  # no board at all: also a new line
    state["p3"]["stopped"] = True
    autopilot.p3_sweep(tmp_path, state, world)
    (t0, sp0), (_, _), (t2, _sp2) = world.queued
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


def test_fail_streak_pauses_source(tmp_path):
    world = FakeWorld()
    _failed(tmp_path, 6, "RuntimeError: GEOS")
    _failed(tmp_path, 4, None)
    autopilot.step(tmp_path, world=world)
    alarm = tmp_path / "autopilot" / "alarm.txt"
    assert "P3 paused" in alarm.read_text() and "GEOS" in alarm.read_text()
    assert "P3" not in world.asked() and "P2" in world.asked()  # only the failing source stops
    alarm.unlink()
    world.calls.clear()
    autopilot.step(tmp_path, world=world)  # alarm cleared: resumes, old failures no longer count
    assert "P3" in world.asked() and not alarm.exists()


def test_mixed_errors_do_not_alarm(tmp_path):
    for i in range(10):
        _failed(tmp_path, 1, f"RuntimeError: e{i}")
    autopilot.step(tmp_path, world=FakeWorld())
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


def test_p2b_reevals_when_gates_change(tmp_path):
    world = FakeWorld(commit="a" * 40)
    state = {"p2": {"built": "a" * 40}, "p2b": {"gates": "old"}}
    autopilot.p2_area(tmp_path, state, world)
    assert [n for n, _ in world.started] == ["p2b"] and state["p2b"]["gates"] == autopilot.gates_hash()
    state["p2b"]["running"] = False
    autopilot.p2_area(tmp_path, state, world)
    assert [n for n, _ in world.started] == ["p2b"]  # gates unchanged since


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


def test_latest_build_published_after_p2_and_p2b_and_failures_do_not_crash(tmp_path):
    # no-go evals (exit 1); the second and third publish fail: the pass must not raise
    world = FakeWorld(exit="1", latest_effects=[None, site.SiteStop("no token"), RuntimeError("boom")])
    autopilot.p2_area(tmp_path, {"p2": {"building": "a" * 40, "pid": 1}}, world)
    autopilot.p2_area(tmp_path, {"p2": {"built": "a" * 40}, "p2b": {"running": True, "gates": autopilot.gates_hash()}}, world)
    autopilot.p2_area(tmp_path, {"p2": {"building": "b" * 40, "pid": 1}}, world)  # SiteStop, then RuntimeError: no raise
    assert [p for p in world.published if p[0] == "latest"] == [("latest", "seaport-twin")] * 3


def test_narrow_stays_inside_contract_range():
    rows = [{"overrides": {"features.cluster_eps_m": v}} for v in (0.05, 0.06)]
    space = autopilot.narrow(rows)["params"]["features.cluster_eps_m"]
    lo, _ = (Params().bounds("features.cluster_eps_m") or (None, None))
    assert space["min"] >= lo


def test_p2_chain_is_merge_then_twin_then_eval_on_the_twin_folder(tmp_path):
    world = FakeWorld(commit="a" * 40)
    autopilot.p2_area(tmp_path, {}, world)
    merge, twin, ev = (c.strip() for c in world.started[0][1].split("&&"))
    assert "area merge seaport" in merge and "area twin seaport" in twin
    assert "eval areas/seaport-twin" in ev


def test_new_main_queues_a_baseline_run_once(tmp_path):
    world = FakeWorld(commit="a" * 40)
    state = {}
    autopilot.p2_area(tmp_path, state, world)
    added = jobqueue.list_jobs(tmp_path)
    assert [(j["scene"], j["eval"], j["tags"]) for j in added] == [(autopilot.prgate.SCENE, True, ["autopilot", "baseline"])]
    state["p2"].update(built="a" * 40, building=None, pid=None)
    autopilot.p2_area(tmp_path, state, world)
    assert len(jobqueue.list_jobs(tmp_path)) == 1  # the same commit is not queued again


def _area(store, scenes):
    """An area definition (scene names -> tokens "tok-<name>") and a twin build that used them."""
    d = store / "areas" / autopilot.TWIN
    d.mkdir(parents=True)
    (d / "drives.json").write_text(json.dumps([{"scene": s} for s in scenes]))
    drives = [{"scene": s, "scene_token": f"tok-{s}"} for s in [*scenes, "unused"]]
    (store / "areas" / f"{autopilot.AREA}.json").write_text(json.dumps({"drives": drives}))


def test_new_main_queues_one_run_per_area_scene_unless_current(tmp_path):
    commit = "a" * 40
    _area(tmp_path, ["scene-1", "scene-2"])
    current = tmp_path / "r-current"
    current.mkdir()
    (current / "run.json").write_text(json.dumps({"code": {"git_sha": commit}}))
    world = FakeWorld(commit=commit, baselines={"tok-scene-2": current})
    autopilot.p2_area(tmp_path, {}, world)
    jobs = [j for j in jobqueue.list_jobs(tmp_path) if "baseline" not in j.get("tags", [])]
    assert [j["scene"] for j in jobs] == ["tok-scene-1"]  # the scene-0757 baseline is the other job


def test_showcase_waits_for_drive_runs_then_publishes_once(tmp_path):
    _area(tmp_path, ["scene-1"])
    jobqueue.add(tmp_path, {"type": "run", "scene": "tok-scene-1"})
    world = FakeWorld(commit="a" * 40, exit="1")
    state = {"p2": {"building": "a" * 40, "built": "a" * 40, "pid": None}, "p2b": {"gates": autopilot.gates_hash()}}
    autopilot.p2_area(tmp_path, state, world)
    assert ("run", autopilot.TWIN) not in world.published and state["p2"]["showcase_pending"]
    for f in (tmp_path / "queue" / "pending").glob("*.json"):
        f.unlink()  # the drive run finished
    autopilot.p2_area(tmp_path, state, world)
    autopilot.p2_area(tmp_path, state, world)
    assert world.published.count(("run", autopilot.TWIN)) == 1 and not state["p2"]["showcase_pending"]


def test_pull_redeploys_only_when_web_changed(tmp_path):
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
    world = FakeWorld(changed=RealWorld(repo).changed_files)  # real git diff, fake site
    autopilot.redeploy_web(tmp_path, base, twin_only, world)
    assert world.redeployed == []  # twin/-only commit: no redeploy
    autopilot.redeploy_web(tmp_path, twin_only, web, world)
    assert world.redeployed == [tmp_path]  # web/ touched: redeployed once
    world.redeploy_effect = site.SiteStop("no token")
    autopilot.redeploy_web(tmp_path, base, web, world)  # failure is logged, not raised
