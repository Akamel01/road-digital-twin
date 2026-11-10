"""Autopilot: keep the box's queue full, best work first. A poll loop beside the scheduler.

When the ready queue is below LOW_WATER it asks the sources in order until TARGET is reached:
P0 PR gates, P2 area rebuild on a new main commit, P3 sweeps around the best, P4 prefetch.
Everything it queues carries tags ["autopilot"]. `touch <store>/autopilot.pause` pauses it.
State is <store>/autopilot/state.json. P0 (cheap, urgent) is polled on every pass.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from twin import jobqueue, prgate, sweep, telemetry

TAGS = {"tags": ["autopilot"]}
LOW_WATER = 6  # ready jobs below this: refill
TARGET = 12  # ... up to this
PAUSE_FILE = "autopilot.pause"
AREA = "seaport"
REPO_URL = "https://github.com/Akamel01/road-digital-twin.git"
ROUND_N = 8  # variants per sweep round
TOP = 5  # leaderboard rows that seed a round
STALL_LIMIT = 3  # rounds without a better score end a sweep line
MIN_GAIN = 1e-6
PASSES_FILE = Path("/data/area_passes.json")  # written by scripts/area_passes.py (area ranking)
NUSCENES = Path("/data/nuscenes/v1.0-trainval")
PREFETCH_AREAS = 2  # disk is shared with production: few areas, few scenes, load+mask only
PREFETCH_SCENES = 6
PREFETCH_MIN_FREE_GB = 15.0
PREFETCH_PIPELINE = {
    s: {"method": m, "enabled": s in ("load", "mask")}
    for s, m in (("load", "nuscenes"), ("mask", "boxes"), ("align", "kiss-icp"),
                 ("ground", "ransac-tiles"), ("features", "intensity"), ("colour", "zbuffer-topk"),
                 ("profile", "centreline"), ("isd", "aashto-b"), ("accuracy", "one-way"),
                 ("outputs", "dxf-pdf"))
}  # fmt: skip


def _state_path(store: Path) -> Path:
    return store / "autopilot" / "state.json"


def load_state(store: Path) -> dict:
    try:
        return json.loads(_state_path(store).read_text())
    except (OSError, ValueError):
        return {}


def save_state(store: Path, state: dict) -> None:
    path = _state_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")


def say(text: str) -> None:
    print(f"autopilot: {text}", flush=True)


# --- P0 ---------------------------------------------------------------------------------
def p0_prgate(store: Path, state: dict) -> int:
    if shutil.which("gh") is None:
        return 0  # no gh on this machine: skip cleanly
    try:
        lines = prgate.poll(store, extra=TAGS)
    except prgate.PrGateError as exc:
        say(f"P0 skipped: {exc}")
        return 0
    for line in lines:
        say(f"P0 {line}")
    return len(lines)


# --- P2 ---------------------------------------------------------------------------------
def main_commit() -> str | None:
    out = subprocess.run(["git", "ls-remote", REPO_URL, "refs/heads/main"],
                         capture_output=True, text=True, check=False)  # fmt: skip
    return out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def leave_one_drive_out(store: Path, area: str) -> int:
    return 0  # hook for #143 (leave-one-drive-out), not built yet: skipped


def rain_test(store: Path, area: str) -> int:
    return 0  # hook for #144 (rain test), not built yet: skipped


def p2_area(store: Path, state: dict) -> int:
    """On a new main commit: area merge (it builds each drive itself), then eval, in one
    detached shell. Then the #143 and #144 hooks. Returns 0: these are not queue jobs."""
    p2 = state.setdefault("p2", {})
    if p2.get("pid") and _alive(p2["pid"]):
        return 0  # still building
    if p2.get("building"):  # it ended; the exit file says how
        code = Path(p2["exit_file"]).read_text().strip() if Path(p2["exit_file"]).is_file() else "?"
        say(f"P2 {p2['building'][:7]} finished, exit {code}")
        if code == "0":
            leave_one_drive_out(store, AREA)
            rain_test(store, AREA)
        p2.update(built=p2["building"], building=None, pid=None, exit=code)
    commit = main_commit()
    if commit is None or commit == p2.get("built"):
        return 0
    logs = store / "autopilot"
    logs.mkdir(parents=True, exist_ok=True)
    exit_file = logs / f"p2-{commit[:7]}.exit"
    exit_file.unlink(missing_ok=True)
    twin = f"{sys.executable} -m twin.cli"
    cmd = (f"{twin} area merge {AREA} --store {store} && "
           f"{twin} eval areas/{AREA}-merged --store {store}")  # fmt: skip
    proc = subprocess.Popen(
        ["sh", "-c", f"{cmd}; echo $? > {exit_file}"],
        stdout=(logs / f"p2-{commit[:7]}.log").open("w"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )  # fmt: skip
    p2.update(building=commit, pid=proc.pid, exit_file=str(exit_file))
    say(f"P2 new main {commit[:7]}: area {AREA} merge + eval, pid {proc.pid}")
    return 0


# --- P3 ---------------------------------------------------------------------------------
def _key(row: dict) -> tuple:
    return (-sweep.RANK.get(row["verdict"], 1), row["score"])


def narrow(rows: list[dict]) -> dict:
    """A search space around the top rows: per swept parameter, their range plus 25 %."""
    params = {}
    for path in rows[0]["overrides"]:
        vals = [r["overrides"][path] for r in rows if path in r["overrides"]]
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in vals):
            lo, hi = min(vals), max(vals)
            pad = max((hi - lo) * 0.25, abs(hi) * 0.02)
            params[path] = {"min": lo - pad, "max": hi + pad}
        else:
            params[path] = {"values": sorted(set(map(str, vals)))}
    return {"mode": "random", "n": ROUND_N, "params": params}


def _board(store: Path, sweep_id: str) -> dict | None:
    try:
        return sweep.leaderboard(store, sweep_id)
    except (OSError, ValueError, KeyError):
        return None


def _latest_scored(store: Path) -> str | None:
    for folder in sorted((store / "sweeps").glob("*"), reverse=True):
        board = _board(store, folder.name)
        if board and board["rows"]:
            return folder.name
    return None


def p3_sweep(store: Path, state: dict) -> int:
    """Exploit: a narrowing random search seeded from the top 5 of the latest leaderboard.
    A line ends after STALL_LIMIT rounds without a better top score."""
    line = state.get("p3")
    if line is None:
        seed = _latest_scored(store)
        if seed is None:
            return 0  # nothing to exploit yet
        line = state["p3"] = {"sweep": seed, "best": None, "stall": 0, "round": 0}
    if line.get("stopped"):
        return 0
    board = _board(store, line["sweep"])
    if board is None or board["waiting"]:
        return 0  # still running
    if not board["rows"]:
        line["stopped"] = True  # the round finished with nothing scored
        return 0
    best = list(_key(board["rows"][0]))
    prev = line["best"]
    if prev is None or best[0] > prev[0] or (best[0] == prev[0] and best[1] > prev[1] + MIN_GAIN):
        line["stall"], line["best"] = 0, best
    else:
        line["stall"] += 1
    if line["stall"] >= STALL_LIMIT:
        line["stopped"] = True
        say(f"P3 sweep line stopped after {STALL_LIMIT} rounds without gain (best {line['best']})")
        return 0
    space = narrow(board["rows"][:TOP])
    space["seed"] = line["round"] = line["round"] + 1
    try:
        new = sweep.queue_sweep(store, board["target"], space, TAGS)
    except ValueError as exc:
        line["stall"] += 1  # an unusable space counts as a round without gain
        say(f"P3 round failed: {exc}")
        return 0
    line["sweep"] = new
    say(f"P3 sweep {new}: round {line['round']} around {board['target']}")
    return len(json.loads((store / "sweeps" / new / "sweep.json").read_text())["variants"])


# --- P4 ---------------------------------------------------------------------------------
def ranked_areas(path: Path = PASSES_FILE) -> dict:
    """{"location/intersection": [scene names]}, most drives first (scripts/area_passes.py)."""
    if not path.is_file():
        subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts" / "area_passes.py")],
                       check=False)  # fmt: skip
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _covered(store: Path) -> set[str]:
    out = set()
    for f in (store / "areas").glob("*.json"):
        try:
            a = json.loads(f.read_text())
        except ValueError:
            continue
        out |= {f"{a.get('location')}/{t}" for t in a.get("intersections", [])}
    return out


def p4_prefetch(store: Path, state: dict) -> int:
    """Load + mask only, for the next-ranked areas. Compute-only, never published."""
    free = telemetry.free_gb("/")
    if free is not None and free < PREFETCH_MIN_FREE_GB:
        say(f"P4 held: {free:.1f} GB free on /, need {PREFETCH_MIN_FREE_GB:.0f}")
        return 0
    done = state.setdefault("p4", {})
    if len(done) >= PREFETCH_AREAS:
        return 0
    skip = _covered(store) | set(done)
    key = next((k for k in ranked_areas() if k not in skip), None)
    if key is None:
        return 0
    try:
        tokens = {s["name"]: s["token"] for s in json.loads((NUSCENES / "scene.json").read_text())}
    except (OSError, ValueError):
        return 0
    jobs = [
        jobqueue.add(store, {"type": "run", "scene": tokens[n], "pipeline": PREFETCH_PIPELINE,
                             "priority": 4, "prefetch": key, **TAGS})
        for n in ranked_areas()[key][:PREFETCH_SCENES] if n in tokens
    ]  # fmt: skip
    done[key] = jobs
    say(f"P4 prefetch {key}: {len(jobs)} load+mask runs")
    return len(jobs)


SOURCES = (("P2", p2_area), ("P3", p3_sweep), ("P4", p4_prefetch))  # P0 runs on every pass


def step(store: Path, ready=None) -> str:
    """One pass. Returns a short status line."""
    store = Path(store)
    if (store / PAUSE_FILE).exists():
        return "paused"
    state = load_state(store)
    queued = {"P0": p0_prgate(store, state)}
    n = telemetry.queue_counts(store)[2] if ready is None else ready
    if n < LOW_WATER:
        for name, source in SOURCES:
            if n >= TARGET:
                break
            queued[name] = source(store, state)
            n += queued[name]
    save_state(store, state)
    return f"ready {n}, queued {queued}"


def autopilot_command(store: Path | None, poll: float, once: bool) -> int:
    from twin.runner import default_store

    store = Path(store or default_store())
    (store / "autopilot").mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(store / "autopilot" / ".lock"), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print("twin autopilot: another autopilot is running", file=sys.stderr)
        return 3
    try:
        while True:
            try:
                say(step(store))
            except Exception as exc:  # noqa: BLE001 - one bad pass must not end the loop
                say(f"pass failed: {type(exc).__name__}: {exc}")
            if once:
                return 0
            time.sleep(poll)
    finally:
        lock.release()
