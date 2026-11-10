"""Streaming scheduler: stage tasks of many runs through CPU, RAM and GPU budgets.

One process reads the file queue (twin.jobqueue) and holds the active jobs. The unit of work is
one stage of one run, run in a forked child that reads and writes the run folder (its manifest is
the state, so a crash loses nothing). A run is a chain: stage k+1 is ready the moment stage k ends.
Results equal the serial runner's: the child runs the same runner._run_step.
"""

import copy
import json
import multiprocessing
import os
import resource
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any, NamedTuple

from filelock import FileLock, Timeout

from twin import gpulease, jobqueue, runner
from twin.contracts import STAGE_NAMES, Pipeline
from twin.gpulease import GPU_STAGES

RESERVE_CORES = 2  # left for the box itself
RESERVE_GB = 8  # left for Librarian
MARGIN = 1.2  # observed peak RSS is padded by this before it is used as the estimate
COST_FILE = "cost.json"  # <store>/queue/: observed peak GB per task name


class Cost(NamedTuple):
    cores: int
    gb: float
    gpu: bool = False


# Starting guesses; replaced by the observed peak RSS (gb) as tasks finish.
# ponytail: cores are fixed per stage. Refine from manifest seconds if the guesses mis-pack.
DEFAULT_COST: dict[str, Cost] = {
    "load": Cost(8, 6),
    "mask": Cost(8, 4),
    "align": Cost(2, 6),
    "ground": Cost(4, 6),
    "features": Cost(2, 3),
    "colour": Cost(2, 6),
    "profile": Cost(1, 1),
    "isd": Cost(1, 2),
    "accuracy": Cost(1, 2),
    "outputs": Cost(1, 2),
    "eval": Cost(4, 4),
    "publish": Cost(1, 2),
    "prgate": Cost(4, 8),
}
FREE = Cost(0, 0)  # a skipped stage costs nothing


def mem_total_gb() -> float:
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3


def budgets() -> tuple[int, float]:
    """(cores, GB) the scheduler may hand out."""
    return max(1, (os.cpu_count() or 1) - RESERVE_CORES), max(1.0, mem_total_gb() - RESERVE_GB)


def _peak_gb() -> float:
    rss = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return rss / (1024**3 if sys.platform == "darwin" else 1024**2)


def _child(conn, fn: Callable, args: tuple) -> None:
    """Run one task. Sends (status, result or message, peak GB)."""
    try:
        msg: tuple = ("ok", fn(*args))
    except BaseException as exc:  # noqa: BLE001 - reported to the scheduler, which fails the job
        msg = ("err", f"{type(exc).__name__}: {exc}")
    conn.send((*msg, _peak_gb()))


def _create_run(store: Path, job: dict) -> tuple[str, int]:
    """Check the job, make its run folder, link a re-run's parent stages. Returns (folder, first stage)."""
    if job["type"] == "run":
        args = (store, job["scene"], *runner._checked(
            job["scene"], jobqueue._load(job.get("pipeline")) or {},
            jobqueue._load(job.get("params")) or {}), None, None, None)
    else:
        args = runner._rerun_args(store, job["run_id"], job["from_stage"],
                                  jobqueue._load(job.get("pipeline")),
                                  jobqueue._load(job.get("params")))
    begun = runner._create_locked(args[0], None, *args[1:])
    return str(begun.ctx.run_dir), runner.prepare_run(begun)


@dataclass
class Task:
    job: "Active"
    name: str  # a stage name, or eval/publish/prgate for non-stage tasks
    fn: Callable
    args: tuple
    cost: Cost
    lock: str | None = None  # named lock: at most one running task holds it
    stage: bool = False

    @property
    def key(self) -> tuple:
        return (jobqueue.priority(self.job.job), self.job.job["id"])


@dataclass
class Active:
    job: dict
    run_dir: Path | None = None
    pipeline: Pipeline | None = None
    next: int = 0
    phase: str = "stages"  # stages, post, whole
    busy: bool = False
    checked: bool = False  # the finished run's stages were checked for a failure
    extra: dict = field(default_factory=dict)


@dataclass
class Running:
    task: Task
    proc: Any
    conn: Any
    cost: Cost


class Scheduler:
    def __init__(self, store, max_tasks: int | None = None, max_active: int = 24,
                 hold=jobqueue.disk_hold, cores: int | None = None, gb: float | None = None):
        self.store = Path(store)
        bc, bg = budgets()
        self.cores, self.gb = cores or bc, gb or bg
        self.max_tasks, self.max_active, self.hold = max_tasks or 10**6, max_active, hold
        self.active: list[Active] = []
        self.running: list[Running] = []
        self.ctx = multiprocessing.get_context("fork")
        self.observed: dict[str, float] = {}
        path = jobqueue._dir(self.store, "pending").parent / COST_FILE
        self.cost_path = path
        if path.is_file():
            self.observed = json.loads(path.read_text())
        self.log: list[str] = []
        self.gpu_record: dict = {}
        self._lease = None

    # --- costs -------------------------------------------------------------------------
    def cost(self, name: str, enabled: bool = True) -> Cost:
        if not enabled:
            return FREE
        base = DEFAULT_COST.get(name, Cost(1, 2))
        gb = self.observed[name] * MARGIN if name in self.observed else base.gb
        return Cost(min(base.cores, self.cores), min(gb, self.gb), name in GPU_STAGES)

    # --- jobs in -----------------------------------------------------------------------
    def _say(self, text: str) -> None:
        self.log.append(text)
        print(text, flush=True)

    def fill(self) -> None:
        """Take pending jobs (best priority first) while there is room and the disk allows."""
        while len(self.active) < self.max_active:
            if any(jobqueue._dir(self.store, "pending").iterdir()) and (reason := self.hold()):
                self._say(f"held: {reason}")
                return
            job = jobqueue.take(self.store)
            if job is None:
                return
            try:
                self.active.append(self._prepare(job))
            except (runner.LowDisk, runner.RunBusy) as exc:
                jobqueue.release(self.store, job)
                self._say(f"held {job['id']}: {exc}")
                return
            except Exception as exc:  # noqa: BLE001 - a bad job fails itself only
                self._finish(job, f"{type(exc).__name__}: {exc}")

    def _prepare(self, job: dict) -> Active:
        kind = job["type"]
        if kind == "prgate":
            return Active(job, phase="whole")
        if kind in ("eval", "publish"):
            return Active(job, phase="post")
        if new := job.get("new_run"):  # restart: the run folder exists, carry on
            run_dir = self.store / new
            a = Active(job, run_dir, self._pipeline(run_dir), runner.resume_run(run_dir))
        else:
            a = self._create(job)
            jobqueue._write(jobqueue._dir(self.store, "running") / f"{job['id']}.json",
                            {**job, "new_run": a.run_dir.name})
        if runner.run_over(a.run_dir):
            a.phase = "post"
        return a

    @staticmethod
    def _pipeline(run_dir: Path) -> Pipeline:
        import yaml
        return Pipeline.model_validate(yaml.safe_load((run_dir / "pipeline.yaml").read_text()))

    def _create(self, job: dict) -> Active:
        free = runner.free_bytes(self.store)
        if free < runner.MIN_FREE_BYTES:
            raise runner.LowDisk(f"{free / 1024**3:.1f} GB free in {self.store}")
        # In a child: validating the pipeline imports the stage modules, and open3d loads the
        # CUDA driver, after which no forked child can use the GPU. This process must stay clean.
        run_dir, first = self._in_child(_create_run, self.store, job)
        return Active(job, Path(run_dir), self._pipeline(Path(run_dir)), first)

    def _in_child(self, fn: Callable, *args: Any) -> Any:
        parent, child = self.ctx.Pipe(duplex=False)
        proc = self.ctx.Process(target=_child, args=(child, fn, args))
        proc.start()
        child.close()
        try:
            msg = parent.recv()
        except EOFError:
            msg = ("err", f"child died (exit {proc.exitcode})", 0.0)
        proc.join()
        if msg[0] == "err":
            raise ValueError(msg[1])
        return msg[1]

    def _finish(self, job: dict, error: str | None, extra: dict | None = None) -> None:
        job = {k: v for k, v in job.items() if k != "new_run"}
        jobqueue.finish(self.store, {**job, **(extra or {})}, error)
        self._say(f"{'failed' if error else 'done'} {job['id']} {error or extra or ''}")

    # --- tasks -------------------------------------------------------------------------
    def ready(self) -> list[Task]:
        tasks = []
        for a in self.active:
            if a.busy:
                continue
            job, store = a.job, self.store
            if a.phase == "stages":
                name = STAGE_NAMES[a.next]
                enabled = getattr(a.pipeline, name).enabled
                tasks.append(Task(a, name, runner.run_stage_task, (a.run_dir, a.next),
                                  self.cost(name, enabled), stage=True))
            elif a.phase == "post":
                run_id = a.run_dir.name if a.run_dir else job["run_id"]
                publishes = job["type"] == "publish" or job.get("publish")
                name = "publish" if publishes else "eval"
                tasks.append(Task(a, name, jobqueue.post_run, (store, job, run_id),
                                  self.cost(name), "publish" if publishes else None))
            else:
                from twin.prgate import REPO, gate
                tasks.append(Task(a, "prgate", gate, (store, job["pr"], job["sha"],
                                  job.get("repo", REPO)), self.cost("prgate")))
        return sorted(tasks, key=lambda t: t.key)

    def admit(self) -> None:
        """Start ready tasks, best first, while they fit the free budget (backpressure).
        A GPU task that waits only for cores or RAM reserves them, so small CPU tasks cannot
        starve it; one that waits for the GPU reserves nothing, so CPU keeps working."""
        used_c = sum(r.cost.cores for r in self.running)
        used_g = sum(r.cost.gb for r in self.running)
        gpu_busy = any(r.cost.gpu for r in self.running)
        locks = {r.task.lock for r in self.running if r.task.lock}
        reserve: Cost | None = None
        ready = self.ready()
        if self._lease is None and any(t.cost.gpu for t in ready):
            self.hold_gpu()
        # ponytail: a big CPU task can wait behind a stream of small ones; add ageing if seen.
        for t in ready:
            if len(self.running) >= self.max_tasks:
                break
            c = t.cost
            if (t.lock and t.lock in locks) or (c.gpu and gpu_busy):
                continue
            rc, rg = (reserve.cores, reserve.gb) if reserve and not c.gpu else (0, 0)
            if used_c + c.cores + rc <= self.cores and used_g + c.gb + rg <= self.gb:
                self._start(t)
                used_c, used_g = used_c + c.cores, used_g + c.gb
                gpu_busy |= c.gpu
                if t.lock:
                    locks.add(t.lock)
            elif c.gpu and reserve is None:
                reserve = c

    def hold_gpu(self) -> None:
        """Take the GPU lease (unload Librarian's ollama models) and keep it until no GPU task
        is left, so the models cannot reload between two GPU tasks."""
        self._lease = gpulease.lease(self.gpu_record)
        self._lease.__enter__()

    def release_gpu(self) -> None:
        if self._lease is not None:
            lease, self._lease = self._lease, None
            lease.__exit__(None, None, None)

    def _gpu_wanted(self) -> bool:
        """True while a GPU task runs or any active run still has an enabled GPU stage ahead."""
        return any(
            a.phase == "stages" and any(
                n in GPU_STAGES and getattr(a.pipeline, n).enabled for n in STAGE_NAMES[a.next:]
            )
            for a in self.active
        )

    def _start(self, t: Task) -> None:
        parent, child = self.ctx.Pipe(duplex=False)
        proc = self.ctx.Process(target=_child, args=(child, t.fn, t.args))
        proc.start()
        child.close()
        t.job.busy = True
        self.running.append(Running(t, proc, parent, t.cost))

    def reap(self, timeout: float) -> None:
        """Block until a task ends (or timeout), then settle every finished task."""
        if not self.running:
            return
        wait([r.proc.sentinel for r in self.running], timeout)
        for r in [r for r in self.running if not r.proc.is_alive()]:
            self.running.remove(r)
            r.proc.join()
            try:
                msg = r.conn.recv()
            except EOFError:  # the child died before it could report
                msg = None
            r.conn.close()
            self._settle(r.task, msg, r.proc.exitcode)

    def _settle(self, t: Task, msg: tuple | None, exitcode: int | None) -> None:
        a = t.job
        a.busy = False
        if msg is None:
            msg = ("err", f"task {t.name} died (exit {exitcode})", 0.0)
        status, out, peak = msg
        if t.cost.gpu:  # a snapshot: the lease goes on after this task
            a.extra.setdefault("gpu_lease", {})[t.name] = copy.deepcopy(self.gpu_record)
        if peak and t.cost != FREE:
            self.observed[t.name] = max(self.observed.get(t.name, 0.0), peak)
            self.cost_path.write_text(json.dumps(self.observed, indent=2))
        if status == "err":
            if a.run_dir:
                runner.fail_running(a.run_dir, out)
            return self._end(a, out)
        if not t.stage:
            return self._end(a, None, out)
        a.next += 1
        if out or a.next >= len(STAGE_NAMES) or STAGE_NAMES[a.next - 1] == a.job.get("stop_after"):
            a.phase = "post"

    def _after_stages(self, a: Active) -> None:
        job = a.job
        if runner._exit_code(self.store, a.run_dir.name):
            return self._end(a, f"run {a.run_dir.name} has a failed stage", {"run_id": a.run_dir.name})
        if job["type"] in ("run", "rerun") and not (job.get("eval") or job.get("publish")):
            self._end(a, None, {"run_id": a.run_dir.name})

    def _end(self, a: Active, error: str | None, out: dict | None = None) -> None:
        extra = {**a.extra, **(out or {})}
        if a.run_dir:
            extra.setdefault("run_id", a.run_dir.name)
        self.active.remove(a)
        self._finish(a.job, error, extra)

    # --- loop --------------------------------------------------------------------------
    def run(self, poll: float = 5, exit_when_idle: bool = False) -> None:
        try:
            self._loop(poll, exit_when_idle)
        finally:
            self.release_gpu()

    def _loop(self, poll: float, exit_when_idle: bool) -> None:
        while True:
            self.fill()
            for a in list(self.active):
                if a.phase == "post" and a.run_dir and not a.busy and not a.checked:
                    a.checked = True
                    self._after_stages(a)
            self.admit()
            if self._lease is not None and not self._gpu_wanted():
                self.release_gpu()
            if not self.running:
                if not self.active and exit_when_idle and not self.hold_pending():
                    return
                time.sleep(poll)
                continue
            self.reap(poll)

    def hold_pending(self) -> bool:
        return any(jobqueue._dir(self.store, "pending").iterdir())


def stream_worker(store: Path | str, max_tasks: int | None = None, poll: float = 5,
                  exit_when_idle: bool = False, hold=jobqueue.disk_hold) -> int:
    """`twin worker --stream`: the scheduler as the queue worker. 3 when another worker runs."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(jobqueue._dir(store, "pending").parent / ".worker.lock"), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print("twin worker: another worker is running", file=sys.stderr)
        return 3
    try:
        print(f"scheduler: store {store}; requeued {jobqueue.recover(store)}", flush=True)
        Scheduler(store, max_tasks, hold=hold).run(poll, exit_when_idle)
    finally:
        lock.release()
    return 0
