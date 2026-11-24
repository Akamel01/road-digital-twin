"""File job queue in the run store: <store>/queue/{pending,running,done,failed}/<id>.json.

A job moves between folders by atomic rename. One worker at a time (a file lock); on start it
puts unfinished running jobs back to pending, so a crash loses nothing.
"""

import importlib.util
import json
import multiprocessing
import os
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from filelock import FileLock, Timeout

from twin import gpulease, memcap
from twin.reload import CodeWatch
from twin.runner import (
    LowDisk,
    RunBusy,
    _exit_code,
    default_store,
    recover_interrupted,
    rerun,
    start_run,
)

STATES = ("pending", "running", "done", "failed")
JOB_TYPES = ("run", "rerun", "eval", "publish", "prgate")
# (path, minimum free GB): the root disk is shared with production, /data holds the stores.
DISK_RULES = (("/", 10), ("/data", 50))
POLL_SECONDS = 30
PUBLISH_LOCK = ".publish.lock"
_HELD_NAMES = (RunBusy.__name__, LowDisk.__name__)


def _dir(store: Path, state: str) -> Path:
    path = Path(store) / "queue" / state
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write(path: Path, job: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2) + "\n")
    os.replace(tmp, path)


def validate(job: dict) -> None:
    """Raise ValueError for a job the worker could not run."""
    kind = job.get("type")
    if kind not in JOB_TYPES:
        raise ValueError(f"job type must be one of {JOB_TYPES}, got {kind!r}")
    need = {"run": "scene", "rerun": "run_id", "eval": "run_id", "publish": "run_id", "prgate": "pr"}[kind]
    if not job.get(need):
        raise ValueError(f"{kind} job needs {need!r}")
    if kind == "rerun" and not job.get("from_stage"):
        raise ValueError("rerun job needs 'from_stage'")
    if kind == "prgate" and not job.get("sha"):
        raise ValueError("prgate job needs 'sha'")


def add(store: Path | str, job: dict) -> str:
    """Queue a job. Job fields: type run (scene, pipeline, params) | rerun (run_id, from_stage,
    pipeline, params) | eval (run_id, baseline, rerun) | prgate (pr, sha, repo) | publish (run_id, dry_run); run and rerun accept
    eval: true, and publish: true to publish after a GO eval."""
    validate(job)
    job_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S-%f}-{secrets.token_hex(3)}"
    job = {**job, "id": job_id, "added": _now()}
    _write(_dir(Path(store), "pending") / f"{job_id}.json", job)
    return job_id


def list_jobs(store: Path | str) -> list[dict]:
    jobs = []
    for state in STATES:
        for path in sorted(_dir(Path(store), state).glob("*.json")):
            jobs.append({**json.loads(path.read_text()), "state": state})
    return jobs


def _move(store: Path, name: str, src: str, dst: str, job: dict | None = None) -> Path:
    src_path = _dir(store, src) / name
    if job is not None:
        _write(src_path, job)
    dst_path = _dir(store, dst) / name
    os.rename(src_path, dst_path)
    return dst_path


def priority(job: dict) -> int:
    """0 PR gate, 1 operator (default), 2 area pipeline, 3 sweep, 4 prefetch. A job may set it."""
    if "priority" in job:
        return int(job["priority"])
    return 0 if job["type"] == "prgate" else 3 if job.get("sweep") else 1


def take(store: Path | str) -> dict | None:
    """Move the highest-priority pending job (oldest first within a level) to running and
    return it, or None when there is none."""
    store = Path(store)
    pending = {p: json.loads(p.read_text()) for p in _dir(store, "pending").glob("*.json")}
    for path in sorted(pending, key=lambda p: (priority(pending[p]), p.name)):
        try:
            os.rename(path, _dir(store, "running") / path.name)
        except FileNotFoundError:
            continue  # another taker won this one
        job = json.loads((_dir(store, "running") / path.name).read_text())
        job["started"] = _now()
        _write(_dir(store, "running") / path.name, job)
        return job
    return None


def finish(store: Path | str, job: dict, error: str | None = None) -> None:
    """Move a running job to done, or to failed when error is set."""
    job = {**job, "finished": _now(), "error": error}
    _move(
        Path(store), f"{job['id']}.json", "running", "failed" if error else "done", job
    )


def release(store: Path | str, job: dict) -> None:
    """Put a running job back to pending (held, nothing was started)."""
    job = {k: v for k, v in job.items() if k != "started"}
    _move(Path(store), f"{job['id']}.json", "running", "pending", job)


def recover(store: Path | str) -> list[str]:
    """Crash recovery: every job left in running goes back to pending. Call only while
    holding the worker lock, so no live worker owns them."""
    ids = []
    for path in sorted(_dir(Path(store), "running").glob("*.json")):
        os.rename(path, _dir(Path(store), "pending") / path.name)
        ids.append(path.stem)
    return ids


def disk_hold(rules=DISK_RULES) -> str | None:
    """Reason to hold jobs, or None. A path that does not exist is not checked."""
    for path, min_gb in rules:
        if not os.path.exists(path):
            continue
        free = os.statvfs(path).f_bavail * os.statvfs(path).f_frsize
        if free < min_gb * 1024**3:
            return f"{free / 1024**3:.1f} GB free on {path}; need {min_gb} GB"
    return None


def _load(value):
    """A pipeline/params value in a job: inline mapping, or a path to a yaml file."""
    if isinstance(value, str):
        return yaml.safe_load(Path(value).read_text())
    return value


def run_eval(store: Path, job: dict, run_id: str) -> tuple[str, str | None]:
    """Run `twin eval` on a run. Returns (verdict, error). Skipped until twin.gates exists."""
    if importlib.util.find_spec("twin.gates") is None:
        return "skipped: twin eval not available", None
    cmd = [sys.executable, "-m", "twin.cli", "eval", run_id, "--store", str(store)]
    for flag, key in (("--baseline", "baseline"), ("--rerun", "rerun")):
        if job.get(key):
            cmd += [flag, job[key]]
    code = subprocess.run(cmd, check=False).returncode
    if code in (0, 1):  # 1 is a no-go verdict, a result and not a failure
        return ("go" if code == 0 else "no-go"), None
    return "error", f"twin eval exited {code}"


def post_run(store: Path, job: dict, run_id: str) -> dict:
    """The eval and publish steps of a job, after its run (if any) finished."""
    out: dict = {}
    if job["type"] == "eval" or job.get("eval"):
        out["eval_result"], err = run_eval(store, job, run_id)
        if err:
            raise RuntimeError(err)
    if job["type"] == "publish" or (
        job.get("publish") and out.get("eval_result") == "go"
    ):
        from twin.site import SiteStop, publish_run

        try:
            with FileLock(str(Path(store) / PUBLISH_LOCK)):  # publish writes the shared site folder
                out["publish_result"] = publish_run(store, run_id, job.get("dry_run", False))
        except SiteStop as exc:
            raise RuntimeError(str(exc)) from exc
    return out


def execute(store: Path, job: dict) -> dict:
    """Run one job. Returns fields to merge into the job (run_id, eval). Raises on failure;
    RunBusy and LowDisk mean the job was not started."""
    out: dict = {}
    if job["type"] == "prgate":
        from twin.prgate import REPO, gate

        return gate(store, job["pr"], job["sha"], job.get("repo", REPO))
    if job["type"] == "run":
        run_id = start_run(
            store,
            job["scene"],
            _load(job.get("pipeline")) or {},
            _load(job.get("params")) or {},
        )
    elif job["type"] == "rerun":
        run_id = rerun(
            store,
            job["run_id"],
            job["from_stage"],
            _load(job.get("pipeline")),
            _load(job.get("params")),
        )
    else:
        run_id = job["run_id"]
    if job["type"] != "eval" and job["type"] != "publish":
        out["run_id"] = run_id
        if _exit_code(store, run_id):
            raise RuntimeError(f"run {run_id} has a failed stage")
    out.update(post_run(store, job, run_id))
    return out


def _job_child(conn, store, job, cap_gb=0.0, key=None) -> None:
    """Run one job in a forked child; enter the memory scope first."""
    memcap.enter_scope(cap_gb, key)
    try:
        extra = execute(store, job)
    except Exception as exc:  # noqa: BLE001 - reported to parent; held names handled there
        conn.send(("err", type(exc).__name__, str(exc)))
        return
    conn.send(("ok", extra))


def _run_job(store: Path, job: dict, cap_gb: float, key: str):
    """Fork the job into its own capped child. Returns a (status, ...) tuple."""
    memcap.launcher()
    ctx = multiprocessing.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_job_child, args=(child, store, job, cap_gb, key))
    proc.start()
    child.close()
    msg = None
    try:
        msg = parent.recv()
    except EOFError:
        msg = None
    proc.join()
    if proc.is_alive():
        proc.terminate()
        proc.join()
    oom = False
    if msg is None or (isinstance(msg, tuple) and msg and msg[0] != "ok"):
        try:
            oom = bool(memcap.oom_killed(key))
        except Exception:  # noqa: BLE001
            oom = False
    memcap.cleanup_scope(key)
    parent.close()
    if oom:
        return ("oom", None)
    if msg is None:
        return ("err", "ChildDied", f"child died (exit {proc.exitcode})")
    return msg


def process_one(store: Path | str, hold=disk_hold) -> str | None:
    """Take and run one job. Returns a status line, or None when nothing was done
    (queue empty, disk low, or the run store busy)."""
    store = Path(store)
    if not any(_dir(store, "pending").iterdir()):
        return None
    reason = hold()
    if reason:
        return f"held: {reason}"
    job = take(store)
    if job is None:
        return None
    cap = memcap.cap_gb(job.get("type", "stage"), job)
    key = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    held: dict = {}
    if gpulease.needs_gpu(job, _load):
        with gpulease.lease(held):
            outcome = _run_job(store, job, cap, key)
    else:
        outcome = _run_job(store, job, cap, key)
    if outcome and outcome[0] == "oom":
        finish(store, {**job, **({"gpu_lease": held} if held else {})}, "oom-cap")
        return f"failed {job['id']}: oom-cap"
    if outcome and outcome[0] == "err":
        exc_name = outcome[1]
        text = outcome[2]
        if exc_name in _HELD_NAMES:
            release(store, job)
            return f"held {job['id']}: {text}"
        finish(store, {**job, **({"gpu_lease": held} if held else {})}, f"{exc_name}: {text}")
        return f"failed {job['id']}: {exc_name}: {text}"
    extra = outcome[1] if outcome else {}
    if held:
        extra = {**extra, "gpu_lease": held}
        print(f"gpu lease {job['id']}: {held}", flush=True)
    finish(store, {**job, **extra})
    return f"done {job['id']} {extra}"


def worker(
    store: Path | str, jobs: int = 0, poll: float = POLL_SECONDS, hold=disk_hold
) -> int:
    """Process jobs one at a time. jobs=N stops after N jobs, 0 runs until killed.
    Returns 3 when another worker holds the lock."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    memcap.launcher()
    lock = FileLock(
        str(_dir(store, "pending").parent / ".worker.lock"), thread_local=False
    )
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print("twin worker: another worker is running", file=sys.stderr)
        return 3
    try:
        print(f"worker: store {store}; requeued {recover(store)}", flush=True)
        try:
            print(f"interrupted runs: {recover_interrupted(store)}", flush=True)
        except (
            ValueError
        ) as exc:  # a run from another code version has an unreadable manifest
            print(f"run recovery skipped: {exc}", flush=True)
        watch = CodeWatch()
        count = 0
        while not jobs or count < jobs:
            changed = watch.changed()
            if changed:
                old, new = changed
                print(f"code changed {old}..{new}: exiting for restart", flush=True)
                sys.exit(75)
            status = process_one(store, hold)
            if status is None or status.startswith("held"):
                if status:
                    print(status, flush=True)
                if jobs and not any(_dir(store, "pending").iterdir()):
                    break  # bounded run on an empty queue: stop
                time.sleep(poll)
                continue
            print(status, flush=True)
            count += 1
    finally:
        lock.release()
    return 0


def queue_command(action: str, job_file: Path | None, store: Path | None) -> int:
    store = store or default_store()
    if action == "add":
        try:
            print(add(store, json.loads(Path(job_file).read_text())))
        except (OSError, ValueError) as exc:
            print(f"twin queue add: {exc}", file=sys.stderr)
            return 2
        return 0
    for job in list_jobs(store):
        detail = job.get("run_id") or job.get("scene") or ""
        print(
            job["state"],
            job["id"],
            job["type"],
            detail,
            job.get("error")
            or job.get("publish_result")
            or job.get("eval_result")
            or "",
        )
    return 0


def worker_command(store: Path | None, jobs: int, poll: float) -> int:
    return worker(store or default_store(), jobs, poll)
