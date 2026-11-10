"""Box utilisation telemetry: sample the box to a daily CSV, then report idle time and stage hours.

Plain files only: <store>/telemetry/YYYY-MM-DD.csv (UTC date). Sources: /proc/stat, /proc/loadavg,
/proc/meminfo, /proc/diskstats (Linux only), nvidia-smi (optional), shutil.disk_usage, and the
job queue folders under <store>/queue. Stdlib only.
"""

import csv
import json
import math
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from twin.runner import STAGE_NAMES, default_store

COLUMNS = (
    "ts",
    "cpu_cores",
    "cpu_avg_pct",
    "cpu_core_pcts",
    "load1",
    "load5",
    "load15",
    "ram_used_gb",
    "ram_total_gb",
    "gpu_util_pct",
    "gpu_mem_used_mb",
    "gpu_mem_total_mb",
    "disk_read_mbps",
    "disk_write_mbps",
    "free_root_gb",
    "free_data_gb",
    "queue_running",
    "queue_pending",
    "queue_ready",
)
NUMERIC = tuple(c for c in COLUMNS if c not in ("ts", "cpu_core_pcts"))
IDLE_CPU_PCT = 50.0
# A whole-disk name, so partitions (sda1, nvme0n1p1) are not counted twice.
WHOLE_DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+n\d+)$")
GIB = 1024**3


# ------------------------------------------------------------------ sampling


def read_cpu(path: str = "/proc/stat") -> list[tuple[int, int]]:
    """(idle, total) jiffies: the all-CPU line first, then one per core."""
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.startswith("cpu"):
            f = [int(x) for x in line.split()[1:]]
            rows.append((f[3] + f[4], sum(f[:8])))  # idle + iowait, all time fields
    return rows


def cpu_pcts(prev: list[tuple[int, int]], cur: list[tuple[int, int]]) -> list[float]:
    """Busy % between two read_cpu() results. Index 0 is all CPUs, then each core."""
    out = []
    for (i0, t0), (i1, t1) in zip(prev, cur):
        dt = t1 - t0
        out.append(0.0 if dt <= 0 else 100 * (1 - (i1 - i0) / dt))
    return out


def read_disk(path: str = "/proc/diskstats") -> tuple[int, int]:
    """Bytes read and written since boot, summed over whole disks."""
    read = written = 0
    for line in Path(path).read_text().splitlines():
        f = line.split()
        if WHOLE_DISK.match(f[2]):
            read += int(f[5]) * 512
            written += int(f[9]) * 512
    return read, written


def read_ram(path: str = "/proc/meminfo") -> tuple[float, float]:
    """(used GiB, total GiB). Used = total minus MemAvailable."""
    info = {}
    for line in Path(path).read_text().splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0]) * 1024
    return (info["MemTotal"] - info["MemAvailable"]) / GIB, info["MemTotal"] / GIB


def read_load(path: str = "/proc/loadavg") -> tuple[float, float, float]:
    one, five, fifteen = Path(path).read_text().split()[:3]
    return float(one), float(five), float(fifteen)


def read_gpu() -> tuple[float | None, float | None, float | None]:
    """Mean utilisation %, memory used MiB and memory total MiB over all GPUs; None without one."""
    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    rows = [
        [float(x) for x in line.split(",")] for line in out.stdout.splitlines() if line
    ]
    if not rows:
        return None, None, None
    util = sum(r[0] for r in rows) / len(rows)
    return util, sum(r[1] for r in rows), sum(r[2] for r in rows)


def free_gb(path: str) -> float | None:
    """Free GiB on the filesystem holding path, or None when the path is absent."""
    if not Path(path).exists():
        return None
    return shutil.disk_usage(path).free / GIB


def queue_counts(store: Path | str) -> tuple[int, int, int]:
    """(running, pending, ready). ready is the ready folder when it exists (#180), else pending."""
    queue = Path(store) / "queue"

    def count(state: str) -> int:
        folder = queue / state
        return len(list(folder.glob("*.json"))) if folder.is_dir() else 0

    pending = count("pending")
    ready = count("ready") if (queue / "ready").is_dir() else pending
    return count("running"), pending, ready


class Sampler:
    """Holds the previous CPU and disk counters, so each row covers the time since the last one."""

    def __init__(self, store: Path | str):
        self.store = Path(store)
        self.cpu = read_cpu()
        self.disk = read_disk()
        self.t = time.monotonic()

    def row(self) -> dict:
        cpu, disk, t = read_cpu(), read_disk(), time.monotonic()
        dt = max(t - self.t, 1e-9)
        pcts = cpu_pcts(self.cpu, cpu)
        read_bps = (disk[0] - self.disk[0]) / dt / 1e6
        write_bps = (disk[1] - self.disk[1]) / dt / 1e6
        self.cpu, self.disk, self.t = cpu, disk, t
        load = read_load()
        ram_used, ram_total = read_ram()
        gpu_util, gpu_used, gpu_total = read_gpu()
        running, pending, ready = queue_counts(self.store)
        return {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "cpu_cores": len(pcts) - 1,
            "cpu_avg_pct": round(pcts[0], 1),
            "cpu_core_pcts": ";".join(f"{p:.0f}" for p in pcts[1:]),
            "load1": load[0],
            "load5": load[1],
            "load15": load[2],
            "ram_used_gb": round(ram_used, 2),
            "ram_total_gb": round(ram_total, 2),
            "gpu_util_pct": gpu_util,
            "gpu_mem_used_mb": gpu_used,
            "gpu_mem_total_mb": gpu_total,
            "disk_read_mbps": round(read_bps, 2),
            "disk_write_mbps": round(write_bps, 2),
            "free_root_gb": _round_or_none(free_gb("/")),
            "free_data_gb": _round_or_none(free_gb("/data")),
            "queue_running": running,
            "queue_pending": pending,
            "queue_ready": ready,
        }


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def append_row(store: Path | str, row: dict) -> Path:
    """Append one row to today's CSV, writing the header when the file is new."""
    folder = Path(store) / "telemetry"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now(UTC):%Y-%m-%d}.csv"
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow({k: "" if v is None else v for k, v in row.items()})
    return path


def monitor(
    store: Path | str, interval: float = 10.0, samples: int | None = None
) -> None:
    """Sample every interval seconds until stopped (or for samples rows, for tests)."""
    sampler = Sampler(store)
    done = 0
    while samples is None or done < samples:
        time.sleep(interval)
        try:
            append_row(store, sampler.row())
        except Exception as exc:  # noqa: BLE001 - one bad sample must not stop the monitor
            print(f"telemetry: sample failed: {exc!r}", file=sys.stderr, flush=True)
        done += 1


# ------------------------------------------------------------------- report


def _num(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def load_rows(store: Path | str) -> list[dict]:
    rows = []
    for path in sorted((Path(store) / "telemetry").glob("*.csv")):
        with path.open(newline="") as f:
            for raw in csv.DictReader(f):
                row = {k: _num(raw[k]) for k in NUMERIC}
                row["ts"] = datetime.fromisoformat(raw["ts"])
                rows.append(row)
    return rows


def pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(q / 100 * len(ordered)) - 1))
    return ordered[k]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def stage_hours(
    store: Path | str, rows: list[dict], since: datetime
) -> dict[str, dict]:
    """Core-hours and GPU-hours per stage name. A stage's hours are its wall seconds times the
    mean busy share of the samples taken during it. Stages shorter than one sample are not counted.
    Linked stages of a rerun (before its from_stage) ran in the parent run, so they are skipped."""
    totals: dict[str, dict] = {}
    for manifest in sorted(Path(store).glob("*/manifest.json")):
        data = json.loads(manifest.read_text())
        parent = data.get("parent")
        first_new = STAGE_NAMES.index(parent["from_stage"]) if parent else 0
        for stage in data.get("stages", []):
            if stage["status"] not in ("ok", "failed"):
                continue
            if STAGE_NAMES.index(stage["name"]) < first_new:
                continue
            start = datetime.fromisoformat(stage["started"])
            if start < since:
                continue
            end = start + timedelta(seconds=stage["seconds"])
            window = [r for r in rows if start <= r["ts"] <= end]
            cpu = _mean(
                [r["cpu_avg_pct"] for r in window if r["cpu_avg_pct"] is not None]
            )
            gpu = _mean(
                [r["gpu_util_pct"] for r in window if r["gpu_util_pct"] is not None]
            )
            if cpu is None and gpu is None:
                continue
            hours = stage["seconds"] / 3600
            total = totals.setdefault(
                stage["name"], {"cpu_hours": 0.0, "gpu_hours": 0.0}
            )
            if cpu is not None:
                total["cpu_hours"] += hours * cpu / 100 * window[0]["cpu_cores"]
            if gpu is not None:
                total["gpu_hours"] += hours * gpu / 100
    return totals


def report(store: Path | str, hours: float = 24.0, now: datetime | None = None) -> str:
    store = Path(store)
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    rows = [r for r in load_rows(store) if since <= r["ts"] <= now]
    if not rows:
        return f"no samples in the last {hours:g} h under {store / 'telemetry'}\n"
    lines = [
        (
            f"{len(rows)} samples, {rows[0]['ts']:%Y-%m-%d %H:%M} to "
            f"{rows[-1]['ts']:%Y-%m-%d %H:%M} UTC, last {hours:g} h"
        ),
        f"{'metric':<18}{'p10':>8}{'p50':>8}{'p90':>8}{'max':>8}",
    ]
    metrics = (
        ("cpu avg %", "cpu_avg_pct"),
        ("load 1m", "load1"),
        ("RAM used GiB", "ram_used_gb"),
        ("GPU util %", "gpu_util_pct"),
        ("disk write MB/s", "disk_write_mbps"),
        ("queue ready", "queue_ready"),
        ("queue running", "queue_running"),
    )
    for label, key in metrics:
        values = [r[key] for r in rows if r[key] is not None]
        if not values:
            lines.append(f"{label:<18}{'n/a':>8}")
            continue
        cells = [pct(values, 10), pct(values, 50), pct(values, 90), max(values)]
        lines.append(f"{label:<18}" + "".join(f"{v:>8.1f}" for v in cells))

    cpu_rows = [r for r in rows if r["cpu_avg_pct"] is not None]
    idle = [r for r in cpu_rows if r["cpu_avg_pct"] < IDLE_CPU_PCT]
    blamed = [r for r in idle if (r["queue_ready"] or 0) > 0]
    backlog = len(idle) - len(blamed)
    lines += [
        "",
        (
            f"idle share (cpu avg under {IDLE_CPU_PCT:g}%): "
            f"{_share(len(idle), len(cpu_rows)):.0%} of samples"
        ),
        f"  ready tasks waiting, scheduler to blame: {_share(len(blamed), len(idle)):.0%} of idle",
        f"  nothing ready, backlog to blame: {_share(backlog, len(idle)):.0%} of idle",
    ]

    usage = stage_hours(store, rows, since)
    for field, label in (("cpu_hours", "core-hours"), ("gpu_hours", "GPU-hours")):
        ranked = sorted(usage.items(), key=lambda kv: kv[1][field], reverse=True)
        ranked = [(name, t[field]) for name, t in ranked if t[field] > 0][:5]
        lines.append("")
        lines.append(f"top stages by {label}:")
        lines += [f"  {name:<12}{value:>10.2f}" for name, value in ranked] or ["  none"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- CLI


def box_command(args) -> int:
    store = args.store or default_store()
    if args.box_cmd == "monitor":
        monitor(store, args.interval)
        return 0
    if args.box_cmd == "report":
        print(report(store, args.hours), end="")
        return 0
    print("usage: twin box {monitor,report}", file=sys.stderr)
    return 2
