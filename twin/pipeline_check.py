"""End-to-end pipeline checks: `twin pipeline smoke` (CI, fake data) and `twin pipeline preflight` (box, real data).

Both drive the same code the box runs: the file queue, the streaming scheduler, `twin area merge`,
`twin eval`, `site.publish_latest` (dry run) and the autopilot. Only the data differs. Each step is
timed and the first failure stops the run (exit 1).

`check_job` is the contract every queued job must pass: validated exactly as the worker validates it.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from twin import fake_run, gpulease, jobqueue, merge, registry, runner, scheduler, site
from twin import fixtures as fx
from twin.contracts import STAGE_NAMES, STAGES, Params, StageResult
from twin.runrecord import record_path

AREA = "seaport"
FAKE_AREA_HALF_M = (
    100.0  # the fake area polygon: a square this far around the fake origin
)
SMOKE_BUDGET_S = 180
PREFLIGHT_BUDGET_S = 900
PREFLIGHT_STAGES = ("load", "mask", "align", "ground", "features", "accuracy")
PREFLIGHT_DRIVES = 2


def _say(text: str) -> None:
    print(text, flush=True)


class StepFailed(RuntimeError):
    pass


# --- the job contract ---------------------------------------------------------------------
def check_job(store: Path | str, job: dict) -> None:
    """Raise ValueError unless the worker can take this job: the job schema, then the Pipeline and
    Params contracts, the dataset version and the base run (the checks of Scheduler._create)."""
    store = Path(store)
    jobqueue.validate(job)
    kind = job["type"]
    if kind == "run":
        runner._checked(
            job["scene"],
            jobqueue._load(job.get("pipeline")) or {},
            jobqueue._load(job.get("params")) or {},
        )
    elif kind == "rerun":
        runner._rerun_args(
            store, job["run_id"], job["from_stage"], jobqueue._load(job.get("pipeline")),
            jobqueue._load(job.get("params")),
        )  # fmt: skip
    elif kind in ("eval", "publish"):
        if not record_path(store / job["run_id"]).is_file():
            raise ValueError(f"{kind} job: run {job['run_id']} not found in {store}")
        if kind == "publish" and not (store / job["run_id"] / "gates.json").is_file():
            raise ValueError(f"publish job: run {job['run_id']} has no gates.json")


def check_queue(store: Path | str, ids: set[str] | None = None) -> list[dict]:
    """check_job on every pending job (or those in ids). Returns the jobs checked."""
    jobs = [
        j
        for j in jobqueue.list_jobs(store)
        if j["state"] == "pending" and (ids is None or j["id"] in ids)
    ]
    for job in jobs:
        try:
            check_job(store, job)
        except ValueError as exc:
            raise ValueError(
                f"job {job['id']} ({job['type']}, {job.get('sweep') or job.get('prefetch') or '-'}): {exc}"
            ) from exc
    return jobs


# --- fake stages --------------------------------------------------------------------------
def _fake_ctx(token: str, run_id: str):
    names = [s.scene_token for s in fake_run.DRIVE_SPECS]
    index = names.index(token) if token in names else sum(map(ord, token)) % len(names)
    facilities = [f for f in fake_run.FACILITIES if index in f.observed]
    plane = fx.make_plane(seed=index, spacing_m=fake_run.SPACING_M)
    return fake_run._Ctx(
        index=index, run_id=run_id, spec=fake_run.DriveSpec(token, f"Fake {token}"), plane=plane,
        canopy=fx.make_canopy(seed=index + 10, spacing_m=fake_run.SPACING_M),
        wall=fx.make_wall(seed=index + 20, spacing_m=fake_run.SPACING_M),
        facilities=facilities, observed={f.id: f.observed[index] for f in facilities},
        rasters=fake_run._rasters(plane),
    )  # fmt: skip


@contextmanager
def fake_stages():
    """Register fake_run's stage writers as every stage method, for this process and its forks."""
    real_outputs = registry.lookup(
        "outputs", "dxf-pdf"
    )  # fake_run's outputs writer runs the real stage
    saved = dict(registry._REGISTRY)
    registry._REGISTRY.clear()
    cache: dict = {}

    def make(name):
        def run(ctx, params):
            key = ctx.scene_token
            if key not in cache:
                cache[key] = _fake_ctx(key, ctx.run_dir.name)
            metrics = fake_run.WRITERS[name](ctx.stage_dir(name), cache[key])
            return StageResult(
                status="ok", files=list(STAGES[name].outputs), metrics=metrics
            )

        return run

    for name in STAGE_NAMES:
        for method in STAGES[name].methods:
            registry._REGISTRY[(name, method)] = make(name)
    registry._REGISTRY[("outputs", "dxf-pdf")] = real_outputs
    real_lease = (
        gpulease.lease
    )  # the fake colour stage must not unload the box's ollama models

    @contextmanager
    def no_lease(record, *a, **kw):
        yield record

    gpulease.lease = no_lease
    try:
        yield
    finally:
        gpulease.lease = real_lease
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved)


# --- fake area ----------------------------------------------------------------------------
def fake_area(store: Path) -> dict:
    """Area json of the two fake drives, with each drive's merge cache (clip.npy) pre-seeded from the fixtures."""
    e, n, h = fake_run.ORIGIN_E, fake_run.ORIGIN_N, FAKE_AREA_HALF_M
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [e - h, n - h],
                [e + h, n - h],
                [e + h, n + h],
                [e - h, n + h],
                [e - h, n - h],
            ]
        ],
    }
    drives = [
        {"scene": f"fake-{i + 1}", "scene_token": s.scene_token, "date": "2026-11-08", "rain": False, "build_input": True}
        for i, s in enumerate(fake_run.DRIVE_SPECS)
    ]  # fmt: skip
    area = {"name": AREA, "location": "fake", "epsg": 32619, "buffer_m": 0.0, "intersections": [],
            "polygon": polygon, "dataset_version": runner.dataset_version(), "drives": drives}  # fmt: skip
    (store / "areas").mkdir(parents=True, exist_ok=True)
    (store / "areas" / f"{AREA}.json").write_text(json.dumps(area, indent=2))
    for i, d in enumerate(drives):
        plane = fx.make_plane(seed=i, spacing_m=0.5)
        pts = np.column_stack(
            [
                plane[:, 0] + e,
                plane[:, 1] + n,
                plane[:, 2],
                plane[:, 3],
                np.zeros(len(plane)),
            ]
        )
        work = store / "areas" / f"{AREA}-merged" / "drives" / d["scene"]
        work.mkdir(parents=True, exist_ok=True)
        np.save(work / "clip.npy", pts)
        key = merge.build_drive_cache_key({"scene_token": d["scene_token"]}, Params())
        (work / "clip.npy.key").write_text(key)
    return area


def stub_web(root: Path) -> Path:
    """A web folder whose build only copies public/ to out/: publish_latest's staging, health and deploy
    logic run for real, the Next.js build does not (it needs Node and minutes)."""
    web = root / "web"
    (web / "node_modules").mkdir(parents=True, exist_ok=True)
    (web / "public").mkdir(exist_ok=True)
    (web / "package.json").write_text(
        json.dumps(
            {"name": "stub", "scripts": {"build": "rm -rf out && cp -r public out"}}
        )
    )
    return web


# --- shared steps -------------------------------------------------------------------------
def health_snapshot(store: Path) -> dict:
    """The health monitor's pass (twin.health, #200) over this store, without alerts."""
    from twin import health

    return health.run(store, alert=False)


def run_scheduler(store: Path, max_tasks: int | None = None) -> None:
    scheduler.Scheduler(store, max_tasks=max_tasks, hold=lambda: None).run(
        poll=0.2, exit_when_idle=True
    )


def assert_all_done(store: Path, label: str) -> None:
    jobs = jobqueue.list_jobs(store)
    bad = [j for j in jobs if j["state"] != "done"]
    if bad:
        raise StepFailed(f"{label}: {len(bad)} of {len(jobs)} jobs not done: " + "; ".join(
            f"{j['id']} {j['state']} {j.get('error') or ''}"[:200] for j in bad[:5]))  # fmt: skip


def twin_cli(*args: str, env: dict | None = None) -> None:
    proc = subprocess.run([sys.executable, "-m", "twin.cli", *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}, check=False)  # fmt: skip
    if proc.returncode not in (0,):
        raise StepFailed(
            f"twin {' '.join(args[:2])} exited {proc.returncode}: {(proc.stderr or proc.stdout)[-600:]}"
        )


def merge_eval_publish(
    store: Path, web: Path, say: Callable[[str], None], run: Callable
) -> dict:
    """area merge, eval of the merged area, publish_latest (dry run), health snapshot."""
    run("area merge", lambda: twin_cli("area", "merge", AREA, "--store", str(store)))
    merged = f"areas/{AREA}-merged"

    # eval exits 1 on a no-go verdict, which is a result; any other code is a failure
    def evaluate():
        proc = subprocess.run([sys.executable, "-m", "twin.cli", "eval", merged, "--store", str(store)],
                              capture_output=True, text=True, check=False)  # fmt: skip
        if (
            proc.returncode not in (0, 1)
            or not (store / merged / "gates.json").is_file()
        ):
            raise StepFailed(f"eval exited {proc.returncode}: {proc.stderr[-600:]}")

    run("eval", evaluate)

    def publish():
        line = site.publish_latest(store, f"{AREA}-merged", dry_run=True, web=web)
        if (
            not line.startswith("dry run")
            or not (web / "out" / "latest-build" / "scorecard.json").is_file()
        ):
            raise StepFailed(f"publish_latest dry run did not stage the bundle: {line}")
        say(f"    {line}")

    run("publish_latest (dry run)", publish)
    run(
        "health snapshot",
        lambda: say(f"    processes {sorted(health_snapshot(store)['processes'])}"),
    )
    return json.loads((store / merged / "gates.json").read_text())


def _runner(say: Callable[[str], None], budget: int):
    t0 = time.perf_counter()

    def run(name: str, fn: Callable):
        t = time.perf_counter()
        say(f"[{t - t0:6.1f}s] {name} ...")
        try:
            fn()
        except StepFailed:
            raise
        except Exception as exc:
            raise StepFailed(f"{name}: {type(exc).__name__}: {exc}") from exc
        say(
            f"[{time.perf_counter() - t0:6.1f}s] {name} ok ({time.perf_counter() - t:.1f}s)"
        )

    return run, t0


# --- smoke --------------------------------------------------------------------------------
def smoke(work: Path | None = None, say: Callable[[str], None] = _say) -> int:
    """Fake data, two fake drives. Returns 0 when every step passed within SMOKE_BUDGET_S."""
    work = Path(work or tempfile.mkdtemp(prefix="twin-smoke-"))
    store = work / "store"
    store.mkdir(parents=True, exist_ok=True)
    run, t0 = _runner(say, SMOKE_BUDGET_S)
    old_env = {k: os.environ.get(k) for k in ("NUSCENES_VERSION", "TWIN_RUNS")}
    os.environ["TWIN_RUNS"] = str(store)
    logging.disable(logging.WARNING)
    try:
        with fake_stages():
            run("fake area", lambda: fake_area(store))
            ids: set[str] = set()

            def queue():
                for spec in fake_run.DRIVE_SPECS:
                    ids.add(
                        jobqueue.add(
                            store,
                            {"type": "run", "scene": spec.scene_token, "eval": True},
                        )
                    )
                check_queue(store, ids)

            run("queue 2 fake drives", queue)
            run(
                "scheduler (stream, exit when idle)",
                lambda: (run_scheduler(store), assert_all_done(store, "drives")),
            )
            run("contract: runs are complete", lambda: _check_runs(store, 2))
            merge_eval_publish(store, stub_web(work), say, run)
            with fake_sources(work):
                run(
                    "autopilot --once, every source",
                    lambda: _autopilot_pass(store, say),
                )
                run(
                    "scheduler on the autopilot's jobs",
                    lambda: (
                        run_scheduler(store),
                        assert_all_done(store, "autopilot jobs"),
                    ),
                )
    except StepFailed as exc:
        say(f"SMOKE FAILED: {exc}")
        return 1
    finally:
        logging.disable(logging.NOTSET)
        for k, v in old_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    total = time.perf_counter() - t0
    say(f"smoke ok in {total:.1f}s (budget {SMOKE_BUDGET_S}s)")
    if total > SMOKE_BUDGET_S:
        say("SMOKE FAILED: over budget")
        return 1
    return 0


def _check_runs(store: Path, n: int) -> None:
    from twin.runstore import RunStore

    runs = RunStore(store)
    found = runs.runs()
    if len(found) != n:
        raise StepFailed(f"expected {n} runs, found {len(found)}")
    full = {r.id for r in runs.runs(full_chain=True)}
    gated = {r.id for r in runs.runs(with_gates=True)}
    for run in found:
        if run.id not in full:
            raise StepFailed(f"run {run.id}: stages {[(s['name'], s['status']) for s in run.stages]}")
        if run.id not in gated:
            raise StepFailed(f"run {run.id}: no gates.json after eval")


@contextmanager
def fake_sources(work: Path):
    """The autopilot's outside world, faked: GitHub (PR list, statuses, gate), main commit, nuScenes scene list,
    area ranking and disk. The patches hold while the scheduler runs the jobs they produce."""
    from twin import autopilot, prgate

    nusc = work / "nuscenes"
    nusc.mkdir(exist_ok=True)
    scenes = [{"name": f"fake-p4-{i}", "token": f"fake-p4-token-{i}"} for i in range(2)]
    (nusc / "scene.json").write_text(json.dumps(scenes))
    passes = work / "passes.json"
    passes.write_text(json.dumps({"fake/area-x": [s["name"] for s in scenes]}))
    sha = "f" * 40
    patches = {
        (autopilot, "NUSCENES"): nusc,
        (autopilot, "ranked_areas"): lambda *a: json.loads(
            passes.read_text()
        ),  # PASSES_FILE is a default argument
        (autopilot, "ROUND_N"): 2,
        (autopilot, "main_commit"): lambda: sha,
        (autopilot.shutil, "which"): lambda name: "/bin/true",
        (prgate, "open_prs"): lambda repo=None, gh=None: [
            {"pr": 7, "sha": sha, "method": True}
        ],
        (
            prgate,
            "gate",
        ): lambda *a, **k: {},  # a PR gate needs git and GitHub; the job must still flow through
        (prgate, "set_status"): lambda *a, **k: (
            None
        ),  # never post to GitHub from a smoke run
        (prgate, "post_comment"): lambda *a, **k: None,
        (autopilot.telemetry, "free_gb"): lambda path: 1000.0,
    }
    saved = {k: getattr(*k) for k in patches}
    for (obj, name), value in patches.items():
        setattr(obj, name, value)
    try:
        yield
    finally:
        for (obj, name), value in saved.items():
            setattr(obj, name, value)


def _autopilot_pass(store: Path, say) -> None:
    """One `twin autopilot --once` pass with P0, P2, P3 and P4 all producing work."""
    from twin import autopilot

    before = {j["id"] for j in jobqueue.list_jobs(store)}
    say(f"    {autopilot.step(store, ready=0)}")
    # P2 runs detached; wait for its merge + eval to end, as the next passes would
    state = autopilot.load_state(store)
    for _ in range(240):
        code = Path(state["p2"]["exit_file"])
        if code.is_file():
            break
        time.sleep(0.5)
    else:
        raise StepFailed("P2 area merge + eval did not finish")
    if code.read_text().strip() not in ("0", "1"):
        raise StepFailed(
            f"P2 area merge + eval exited {code.read_text().strip()}: see {code.with_suffix('.log')}"
        )
    new = [j for j in jobqueue.list_jobs(store) if j["id"] not in before]
    kinds = {
        (
            "P0"
            if j["type"] == "prgate"
            else "P2"
            if "baseline" in j.get("tags", [])
            else "P3"
            if j.get("sweep")
            else "P4"
            if j.get("prefetch")
            else "?"
        )
        for j in new
    }
    if kinds != {"P0", "P2", "P3", "P4"}:
        raise StepFailed(
            f"the autopilot pass queued {sorted(kinds)}, expected P0, P2 (baseline), P3 and P4 jobs"
        )
    check_queue(store, {j["id"] for j in new if j["type"] != "prgate"})


# --- preflight ----------------------------------------------------------------------------
def _preflight(
    store: Path | None = None,
    work: Path | None = None,
    say: Callable[[str], None] = _say,
) -> int:
    """Real data on the box: 2 seaport drives through load, mask, align, ground, features and accuracy, then
    area merge, eval and publish_latest (dry run). Runs in a scratch folder; never touches the live store.
    Stops on the first failure. Returns 0 when everything passed within PREFLIGHT_BUDGET_S."""
    live = Path(store or runner.default_store())
    work = Path(
        work or tempfile.mkdtemp(prefix="twin-preflight-", dir=os.environ.get("TMPDIR"))
    )
    scratch = work / "store"
    scratch.mkdir(parents=True, exist_ok=True)
    run, t0 = _runner(say, PREFLIGHT_BUDGET_S)
    old_env = {k: os.environ.get(k) for k in ("NUSCENES_VERSION", "TWIN_RUNS")}
    os.environ["TWIN_RUNS"] = str(scratch)
    ids: set[str] = set()
    try:
        area_file = live / "areas" / f"{AREA}.json"
        if not area_file.is_file():
            raise StepFailed(f"no area definition {area_file}")
        area = json.loads(area_file.read_text())
        os.environ["NUSCENES_VERSION"] = area["dataset_version"]
        drives = [d for d in area["drives"] if d.get("build_input")][:PREFLIGHT_DRIVES]
        if len(drives) < PREFLIGHT_DRIVES:
            raise StepFailed(
                f"area {AREA} has fewer than {PREFLIGHT_DRIVES} build-input drives"
            )
        area["drives"] = drives
        (scratch / "areas").mkdir()
        (scratch / "areas" / f"{AREA}.json").write_text(json.dumps(area, indent=2))
        say(
            f"preflight: scenes {[d['scene'] for d in drives]}, dataset {area['dataset_version']}, scratch {work}"
        )
        # a required stage cannot be disabled (Pipeline contract): only optional ones past accuracy are
        pipeline = {
            n: {"method": STAGES[n].methods[0], "enabled": False}
            for n in STAGE_NAMES
            if STAGES[n].optional and n not in PREFLIGHT_STAGES
        }

        def queue():
            for d in drives:
                ids.add(jobqueue.add(scratch, {"type": "run", "scene": d["scene_token"], "stop_after": "accuracy",
                                               "pipeline": pipeline, "eval": False}))  # fmt: skip
            check_queue(scratch, ids)

        run("queue 2 seaport drives", queue)
        run("scheduler: load, mask, align, ground, features, accuracy",
            lambda: (run_scheduler(scratch, max_tasks=2), assert_all_done(scratch, "seaport drives")))  # fmt: skip
        merge_eval_publish(scratch, stub_web(work), say, run)
    except StepFailed as exc:
        say(f"PREFLIGHT FAILED: {exc}")
        return 1
    finally:
        for k, v in old_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    total = time.perf_counter() - t0
    shutil.rmtree(work, ignore_errors=True)
    say(f"preflight ok in {total:.0f}s (budget {PREFLIGHT_BUDGET_S}s)")
    return (
        0
        if total <= PREFLIGHT_BUDGET_S
        else (say("PREFLIGHT FAILED: over budget") or 1)
    )


def preflight(store: Path | None = None, work: Path | None = None, say: Callable[[str], None] = _say) -> int:
    """_preflight, then <store>/health/preflight.json for the health monitor (twin.health raises an alarm on a failure)."""
    last: list[str] = []

    def log(text: str) -> None:
        last.append(text)
        say(text)

    code = _preflight(store, work, log)
    error = next((t for t in reversed(last) if "FAILED" in t), "")
    try:
        path = Path(store or runner.default_store()) / "health" / "preflight.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ok": code == 0, "error": error}) + "\n")
    except OSError as exc:
        say(f"could not write {path}: {exc}")
    return code


def pipeline_command(action: str, store: Path | None, work: Path | None) -> int:
    return smoke(work) if action == "smoke" else preflight(store, work)
