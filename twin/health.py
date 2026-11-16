"""Pipeline health: `twin health` writes <store>/health.json and raises or clears operator alarms.

Alarms are GitHub issues labelled box-alarm, one per kind (opened, commented on at most once an
hour while the alarm holds, closed when it clears), through `gh`. A source paused by the fail-streak
alarm is retried by the autopilot (twin.autopilot.retry_paused). The supervisor script
(scripts/twin-supervisor.sh) calls this once a minute. Stdlib only apart from twin imports.
"""

import json
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from twin import REPO, gates, jobqueue, telemetry

LABEL = "box-alarm"
IDLE_MIN = 30
ROOT_MIN_GB = 15.0
RESTART_MAX = 3  # more than this many restarts of one process in an hour
COMMENT_EVERY = timedelta(hours=1)
TREND_N = 10  # builds in a progress trend
TIERS = {0: "P0 pr-gate", 1: "operator", 2: "P2 area", 3: "P3 sweep", 4: "P4 prefetch"}
PROCESSES = {  # name: marker in the command line of the python process
    "worker": "twin worker",
    "autopilot": "twin autopilot",
    "telemetry": "twin box monitor",
}
RESTARTS_FILE = "supervisor-restarts.log"  # "<iso ts> <process>" per restart, written by the supervisor
PREFLIGHT_FILE = "preflight.json"  # {"ok": bool, "error": str}, written by the pipeline preflight
KINDS = {
    "idle": "Box idle",
    "paused": "Autopilot source paused",
    "restarts": "Process restarting repeatedly",
    "disk": "Root disk low",
    "preflight": "Preflight failure",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# --- collection ---------------------------------------------------------------------------
def processes(ps_text: str | None = None) -> dict:
    """{name: {"alive": bool, "uptime_s": int | None}} from `ps` (commands run by a python interpreter only, so a
    shell or ssh command that merely mentions a name never counts)."""
    if ps_text is None:
        out = subprocess.run(["ps", "-eo", "etimes=,args="], capture_output=True, text=True, check=False)
        ps_text = out.stdout
    found: dict[str, int] = {}
    for line in ps_text.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit() or int(parts[0]) > 10**9 or not parts[1].rsplit("/", 1)[-1].startswith("python"):
            continue  # the command must be a python interpreter; a shell or ssh line is not a process
        for name, marker in PROCESSES.items():
            if marker in parts[2]:
                found[name] = max(found.get(name, 0), int(parts[0]))
    return {n: {"alive": n in found, "uptime_s": found.get(n)} for n in PROCESSES}


def tiers(store: Path, now: datetime, window_h: float = 24.0) -> dict:
    """Per tier: last job queued, finished, failed (time, error), plus runs and job-hours in the window."""
    since = _iso(now - timedelta(hours=window_h))
    out = {}
    for job in jobqueue.list_jobs(store):
        t = out.setdefault(TIERS.get(jobqueue.priority(job), "other"), {
            "queued": None, "finished": None, "failed": None, "runs": 0, "job_hours": 0.0})  # fmt: skip
        t["queued"] = max(filter(None, (t["queued"], job.get("added"))), default=None)
        done = job.get("finished")
        if done and job["state"] == "done":
            t["finished"] = max(filter(None, (t["finished"], done)))
        if done and job["state"] == "failed" and (not t["failed"] or done > t["failed"]["at"]):
            err = (job.get("error") or "?").strip().splitlines()[-1][:160]
            t["failed"] = {"at": done, "error": err}
        if done and done >= since and job.get("started"):
            t["runs"] += job["type"] == "run"
            span = datetime.fromisoformat(done) - datetime.fromisoformat(job["started"])
            t["job_hours"] = round(t["job_hours"] + span.total_seconds() / 3600, 3)
    return out


def idle_minutes(rows: list[dict], now: datetime) -> dict:
    """Minutes, counted back from the newest sample, that CPU, GPU and the queue have each been idle."""
    rows = sorted(rows, key=lambda r: r["ts"])[-24 * 60 * 6:]

    def span(is_idle) -> float:
        end = None
        for r in reversed(rows):
            if not is_idle(r):
                break
            end = r["ts"]
        return round((now - end).total_seconds() / 60, 1) if end else 0.0

    cpu = span(lambda r: (r["cpu_avg_pct"] or 0) < telemetry.IDLE_CPU_PCT)
    gpu = span(lambda r: not (r["gpu_util_pct"] or 0))
    queue = span(lambda r: not (r["queue_running"] or 0) and not (r["queue_pending"] or 0))
    fresh = bool(rows) and (now - rows[-1]["ts"]) < timedelta(minutes=5)
    return {"cpu": cpu, "gpu": gpu, "queue": queue, "all": min(cpu, gpu, queue) if fresh else 0.0}


def progress(store: Path) -> dict:
    """Best and latest value of every gate metric, a trend over the last TREND_N builds and the G2 ratchet."""
    spec = gates.load_gates()["gates"]
    ops = {c["metric"]: (g, c["op"], c["value"]) for g, body in spec.items() for c in body["checks"]}
    trend = _json(Path(store) / "published" / "latest" / "trend.json", [])
    metrics = {}
    for metric, (gate, op, thr) in ops.items():
        vals = [t["metrics"][metric] for t in trend if metric in t.get("metrics", {})]
        if not vals:
            continue
        better = min if op == "<=" else max
        metrics[metric] = {"gate": gate, "op": op, "threshold": thr, "latest": vals[-1], "best": better(vals),
                           "trend": [round(v, 4) for v in vals[-TREND_N:]]}  # fmt: skip
    ratchet = gates.g2_ratchet(_json(Path(store) / "autopilot" / "g2_history.json", []))
    return {"builds": len(trend), "metrics": metrics, "g2_ratchet": ratchet}


def collect(store: Path, now: datetime | None = None, ps_text: str | None = None, rows: list[dict] | None = None) -> dict:
    store, now = Path(store), now or _now()
    state = _json(store / "autopilot" / "state.json", {})
    rows = telemetry.load_rows(store) if rows is None else rows
    gpu_used, gpu_total = None, None
    if rows and rows[-1]["gpu_mem_used_mb"] is not None:
        gpu_used, gpu_total = rows[-1]["gpu_mem_used_mb"], rows[-1]["gpu_mem_total_mb"]
    run, pend, _ = telemetry.queue_counts(store)
    since = now - timedelta(hours=1)
    restarts = Counter()
    try:
        for line in (store / RESTARTS_FILE).read_text().splitlines():
            ts, name = line.split()[:2]
            if datetime.fromisoformat(ts) >= since:
                restarts[name] += 1
    except (OSError, ValueError):
        pass
    by_tier = tiers(store, now)
    return {
        "updated": _iso(now),
        "processes": {n: {**p, "restarts_1h": restarts[n]} for n, p in processes(ps_text).items()},
        "queue": {"running": run, "pending": pend},
        "tiers": by_tier,
        "idle_min": idle_minutes(rows, now),
        "paused": state.get("paused", {}),
        "fail_streaks": {s: bool(state.get("retrying", {}).get(s)) for s in state.get("paused", {})},
        "disk_free_gb": {p: None if (v := telemetry.free_gb(p)) is None else round(v, 1) for p in ("/", "/data")},
        "gpu": {"vram_used_mb": gpu_used, "vram_total_mb": gpu_total, "lease": _lease(store)},
        "progress": progress(store),
        "throughput": {"window_h": 24, "runs_per_hour": round(sum(t["runs"] for t in by_tier.values()) / 24, 2),
                       "job_hours": {k: t["job_hours"] for k, t in by_tier.items()}},
        "preflight": _json(store / "health" / PREFLIGHT_FILE, None),
    }


def _lease(store: Path) -> str:
    """held when a running job carries a gpu_lease record, else free."""
    running = (store / "queue" / "running").glob("*.json")
    return "held" if any(_json(p, {}).get("gpu_lease") for p in running) else "free"


def public(health: dict) -> dict:
    """The copy shipped to the site: no error text, paths, hostnames or addresses."""
    h = json.loads(json.dumps(health))
    for t in h["tiers"].values():
        if t.get("failed"):
            t["failed"] = {"at": t["failed"]["at"]}
    h["paused"] = {s: "paused" for s in h["paused"]}
    h["preflight"] = None if not h.get("preflight") else {"ok": bool(h["preflight"].get("ok"))}
    return h


# --- alarms -------------------------------------------------------------------------------
def alarms(health: dict) -> dict[str, str | None]:
    """{kind: detail while the alarm holds, None when clear}."""
    out: dict[str, str | None] = dict.fromkeys(KINDS)
    idle = health["idle_min"]["all"]
    if idle > IDLE_MIN:
        out["idle"] = f"CPU, GPU and queue idle for {idle:.0f} min (alarm over {IDLE_MIN})."
    if health["paused"]:
        out["paused"] = "; ".join(f"{s}: {e}" for s, e in sorted(health["paused"].items()))
    loud = {n: p["restarts_1h"] for n, p in health["processes"].items() if p["restarts_1h"] > RESTART_MAX}
    if loud:
        out["restarts"] = ", ".join(f"{n} restarted {c} times in the last hour" for n, c in sorted(loud.items()))
    root = health["disk_free_gb"].get("/")
    if root is not None and root < ROOT_MIN_GB:
        out["disk"] = f"{root:.1f} GB free on / (alarm under {ROOT_MIN_GB:.0f} GB). Root is shared with production."
    pre = health.get("preflight")
    if pre and not pre.get("ok", True):
        out["preflight"] = f"Preflight failed: {pre.get('error', '?')}"
    return out


def gh_cli(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if out.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {out.stderr.strip()[:200]}")
    return out.stdout


def _ensure_label(gh) -> None:
    names = [x["name"] for x in json.loads(gh("label", "list", "-R", REPO, "--json", "name", "--limit", "200"))]
    if LABEL not in names:
        gh("label", "create", LABEL, "-R", REPO, "--color", "B60205", "--description", "Box needs the operator")


def sync(store: Path, health: dict, gh=gh_cli, now: datetime | None = None) -> list[str]:
    """Open, comment on (at most hourly) or close one issue per alarm kind. Returns what it did.
    State is <store>/health/alarms.json: {kind: {"issue": n, "commented": iso}}."""
    store, now = Path(store), now or _now()
    path = store / "health" / "alarms.json"
    state = _json(path, {})
    did = []
    active = alarms(health)
    if any(active.values()) or state:
        _ensure_label(gh)
    for kind, detail in active.items():
        entry = state.get(kind)
        if detail and not entry:
            url = gh("issue", "create", "-R", REPO, "--label", LABEL, "--title", f"[box-alarm] {KINDS[kind]}",
                     "--body", f"{detail}\n\nRaised {_iso(now)} by `twin health`. This issue closes itself when the alarm clears.")  # fmt: skip
            state[kind] = {"issue": int(url.strip().rsplit("/", 1)[-1]), "commented": _iso(now)}
            did.append(f"opened {kind}")
        elif detail and now - datetime.fromisoformat(entry["commented"]) >= COMMENT_EVERY:
            gh("issue", "comment", str(entry["issue"]), "-R", REPO, "--body", f"Still firing at {_iso(now)}: {detail}")
            entry["commented"] = _iso(now)
            did.append(f"commented {kind}")
        elif not detail and entry:
            gh("issue", "close", str(entry["issue"]), "-R", REPO, "--comment", f"Cleared at {_iso(now)}.")
            del state[kind]
            did.append(f"closed {kind}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")
    return did


def run(store: Path, alert: bool = True, gh=gh_cli) -> dict:
    """One health pass: write health.json, then sync alarms (a gh failure is reported, never raised)."""
    health = collect(store)
    store = Path(store)
    tmp = store / "health.json.tmp"
    tmp.write_text(json.dumps(health, indent=2) + "\n")
    tmp.replace(store / "health.json")
    if alert:
        try:
            for line in sync(store, health, gh):
                print(f"health: {line}", flush=True)
        except (RuntimeError, ValueError, OSError) as exc:
            print(f"health: alert sync failed: {exc}", flush=True)
    return health


def health_command(store: Path | None, no_alert: bool) -> int:
    from twin.runner import default_store

    health = run(Path(store or default_store()), alert=not no_alert)
    ok = all(p["alive"] for p in health["processes"].values())
    print(f"health: {'ok' if ok else 'a process is down'}, idle {health['idle_min']['all']:.0f} min", flush=True)
    return 0

