"""Box telemetry on synthetic /proc text and synthetic CSV rows. Nothing touches the real box."""

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from twin import telemetry
from twin.telemetry import COLUMNS, append_row, cpu_pcts, read_cpu, read_disk, read_ram

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _write(path: Path, text: str) -> str:
    path.write_text(text)
    return str(path)


def test_cpu_busy_share_from_two_reads(tmp_path):
    first = _write(
        tmp_path / "a",
        "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0 0 0 0\n",
    )
    second = _write(
        tmp_path / "b",
        "cpu  150 0 150 750 100 0 0 0 0 0\ncpu0 75 0 75 350 50 0 0 0 0 0\n",
    )
    pcts = cpu_pcts(read_cpu(first), read_cpu(second))
    # all CPUs: 150 busy-ish of 150 total ticks... idle delta 50 of 150 total -> 66.7 % busy
    assert pcts[0] == pytest.approx(66.67, abs=0.01)
    assert pcts[1] == pytest.approx(100.0)  # cpu0: 0 idle ticks of 100 -> 100 %


def test_disk_ram_and_load_parse(tmp_path):
    disks = _write(
        tmp_path / "d",
        "   8  0 sda 1 0 100 0 1 0 50 0 0 0 0\n"
        "   8  1 sda1 1 0 999 0 1 0 999 0 0 0 0\n"
        " 259  0 nvme0n1 1 0 10 0 1 0 20 0 0 0 0\n",
    )
    assert read_disk(disks) == (110 * 512, 70 * 512)  # partitions not double counted
    meminfo = _write(tmp_path / "m", "MemTotal: 2097152 kB\nMemAvailable: 1048576 kB\n")
    used, total = read_ram(meminfo)
    assert used == pytest.approx(1.0) and total == pytest.approx(2.0)


def test_queue_counts_use_ready_folder_when_present(tmp_path):
    for state, n in (("pending", 3), ("running", 2)):
        (tmp_path / "queue" / state).mkdir(parents=True)
        for i in range(n):
            (tmp_path / "queue" / state / f"{i}.json").write_text("{}")
    assert telemetry.queue_counts(tmp_path) == (
        2,
        3,
        3,
    )  # no ready folder: pending used
    (tmp_path / "queue" / "ready").mkdir()
    (tmp_path / "queue" / "ready" / "x.json").write_text("{}")
    assert telemetry.queue_counts(tmp_path) == (2, 3, 1)


def test_gpu_absent_gives_blanks(monkeypatch):
    def no_smi(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(telemetry.subprocess, "run", no_smi)
    assert telemetry.read_gpu() == (None, None, None)


def test_append_row_writes_header_once(tmp_path):
    row = {c: 0 for c in COLUMNS}
    row["gpu_util_pct"] = None
    path = append_row(tmp_path, row)
    append_row(tmp_path, row)
    lines = path.read_text().splitlines()
    assert lines[0].split(",") == list(COLUMNS)
    assert len(lines) == 3
    assert lines[1].split(",")[COLUMNS.index("gpu_util_pct")] == ""


def _csv_row(ts, cpu, gpu, ready):
    return {
        "ts": ts.isoformat(timespec="seconds"),
        "cpu_cores": 28,
        "cpu_avg_pct": cpu,
        "cpu_core_pcts": "",
        "load1": 1.0,
        "load5": 1.0,
        "load15": 1.0,
        "ram_used_gb": 10,
        "ram_total_gb": 64,
        "gpu_util_pct": gpu,
        "gpu_mem_used_mb": 1000,
        "gpu_mem_total_mb": 12000,
        "disk_read_mbps": 0,
        "disk_write_mbps": 2,
        "free_root_gb": 50,
        "free_data_gb": 500,
        "queue_running": 1,
        "queue_pending": ready,
        "queue_ready": ready,
    }


def _synthetic_store(store: Path) -> None:
    rows = []
    # 6 samples inside the stage window, busy
    rows += [
        _csv_row(
            datetime(2026, 11, 10, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=10 * i),
            80,
            50,
            0,
        )
        for i in range(6)
    ]
    # 4 idle samples with ready tasks waiting: scheduler to blame
    rows += [
        _csv_row(
            datetime(2026, 11, 10, 11, 10, 0, tzinfo=UTC) + timedelta(seconds=10 * i),
            30,
            0,
            4,
        )
        for i in range(4)
    ]
    # 2 idle samples with nothing ready: backlog
    rows += [
        _csv_row(
            datetime(2026, 11, 10, 11, 20, 0, tzinfo=UTC) + timedelta(seconds=10 * i),
            30,
            0,
            0,
        )
        for i in range(2)
    ]
    folder = store / "telemetry"
    folder.mkdir(parents=True)
    with (folder / "2026-11-10.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    run = store / "20261110-100000-abcdef"
    run.mkdir()
    manifest = {
        "run_id": run.name,
        "stages": [
            {
                "name": "features",
                "method": "intensity",
                "status": "ok",
                "started": "2026-11-10T10:00:00+00:00",
                "seconds": 3600,
                "files": [],
            }
        ],
    }
    (run / "manifest.json").write_text(json.dumps(manifest))


def test_report_idle_split_and_stage_hours(tmp_path):
    _synthetic_store(tmp_path)
    text = telemetry.report(tmp_path, hours=3, now=NOW)
    assert "12 samples" in text
    assert "50% of samples" in text  # 6 of 12 under 50 % CPU
    assert "67% of idle" in text  # 4 of 6 with ready tasks waiting
    assert "33% of idle" in text  # 2 of 6 with nothing ready
    # one hour at 80 % of 28 cores, 50 % GPU
    assert "features" in text
    assert "22.40" in text
    assert "0.50" in text


def test_report_without_samples(tmp_path):
    assert "no samples" in telemetry.report(tmp_path, hours=1, now=NOW)
