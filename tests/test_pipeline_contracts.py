"""Contract tests per pipeline step (#199): every job any autopilot tier can emit is generated from
realistic state and validated as the worker validates it (twin.pipeline_check.check_job).

Each test names the bug it guards; reverting the fix makes it fail."""

import json
import random
import shlex
import shutil

import pytest

from twin import autopilot, fake_run, jobqueue, prgate, runner, site
from twin.autopilot import RealWorld
from twin.contracts import Params
from twin.pipeline_check import check_job, check_queue, fake_area, stub_web

TRAINVAL = "v1.0-trainval"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("fake-runs")
    fake_run.write_fake_runs(out, 2)  # slow: written once, copied per test
    return out


@pytest.fixture
def store(built, tmp_path, monkeypatch):
    """A store with two finished fake drives, built from the worker's dataset version."""
    monkeypatch.setenv("NUSCENES_VERSION", "v1.0-mini")  # what fake_run's manifests record
    shutil.copytree(built, tmp_path, dirs_exist_ok=True)
    return tmp_path


class ContractWorld(RealWorld):
    """The real world with the outside effects the contract tests need faked."""

    def __init__(self, commit="c" * 40, ranked=None, tokens=None, board=None, round_n=3):
        super().__init__()
        self.commit, self.ranked, self.tokens, self.board, self.round_n = commit, ranked or {}, tokens, board, round_n
        self.cmds = []

    def main_commit(self):
        return self.commit

    def free_gb(self, path):
        return 1000.0

    def ranked_areas(self):
        return self.ranked

    def scene_tokens(self):
        return self.tokens

    def leaderboard(self, store, sweep_id):
        return self.board if self.board is not None else super().leaderboard(store, sweep_id)

    def queue_sweep(self, store, target, space, extra):
        return super().queue_sweep(store, target, {**space, "n": self.round_n}, extra)

    def start(self, store, name, cmd, cap_gb=0.0):
        self.cmds.append(cmd)
        self.cap_calls = getattr(self, "cap_calls", [])
        self.cap_calls.append((name, cap_gb))
        return 0, str(store / "x.exit")

    def ram_gb(self):
        return (0.0, 1024.0)


def pending(store):
    return [j for j in jobqueue.list_jobs(store) if j["state"] == "pending"]


def test_every_job_type_has_a_check(store):
    run_id = next(p.parent.name for p in store.glob("*/run.json"))
    check_job(store, {"type": "run", "scene": "tok"})
    check_job(store, {"type": "rerun", "run_id": run_id, "from_stage": "ground"})
    check_job(store, {"type": "eval", "run_id": run_id})
    check_job(store, {"type": "prgate", "pr": 3, "sha": "a" * 40})
    with pytest.raises(ValueError):
        check_job(store, {"type": "publish", "run_id": run_id})  # no gates.json yet
    with pytest.raises(ValueError):
        check_job(
            store,
            {
                "type": "rerun",
                "run_id": "20200101-000000-aaaaaa",
                "from_stage": "ground",
            },
        )  # no base run


# --- P0: PR gates -------------------------------------------------------------------------
def test_p0_jobs_are_valid_and_n_a_status_posts_once_per_head(tmp_path, monkeypatch):
    """Bug: prgate spammed statuses (#197). Polling every minute must post n/a once per head commit."""
    posts = []

    def gh(*args):
        if args[:2] == ("pr", "diff"):
            return "twin/stages/load.py"
        if args[0] == "pr":
            prs = [(1, "1" * 40, ["method"]), (2, "2" * 40, [])]
            return json.dumps(
                [
                    {"number": n, "headRefOid": s, "labels": [{"name": x} for x in lab]}
                    for n, s, lab in prs
                ]
            )
        if args[-1] == "--paginate":
            return "[]"
        posts.append(args)
        return ""

    for _ in range(5):  # five autopilot passes
        prgate.poll(tmp_path, gh=gh, extra=autopilot.TAGS)
    assert sum("state=success" in a for a in posts) == 1  # the non-method PR, once
    jobs = pending(tmp_path)
    assert len(jobs) == 1 and jobs[0]["type"] == "prgate"
    check_queue(tmp_path)


# --- P2 / P2b: area rebuild and re-eval ----------------------------------------------------
def test_p2_commands_parse_as_twin_cli(store, monkeypatch):
    from twin.cli import build_parser

    world = ContractWorld()
    cmds = world.cmds
    monkeypatch.setattr(autopilot, "gates_hash", lambda: "g1")
    state: dict = {}
    autopilot.p2_area(store, state, world)  # P2: new main commit
    state["p2"].update(built="c" * 40, building=None, pid=None)
    state["p2b"] = {"gates": "old"}
    autopilot.p2_area(store, state, world)  # P2b: gates changed
    assert len(cmds) == 2
    for cmd in cmds:
        for part in cmd.replace("(", " ").replace(")", " ").split("&&"):
            part = part.split(";")[0]
            argv = shlex.split(part.split("twin.cli", 1)[1])
            assert build_parser().parse_args(argv).command in ("area", "eval")


# --- P3: sweep lines ----------------------------------------------------------------------
def test_p3_new_line_jobs_validate_over_many_seeds(store, monkeypatch):
    world = ContractWorld()
    for seed in range(len(autopilot.GROUPS) * 3):
        state = {"p3_lines": seed}
        before = {j["id"] for j in pending(store)}
        n = autopilot.new_line(store, state, world)
        assert n > 0, f"seed {seed}: no variants queued"
        check_queue(store, {j["id"] for j in pending(store)} - before)


def test_p3_never_reruns_a_base_built_from_another_dataset_version(store, monkeypatch):
    """Bug: P3 reruns hit 'dataset version differs from the parent run's' (8 failed jobs on the box)."""
    monkeypatch.setenv(
        "NUSCENES_VERSION", TRAINVAL
    )  # the worker reads trainval; the runs on disk are mini
    assert autopilot.base_runs(store, RealWorld()) == []
    assert autopilot.new_line(store, {}, RealWorld()) == 0
    assert pending(store) == []
    # a base run of the right version is used, and its jobs pass the worker's checks
    run = next(store.glob("20*/run.json"))
    doc = json.loads(run.read_text())
    doc["data"]["nuscenes_version"] = TRAINVAL
    run.write_text(json.dumps(doc))
    assert autopilot.base_runs(store, RealWorld()) == [run.parent.name]
    assert autopilot.new_line(store, {}, RealWorld()) > 0
    check_queue(store)


def _rows_around(rng, paths, k=5):
    """Leaderboard rows whose overrides sit anywhere in each parameter's contract range, edges included."""
    rows = []
    for _ in range(k):
        o = {}
        for p in paths:
            lo, hi = (Params().bounds(p) or (None, None))
            o[p] = rng.choice([lo, hi, rng.uniform(lo, hi)])
        rows.append(
            {
                "overrides": o,
                "verdict": "no-go",
                "score": rng.random(),
                "run_id": "x",
                "from_stage": "ground",
            }
        )
    return rows


def _bounded_paths():
    return [f"{g}.{n}" for g in autopilot.GROUPS for n, f in type(getattr(Params(), g)).model_fields.items()
            if f.annotation in (int, float) and (Params().bounds(f"{g}.{n}") or (None, None)) != (None, None)]  # fmt: skip


def test_p3_narrowed_space_stays_inside_params_ranges(store, monkeypatch):
    """Bug: P3 narrowed outside the Params ranges (#198): the round failed and the line stalled."""
    paths = _bounded_paths()
    assert len(paths) > 10
    for seed in range(200):
        rng = random.Random(seed)
        picked = rng.sample(paths, 3)
        space = autopilot.narrow(_rows_around(rng, picked))["params"]
        for path, dim in space.items():
            lo, hi = (Params().bounds(path) or (None, None))
            assert (lo is None or dim["min"] >= lo) and (
                hi is None or dim["max"] <= hi
            ), (seed, path, dim)


def test_p3_narrowed_rounds_queue_valid_jobs(store, monkeypatch):
    base = next(p.parent.name for p in store.glob("20*/run.json"))
    paths = _bounded_paths()
    for seed in range(40):
        rng = random.Random(seed)
        rows = _rows_around(rng, rng.sample(paths, 3))
        board = {"target": base, "waiting": 0, "rows": rows}
        world = ContractWorld(board=board)
        state = {"p3": {"sweep": "s", "best": None, "stall": 0, "round": 0}}
        before = {j["id"] for j in pending(store)}
        n = autopilot.p3_sweep(store, state, world)
        assert state["p3"]["stall"] == 0 and n > 0, (
            f"seed {seed}: round refused (stall {state['p3']['stall']})"
        )
        check_queue(store, {j["id"] for j in pending(store)} - before)


# --- P4: prefetch -------------------------------------------------------------------------
def test_p4_jobs_pass_pipeline_validation(store, tmp_path, monkeypatch):
    """Bug: P4 jobs failed Pipeline validation ('stage align is required and cannot be disabled', 12 jobs on the box)."""
    world = ContractWorld(
        ranked={"loc/a": ["s0", "s1", "s2"]},
        tokens={f"s{i}": f"tok{i}" for i in range(3)},
    )
    assert autopilot.p4_prefetch(store, {}, world) == 3
    jobs = pending(store)
    assert {j["stop_after"] for j in jobs} == {"mask"}
    check_queue(store)
    for j in jobs:  # whatever pipeline a P4 job carries must be a valid Pipeline with every required stage on
        runner._checked(j["scene"], jobqueue._load(j.get("pipeline")) or {}, {})


# --- site publish -------------------------------------------------------------------------
def test_publish_job_and_latest_dry_run(store, tmp_path, monkeypatch):
    run_id = next(p.parent.name for p in store.glob("20*/run.json"))
    (store / run_id / "gates.json").write_text(
        json.dumps({"verdict": "go", "gates": {}, "gates_version": 2})
    )
    job = {"type": "publish", "run_id": run_id, "dry_run": True}
    check_job(store, job)
    fake_area(store)
    # the merged cloud of the fake area: publish_latest needs merged.npz and gates.json
    import numpy as np

    merged = store / "areas" / "seaport-merged"
    np.savez(
        merged / "merged.npz",
        x=np.arange(5.0),
        y=np.arange(5.0),
        z=np.zeros(5),
        intensity=np.zeros(5),
        drive=np.zeros(5, "u2"),
    )
    (merged / "gates.json").write_text(
        json.dumps({"run_id": "a", "verdict": "go", "gates_version": 2, "gates": {}})
    )
    web = stub_web(tmp_path)
    assert site.publish_latest(
        store, "seaport-merged", dry_run=True, web=web
    ).startswith("dry run")
    assert (web / "out" / "latest-build" / "scorecard.json").is_file()
