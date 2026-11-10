import json

from twin import autopilot, jobqueue, prgate
from twin.cli import main


def _pending(store, n):
    for _ in range(n):
        jobqueue.add(store, {"type": "run", "scene": "x"})


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
    _pending(tmp_path, 0)
    jobqueue.take(tmp_path)  # one below the mark
    out = autopilot.step(tmp_path)
    assert calls == ["P0", "P2", "P3", "P4"], out


def test_stops_at_target(tmp_path, monkeypatch):
    calls = []
    _fakes(monkeypatch, calls, adds=autopilot.TARGET)
    autopilot.step(tmp_path)
    assert calls == ["P0", "P2"]  # P2 filled the queue: P3 and P4 not asked


def test_source_order_and_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot.shutil, "which", lambda _: "/bin/gh")
    gh = lambda *a: json.dumps([{"number": 7, "headRefOid": "a" * 40, "labels": [{"name": "method"}]}])
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
    monkeypatch.setattr(autopilot.telemetry, "free_gb", lambda p: 30.0)
    monkeypatch.setattr(autopilot, "ranked_areas", lambda: {"l/a": names, "l/b": names, "l/c": names})
    state = {}
    assert autopilot.p4_prefetch(tmp_path, state) == autopilot.PREFETCH_SCENES
    autopilot.p4_prefetch(tmp_path, state)
    assert autopilot.p4_prefetch(tmp_path, state) == 0  # two areas at most
    jobs = jobqueue.list_jobs(tmp_path)
    assert len(jobs) == 2 * autopilot.PREFETCH_SCENES
    assert all(j["priority"] == 4 and j["tags"] == ["autopilot"] for j in jobs)
    enabled = {s for s, v in jobs[0]["pipeline"].items() if v["enabled"]}
    assert enabled == {"load", "mask"}


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


def test_cli_once(tmp_path, monkeypatch):
    monkeypatch.setattr(autopilot, "main_commit", lambda: None)
    monkeypatch.setattr(autopilot.shutil, "which", lambda _: None)
    monkeypatch.setattr(autopilot, "ranked_areas", dict)
    assert main(["autopilot", "--store", str(tmp_path), "--once"]) == 0
    assert (tmp_path / "autopilot" / "state.json").is_file()
