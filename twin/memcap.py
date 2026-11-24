"""Memory caps and headroom checks for twin worker jobs (ticket #451).

Stdlib only. No side effects at import: nothing probes cgroup/systemd here.
"""

import math
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

HEADROOM_GB = 10.0
CAPS_GB: dict[str, float] = {
    "area-merge": 20.0,
    "stage": 8.0,
    "eval": 8.0,
    "publish": 8.0,
    "prgate": 8.0,
}
PROBE_CAP_GB = 1.0
CGROUP_ROOT: Path = Path("/sys/fs/cgroup")

_MISSING = object()


def _bytes(g: float) -> str:
    return str(int(g * 1024**3))


_WARNED_OVERRIDES: set[str] = set()
_WARNED_READER: bool = False
_WARNED: bool = False
_LAUNCHER = None


def _is_valid(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 and math.isfinite(v)


def _warn_once(key: str) -> None:
    if key not in _WARNED_OVERRIDES:
        _WARNED_OVERRIDES.add(key)
        print(f"twin memcap: WARNING: invalid cap override {key}", file=sys.stderr)


def _cap_root(root: Path = CGROUP_ROOT, proc_cgroup: Path = Path("/proc/self/cgroup")) -> Path | None:
    try:
        lines = proc_cgroup.read_text().splitlines()
    except OSError:
        return None
    unified = None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1].strip() == "":
            unified = parts[2].strip()
            break
    if unified is None:
        return None
    rel = unified.lstrip("/")
    cur = (root / rel) if rel else root
    root_str = str(root)
    while True:
        if not str(cur).startswith(root_str):
            break
        sc = cur / "cgroup.subtree_control"
        try:
            if "memory" in sc.read_text().split():
                return cur
        except OSError:
            pass
        if cur == root:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def _probe_cgroup(root: Path) -> Path | None:
    if root is None:
        return None
    name = f"twin-cap-probe-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    scope = root / name
    try:
        scope.mkdir(parents=True, exist_ok=True)
        (scope / "memory.max").write_text(_bytes(PROBE_CAP_GB))
        (scope / "memory.swap.max").write_text("0")
    except OSError:
        try:
            scope.rmdir()
        except OSError:
            pass
        return None
    for f in ("memory.max", "memory.swap.max"):
        try:
            (scope / f).unlink()
        except OSError:
            pass
    try:
        scope.rmdir()
    except OSError:
        pass
    return root


class Launcher:
    def __init__(self, systemd: str | None, cgroup: Path | None):
        self.systemd = systemd
        self.cgroup = cgroup

    @property
    def available(self) -> bool:
        return self.systemd is not None or self.cgroup is not None

    def argv(self, cmd: list[str], cap_gb: float) -> list[str]:
        if cap_gb <= 0 or self.systemd is None:
            return list(cmd)
        return [
            self.systemd,
            "--user",
            "--scope",
            "--quiet",
            "-p",
            f"MemoryMax={_bytes(cap_gb)}",
            "-p",
            "MemorySwapMax=0",
            "--",
            *cmd,
        ]

    def enter(self, cap_gb: float, key: str) -> bool:
        if cap_gb <= 0 or self.cgroup is None or not key:
            return False
        scope = self.cgroup / f"twin-cap-{key}"
        procs = scope / "cgroup.procs"
        existing = ""
        try:
            if procs.exists():
                existing = procs.read_text().strip()
        except OSError:
            existing = ""
        if existing:
            print(
                f"twin memcap: scope twin-cap-{key} already has live procs; running uncapped",
                file=sys.stderr,
            )
            return False
        try:
            scope.rmdir()
        except OSError:
            pass
        try:
            scope.mkdir(parents=True, exist_ok=True)
            (scope / "memory.max").write_text(_bytes(cap_gb))
            (scope / "memory.swap.max").write_text("0")
            procs.write_text(str(os.getpid()))
        except OSError:
            return False
        return True

    def oom_killed(self, key: str) -> bool:
        if self.cgroup is None or not key:
            return False
        scope = self.cgroup / f"twin-cap-{key}"
        events = scope / "memory.events"
        try:
            text = events.read_text()
        except OSError:
            return False
        for line in text.splitlines():
            parts = line.split()
            if parts and parts[0] == "oom_kill":
                try:
                    return int(parts[1]) > 0
                except (IndexError, ValueError):
                    return False
        return False

    def cleanup(self, key: str) -> None:
        if self.cgroup is None or not key:
            return
        scope = self.cgroup / f"twin-cap-{key}"
        try:
            scope.rmdir()
        except OSError:
            pass


def cap_gb(kind: str, job: dict | None = None, *, stage: str | None = None) -> float:
    if job is not None:
        v = job.get("mem_cap_gb", _MISSING)
        if v is not _MISSING:
            if _is_valid(v):
                return float(v)
            _warn_once(f"job:{kind}:mem_cap_gb")
    if stage is not None:
        envname = "TWIN_MEM_CAP_STAGE_" + stage.replace("-", "_").upper() + "_GB"
        if envname in os.environ:
            try:
                fv = float(os.environ[envname])
                parsed = True
            except (ValueError, TypeError):
                fv = None
                parsed = False
            if not parsed:
                _warn_once(envname)
            elif _is_valid(fv):
                return fv
            else:
                _warn_once(envname)
    envname = "TWIN_MEM_CAP_" + kind.replace("-", "_").upper() + "_GB"
    if envname in os.environ:
        try:
            fv = float(os.environ[envname])
            parsed = True
        except (ValueError, TypeError):
            fv = None
            parsed = False
        if not parsed:
            _warn_once(envname)
        elif _is_valid(fv):
            return fv
        else:
            _warn_once(envname)
    return CAPS_GB.get(kind, CAPS_GB["stage"])


def available_gb(reader=None) -> float | None:
    global _WARNED_READER
    if reader is None:
        from twin import telemetry

        reader = telemetry.read_ram
    try:
        used, total = reader()
        return max(0.0, float(total) - float(used))
    except (OSError, ValueError):
        if not _WARNED_READER:
            _WARNED_READER = True
            print("twin memcap: WARNING: cannot read memory; headroom check skipped", file=sys.stderr)
        return None


def headroom_reason(kind: str, job: dict | None = None, *, stage: str | None = None, reader=None) -> str | None:
    cap = cap_gb(kind, job, stage=stage)
    avail = available_gb(reader=reader)
    if avail is None:
        return None
    if avail - cap < HEADROOM_GB:
        return f"{kind} needs {cap:.1f} GB cap + {HEADROOM_GB:.1f} GB headroom; {avail:.1f} GB available"
    return None


def oom_in_text(text: str) -> bool:
    return any(m in text for m in ("oom-kill", "Memory cgroup out of memory", "Killed process"))


def cap_killed(exitcode, *, cgroup_oom: bool = False, text: str = "") -> bool:
    return bool(cgroup_oom) or oom_in_text(text)


def scope_argv(cmd: list[str], cap_gb: float) -> list[str]:
    return launcher().argv(cmd, cap_gb)


def enter_scope(cap_gb: float, key: str) -> bool:
    l = _LAUNCHER
    if l is None:
        return False
    return l.enter(cap_gb, key)


def oom_killed(key: str) -> bool:
    l = _LAUNCHER
    if l is None:
        return False
    return l.oom_killed(key)


def cleanup_scope(key: str) -> None:
    l = _LAUNCHER
    if l is None:
        return
    l.cleanup(key)


def launcher() -> "Launcher":
    global _LAUNCHER, _WARNED
    if _LAUNCHER is not None:
        return _LAUNCHER
    systemd = shutil.which("systemd-run")
    systemd_usable = False
    if systemd:
        try:
            r = subprocess.run(
                [
                    systemd,
                    "--user",
                    "--scope",
                    "--quiet",
                    "-p",
                    f"MemoryMax={_bytes(PROBE_CAP_GB)}",
                    "-p",
                    "MemorySwapMax=0",
                    "--",
                    "true",
                ],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if r.returncode == 0:
                systemd_usable = True
        except (subprocess.TimeoutExpired, OSError):
            systemd_usable = False
    systemd_val = systemd if systemd_usable else None

    root = _cap_root()
    cgroup_val = _probe_cgroup(root) if root is not None else None

    failures = []
    if systemd is not None and not systemd_usable:
        failures.append("systemd-run probe failed")
    if systemd is None:
        failures.append("systemd-run not found")
    if root is not None and cgroup_val is None:
        failures.append("cgroup probe failed")
    if root is None:
        failures.append("no memory-delegated cgroup ancestor")

    shell_token = "systemd-run" if systemd_val is not None else "UNCAPPED"
    cg_token = str(cgroup_val) if cgroup_val is not None else "none"
    line = f"twin memcap: shell={shell_token} child-cgroups={cg_token}"
    if failures:
        line += " WARNING: " + "; ".join(failures) + "; caps NOT enforced (headroom check still applies)"
    print(line, file=sys.stderr)

    _LAUNCHER = Launcher(systemd_val, cgroup_val)
    _WARNED = True
    return _LAUNCHER


def set_launcher(value) -> None:
    global _LAUNCHER, _WARNED, _WARNED_READER
    _LAUNCHER = value
    _WARNED = False
    if value is None:
        _WARNED_READER = False
        _WARNED_OVERRIDES.clear()
