"""Autopilot: keep the box's queue full, best work first. A poll loop beside the scheduler.

When the scheduler's active jobs are below LOW_WATER it asks the sources in order until TARGET is reached:
P0 PR gates, P2 area rebuild on a new main commit (P2b: re-evaluate when a gate changed),
P3 sweeps (a stalled line is replaced by a new one, never idle), P4 prefetch (until the disk hold).
Everything it queues carries tags ["autopilot"]. `touch <store>/autopilot.pause` pauses it.
State is <store>/autopilot/state.json. P0 (cheap, urgent) is polled on every pass.
Alarms: when over half of a source's last 10 jobs fail with one error, the source is paused and
<store>/autopilot/alarm.txt says why (delete the file to resume); an idle box is logged.
"""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from filelock import FileLock, Timeout

from twin import gates, jobqueue, prgate, site, sweep, telemetry
from twin.contracts import Params
from twin.runner import dataset_version

TAGS = {"tags": ["autopilot"]}
LOW_WATER = 6  # active jobs below this: refill
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
PREFETCH_SCENES = 6  # load+mask only; the disk hold is the only limit on areas
PREFETCH_STORE_MIN_GB = 100.0  # free on the store's own filesystem (/data, 2 TB)
PREFETCH_ROOT_MIN_GB = 10.0  # root is shared with production (jobqueue.DISK_RULES)
G2_STEPS = {0.20: 0.10, 0.10: 0.05}  # the G2 ratchet: lower once 3 area builds in a row pass
G2_RUN = 3
GROUPS = ("ground", "features", "align", "colour", "semantics")  # parameter groups a new line rotates
LINE_PARAMS = 3  # swept parameters per new line
FAIL_WINDOW = 10  # last jobs per source looked at by the fail-streak alarm
IDLE_MIN = 30  # minutes of idle telemetry before the idle alarm
IDLE_CPU_PCT = 25.0
ALARM_FILE = "alarm.txt"


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


def gates_hash() -> str:
    """Changes when gates.yaml or the gate code changes."""
    h = hashlib.sha1(gates.GATES_FILE.read_bytes())
    h.update(Path(gates.__file__).read_bytes())
    return h.hexdigest()


def record_g2(store: Path) -> None:
    """Append the latest area build's G2 value and verdict to autopilot/g2_history.json, and say
    when G2_RUN builds in a row passed at the current threshold. gates.yaml is never edited."""
    try:
        report = json.loads((store / "areas" / f"{AREA}-merged" / "gates.json").read_text())
        check = report["gates"]["G2"]["checks"][0]
        entry = {"run_id": report["run_id"], "value": check["value"], "threshold": check["threshold"],
                 "status": check["status"]}  # fmt: skip
    except (OSError, ValueError, KeyError, IndexError):
        return
    path = store / "autopilot" / "g2_history.json"
    try:
        history = json.loads(path.read_text())
    except (OSError, ValueError):
        history = []
    if any((h["run_id"], h["threshold"]) == (entry["run_id"], entry["threshold"]) for h in history):
        return  # a re-eval of a build already recorded
    history.append({**entry, "ts": datetime.now(UTC).isoformat(timespec="seconds")})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2) + "\n")
    last = history[-G2_RUN:]
    nxt = G2_STEPS.get(entry["threshold"])
    if nxt and len(last) == G2_RUN and all(h["threshold"] == entry["threshold"] and h["status"] == "go" for h in last):
        say(f"G2 ratchet due: lower to {nxt}")


def _detached(store: Path, name: str, cmd: str) -> tuple[int, str]:
    """Run a shell command in its own session; its exit code lands in the returned file."""
    logs = store / "autopilot"
    logs.mkdir(parents=True, exist_ok=True)
    exit_file = logs / f"{name}.exit"
    exit_file.unlink(missing_ok=True)
    proc = subprocess.Popen(
        ["sh", "-c", f"{cmd}; echo $? > {exit_file}"],
        stdout=(logs / f"{name}.log").open("w"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )  # fmt: skip
    return proc.pid, str(exit_file)


def _exit_code(job: dict) -> str:
    path = Path(job["exit_file"])
    return path.read_text().strip() if path.is_file() else "?"


def publish_latest(store: Path) -> None:
    """Update the site's Latest build view after an area eval, whatever the verdict (#192).
    A failure is logged and never stops the loop."""
    try:
        say(f"latest build: {site.publish_latest(store, f'{AREA}-merged')}")
    except site.SiteStop as exc:
        say(f"latest build not published: {exc}")
    except Exception as exc:  # noqa: BLE001 - the autopilot loop must not die on a site problem
        say(f"latest build publish failed: {exc!r}")


def p2_area(store: Path, state: dict) -> int:
    """On a new main commit: area merge (it builds each drive itself), then eval, in one
    detached shell. Then the #143 and #144 hooks. When main is unchanged but a gate changed since
    the last eval (P2b), re-run eval and the hooks on the latest area build. Returns 0: these
    are not queue jobs."""
    p2, p2b = state.setdefault("p2", {}), state.setdefault("p2b", {})
    if any(j.get("pid") and _alive(j["pid"]) for j in (p2, p2b)):
        return 0  # still building
    if p2.get("building"):  # it ended; the exit file says how
        code = _exit_code(p2)
        say(f"P2 {p2['building'][:7]} finished, exit {code}")
        if code in ("0", "1"):
            publish_latest(store)
        if code == "0":
            leave_one_drive_out(store, AREA)
            rain_test(store, AREA)
            p2b["gates"] = gates_hash()  # that eval ran with today's gates
            record_g2(store)
        p2.update(built=p2["building"], building=None, pid=None, exit=code)
    if p2b.get("running"):
        code = _exit_code(p2b)
        say(f"P2b re-eval finished, exit {code}")
        if code in ("0", "1"):
            publish_latest(store)
        if code == "0":
            leave_one_drive_out(store, AREA)
            rain_test(store, AREA)
            record_g2(store)
        p2b.update(running=False, pid=None, exit=code)
    twin = f"{sys.executable} -m twin.cli"
    # eval exit 1 is a no-go verdict, not a failure
    eval_cmd = f"({twin} eval areas/{AREA}-merged --store {store}; [ $? -le 1 ])"
    commit = main_commit()
    if commit is not None and commit != p2.get("built"):
        pid, exit_file = _detached(store, f"p2-{commit[:7]}", f"{twin} area merge {AREA} --store {store} && {eval_cmd}")
        p2.update(building=commit, pid=pid, exit_file=exit_file)
        say(f"P2 new main {commit[:7]}: area {AREA} merge + eval, pid {pid}")
    elif p2.get("built") and p2b.get("gates") != (now := gates_hash()):
        pid, exit_file = _detached(store, "p2b", eval_cmd)
        p2b.update(running=True, pid=pid, exit_file=exit_file, gates=now)
        say(f"P2b gates changed: re-eval of area {AREA}, pid {pid}")
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


def _usable(store: Path, folder: Path) -> bool:
    """A rerun sweep needs the base run built from the worker's dataset version."""
    try:
        target = json.loads((folder / "sweep.json").read_text())["target"]
        made = json.loads((store / target / "manifest.json").read_text())["data"]["nuscenes_version"]
    except (OSError, ValueError, KeyError):
        return False
    return made == dataset_version()


def _latest_scored(store: Path) -> str | None:
    for folder in sorted((store / "sweeps").glob("*"), reverse=True):
        if not _usable(store, folder):
            continue
        board = _board(store, folder.name)
        if board and board["rows"]:
            return folder.name
    return None


def base_runs(store: Path) -> list[str]:
    """Dry drives: full runs of this dataset version whose accuracy stage passed, oldest first."""
    out = []
    for path in sorted(store.glob("*/manifest.json")):
        try:
            m = json.loads(path.read_text())
            ok = m["data"]["nuscenes_version"] == dataset_version() and not m.get("parent")
            ok = ok and any(st["name"] == "accuracy" and st["status"] == "ok" for st in m["stages"])
        except (OSError, ValueError, KeyError):
            continue
        if ok:
            out.append(path.parent.name)
    return out


def group_space(group: str, start: int) -> dict:
    """A random search over LINE_PARAMS numeric parameters of one group, over the contract ranges."""
    found = []
    for name, field in type(getattr(Params(), group)).model_fields.items():
        if field.annotation not in (int, float):
            continue
        lo = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        hi = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        if lo is not None and hi is not None:
            found.append((f"{group}.{name}", {"min": lo, "max": hi}))
    n = min(LINE_PARAMS, len(found))
    picked = [found[(start + i) % len(found)] for i in range(n)]
    return {"mode": "random", "n": ROUND_N, "params": dict(picked)}


def new_line(store: Path, state: dict) -> int:
    """Start a sweep line: the next base run, the next parameter group. Bases rotate fastest,
    groups after a full pass over the bases, so every pair is tried before any repeats."""
    bases = base_runs(store)
    if not bases:
        return 0
    n = state.get("p3_lines", 0)
    for k in range(n, n + len(bases) * len(GROUPS)):  # a base can be unusable: try the next
        base, group = bases[k % len(bases)], GROUPS[(k // len(bases)) % len(GROUPS)]
        space = group_space(group, k // (len(bases) * len(GROUPS)))
        space["seed"] = k
        try:
            new = sweep.queue_sweep(store, base, space, TAGS)
        except ValueError as exc:
            say(f"P3 new line on {base} / {group} skipped: {exc}")
            continue
        state["p3_lines"] = k + 1
        state["p3"] = {"sweep": new, "best": None, "stall": 0, "round": 0, "base": base, "group": group}
        say(f"P3 new line {new}: {group} around {base}")
        return len(json.loads((store / "sweeps" / new / "sweep.json").read_text())["variants"])
    state["p3_lines"] = n + 1
    return 0


def p3_sweep(store: Path, state: dict) -> int:
    """Exploit: a narrowing random search seeded from the top 5 of the latest leaderboard.
    A line ends after STALL_LIMIT rounds without a better top score, or when it has no seed;
    then a new line starts on the next base run and parameter group. P3 never runs dry."""
    line = state.get("p3")
    if line is None:
        seed = _latest_scored(store)
        if seed is None:
            return new_line(store, state)  # no passing leaderboard: explore a base run instead
        line = state["p3"] = {"sweep": seed, "best": None, "stall": 0, "round": 0}
    if line.get("stopped"):
        return new_line(store, state)
    board = _board(store, line["sweep"])
    if board is None or board["waiting"]:
        return 0  # still running
    if not board["rows"]:
        line["stopped"] = True  # the round finished with nothing scored
        return new_line(store, state)
    best = list(_key(board["rows"][0]))
    prev = line["best"]
    if prev is None or best[0] > prev[0] or (best[0] == prev[0] and best[1] > prev[1] + MIN_GAIN):
        line["stall"], line["best"] = 0, best
    else:
        line["stall"] += 1
    if line["stall"] >= STALL_LIMIT:
        line["stopped"] = True
        say(f"P3 sweep line stopped after {STALL_LIMIT} rounds without gain (best {line['best']})")
        return new_line(store, state)
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
    """Load + mask only, one more ranked area per call. Compute-only, never published. No cap on
    areas: the disk hold (root and the store's filesystem) is the only limit."""
    for path, need in (("/", PREFETCH_ROOT_MIN_GB), (str(store), PREFETCH_STORE_MIN_GB)):
        free = telemetry.free_gb(path)
        if free is not None and free < need:
            say(f"P4 held: {free:.1f} GB free on {path}, need {need:.0f}")
            return 0
    done = state.setdefault("p4", {})
    skip = _covered(store) | set(done)
    key = next((k for k in ranked_areas() if k not in skip), None)
    if key is None:
        return 0
    try:
        tokens = {s["name"]: s["token"] for s in json.loads((NUSCENES / "scene.json").read_text())}
    except (OSError, ValueError):
        return 0
    jobs = [
        jobqueue.add(store, {"type": "run", "scene": tokens[n], "stop_after": "mask",
                             "priority": 4, "prefetch": key, **TAGS})
        for n in ranked_areas()[key][:PREFETCH_SCENES] if n in tokens
    ]  # fmt: skip
    done[key] = jobs
    say(f"P4 prefetch {key}: {len(jobs)} load+mask runs")
    return len(jobs)


SOURCES = (("P2", p2_area), ("P3", p3_sweep), ("P4", p4_prefetch))  # P0 runs on every pass


# --- alarms -----------------------------------------------------------------------------
def _source(job: dict) -> str | None:
    if job["type"] == "prgate":
        return "P0"
    return "P3" if job.get("sweep") else "P4" if job.get("prefetch") else None


def _short(error: str) -> str:
    return error.strip().splitlines()[-1][:200] if error and error.strip() else "?"


def fail_streaks(store: Path, state: dict) -> None:
    """Over half of a source's last FAIL_WINDOW jobs failed with one error: pause the source,
    write alarm.txt, log it. Deleting alarm.txt resumes (older failures then stop counting)."""
    alarm = store / "autopilot" / ALARM_FILE
    paused = state.setdefault("paused", {})
    if paused and not alarm.exists():
        say(f"{ALARM_FILE} removed: resuming {sorted(paused)}")
        paused.clear()
        state["resumed"] = datetime.now(UTC).isoformat(timespec="seconds")
    jobs = [j for j in jobqueue.list_jobs(store)
            if j["state"] in ("done", "failed") and "autopilot" in j.get("tags", [])
            and j.get("finished", "") > state.get("resumed", "")]  # fmt: skip
    for src in ("P0", "P3", "P4"):
        if src in paused:
            continue
        last = sorted((j for j in jobs if _source(j) == src), key=lambda j: j["finished"])[-FAIL_WINDOW:]
        if len(last) < FAIL_WINDOW:
            continue
        errors = Counter(_short(j["error"]) for j in last if j["state"] == "failed")
        if errors and (top := errors.most_common(1)[0])[1] > FAIL_WINDOW / 2:
            paused[src] = top[0]
            alarm.parent.mkdir(parents=True, exist_ok=True)
            with alarm.open("a") as f:
                f.write(f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC {src} paused: {top[1]} of the last "
                        f"{FAIL_WINDOW} jobs failed with: {top[0]}\n")  # fmt: skip
            say(f"ALARM {src} paused, {top[1]}/{FAIL_WINDOW} jobs failed: {top[0]} (see {alarm})")


def idle_alarm(store: Path, state: dict, now: datetime | None = None) -> bool:
    """Log an alarm when the last IDLE_MIN minutes of telemetry show CPU under IDLE_CPU_PCT, GPU
    at 0 and an empty queue, with samples from the whole window. Once per window."""
    now = now or datetime.now(UTC)
    since = now - timedelta(minutes=IDLE_MIN)
    if state.get("idle_alarm") and datetime.fromisoformat(state["idle_alarm"]) > since:
        return False
    rows = []
    for day in (now - timedelta(days=1), now):
        path = store / "telemetry" / f"{day:%Y-%m-%d}.csv"
        if path.is_file():
            with path.open(newline="") as f:
                rows += [r for r in csv.DictReader(f) if datetime.fromisoformat(r["ts"]) >= since]
    if not rows or datetime.fromisoformat(rows[0]["ts"]) > since + timedelta(minutes=2):
        return False  # no samples from the start of the window

    def idle(r: dict) -> bool:
        try:
            return (float(r["cpu_avg_pct"]) < IDLE_CPU_PCT and float(r["gpu_util_pct"] or 0) == 0
                    and not float(r["queue_running"] or 0) and not float(r["queue_pending"] or 0))  # fmt: skip
        except (ValueError, KeyError):
            return False

    if not all(idle(r) for r in rows):
        return False
    state["idle_alarm"] = now.isoformat(timespec="seconds")
    say(f"ALARM idle: CPU under {IDLE_CPU_PCT:.0f}%, GPU 0% and an empty queue for {IDLE_MIN} min")
    return True


def step(store: Path, ready=None, skip: tuple = ()) -> str:
    """One pass. Returns a short status line."""
    store = Path(store)
    if (store / PAUSE_FILE).exists():
        return "paused"
    state = load_state(store)
    fail_streaks(store, state)
    idle_alarm(store, state)
    skip = (*skip, *state["paused"])
    queued = {} if "P0" in skip else {"P0": p0_prgate(store, state)}
    # the scheduler's active tasks (jobs in running/), not pending files: held jobs are no work
    n = telemetry.queue_counts(store)[0] if ready is None else ready
    if n < LOW_WATER:
        for name, source in SOURCES:
            if name in skip:
                continue
            if n >= TARGET:
                break
            queued[name] = source(store, state)
            n += queued[name]
    save_state(store, state)
    return f"active {n}, queued {queued}"


def autopilot_command(store: Path | None, poll: float, once: bool, skip: tuple = ()) -> int:
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
                say(step(store, skip=skip))
            except Exception as exc:  # noqa: BLE001 - one bad pass must not end the loop
                say(f"pass failed: {type(exc).__name__}: {exc}")
            if once:
                return 0
            time.sleep(poll)
    finally:
        lock.release()
