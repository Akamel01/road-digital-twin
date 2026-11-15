"""Auto-publish the public site (ADR 0005): a run that is GO on every gate and beats the
published run goes to twin.papyrus-ai.net. History of published runs: <store>/published/history.json.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from twin import prgate, publish
from twin.area import drive_tokens
from twin.gates import GO
from twin.runner import default_store

WEB = Path(__file__).resolve().parents[1] / "web"
WRANGLER = "wrangler@4.151.2"
ACCOUNT_ID = "1bde08c94022d2f83395dafe200028fa"
TOKEN_FILE = (
    "~/.config/twin/cf-token"  # operator-created, mode 600, never printed or committed
)


class SiteStop(RuntimeError):
    """A clear reason not to continue; the message is for the operator."""


def _history_file(store: Path) -> Path:
    return Path(store) / "published" / "history.json"


def history(store: Path) -> list[dict]:
    path = _history_file(store)
    return json.loads(path.read_text()) if path.exists() else []


def _record(store: Path, entry: dict) -> None:
    path = _history_file(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([*history(store), entry], indent=2) + "\n")


def margins(report: dict) -> dict[str, float]:
    """Room left on each measured check: threshold - value for <=, value - threshold for >=."""
    out = {}
    for gate in report["gates"].values():
        for c in gate["checks"]:
            if c["value"] is not None:
                sign = 1 if c["op"] == "<=" else -1
                out[c["metric"]] = sign * (c["threshold"] - c["value"])
    return out


def beats(new: dict[str, float], old: dict[str, float]) -> str | None:
    """None when new beats old (no check worse, at least one better), else the reason."""
    for metric, was in old.items():
        if metric not in new:
            return f"{metric} no longer measured"
        if new[metric] < was:
            return f"{metric} margin {new[metric]:g} is worse than published {was:g}"
    if old and not any(new[m] > was for m, was in old.items()):
        return "no check is better than the published run"
    return None


def _checks(report: dict):
    for gate in (report.get("gates") or {}).values():
        yield from gate.get("checks", [])


def go_count(report: dict) -> int:
    """Number of gate checks whose status is go."""
    return sum(1 for c in _checks(report) if c.get("status") == "go")


def total_checks(report: dict) -> int:
    return sum(1 for _ in _checks(report))


def margin_sum(report: dict) -> float:
    """Sum of normalised, clipped per-check margins (denom |threshold| or 1)."""
    total = 0.0
    for c in _checks(report):
        v = c.get("value")
        if v is None:
            continue
        t = c.get("threshold", 0)
        op = c.get("op", "<=")
        denom = abs(t) if t not in (0, 0.0) else 1
        sign = 1 if op == "<=" else -1
        margin = sign * (t - v) / denom
        total += max(-1.0, min(1.0, margin))
    return round(total, 6)


def token_path() -> Path:
    return Path(os.environ.get("TWIN_CF_TOKEN_FILE", TOKEN_FILE)).expanduser()


def read_token() -> str:
    path = token_path()
    if not path.is_file():
        raise SiteStop(
            f"no Cloudflare token at {path}: the operator must create it "
            "(docs/runbooks/site-auto-publish.md); nothing was published"
        )
    token = path.read_text().strip()
    if not token:
        raise SiteStop(f"Cloudflare token file {path} is empty")
    return token


def node_env(extra: dict | None = None) -> dict:
    """Environment for npm/npx: ~/.local/node/bin (or $TWIN_NODE_BIN) first on PATH when it exists."""
    node_bin = Path(os.environ.get("TWIN_NODE_BIN", "~/.local/node/bin")).expanduser()
    env = {**os.environ, **(extra or {})}
    if node_bin.is_dir():
        env["PATH"] = f"{node_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    if subprocess.run(cmd, cwd=cwd, env=env or node_env(), check=False).returncode:
        raise SiteStop(f"command failed: {' '.join(cmd[:3])}")


def write_status(showcase: Path, report: dict, published_at: str) -> None:
    """status.json for the site: verdict and how many gate checks pass (the banner on /)."""
    status = {
        "run_id": report.get("run_id"),
        "published_at": published_at,
        "verdict": report["verdict"],
        "gates_version": report["gates_version"],
        "checks_passed": go_count(report),
        "checks_total": total_checks(report),
    }
    (showcase / "status.json").write_text(json.dumps(status, indent=2) + "\n")


def build(run_ids: list[str], store: Path, report: dict, web: Path = WEB) -> None:
    """Showcase bundle, status.json and the static export in web/out."""
    label = ",".join(map(str, run_ids))
    if not shutil.which("npm", path=node_env()["PATH"]):
        raise SiteStop(
            "npm not found: Node is needed to build web/ (not installed on this machine)"
        )
    showcase = web / "public" / "showcase"
    shutil.rmtree(showcase, ignore_errors=True)
    try:
        publish.publish_runs(run_ids, showcase, store)
    except (OSError, ValueError) as exc:
        raise SiteStop(f"cannot build the showcase from {label}: {exc}") from exc
    stage_latest_into(store, web)
    write_status(showcase, report, datetime.now(UTC).isoformat(timespec="seconds"))
    if not (web / "node_modules").exists():
        _run(["npm", "ci"], web)
    _run(["npm", "run", "build"], web)


def deploy(token: str, web: Path = WEB) -> None:
    env = node_env({"CLOUDFLARE_API_TOKEN": token})
    env.setdefault("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    _run(["npx", "-y", WRANGLER, "deploy"], web, env)


def _published_report(store: Path, entry: dict) -> dict | None:
    rid = entry.get("run_id")
    if rid:
        gf = store / rid / "gates.json"
        if gf.exists():
            try:
                return json.loads(gf.read_text())
            except (OSError, ValueError):
                pass
    return None


def _improves(candidate: dict, published_entry: dict, store: Path) -> tuple[bool, str]:
    pub_gc = published_entry.get("go_count")
    pub_ms = published_entry.get("margin_sum")
    if pub_gc is None or pub_ms is None:
        return True, ""
    cand_gc, cand_ms = go_count(candidate), margin_sum(candidate)
    if cand_gc > pub_gc:
        return True, ""
    if cand_gc < pub_gc:
        return False, f"fewer gate checks pass ({cand_gc} vs {pub_gc})"
    if cand_ms > pub_ms:
        return True, ""
    return False, f"margin sum {cand_ms:g} is not greater than published {pub_ms:g}"


def area_runs(store: Path, area) -> list[str]:
    """For each drive of the area build, the newest full single-drive run (prgate.pick_baseline) that has
    every public file; drives without one are left out and logged."""
    store = Path(store)
    area = area if isinstance(area, Path) else resolve_area(store, str(area))
    selected: list[str] = []
    for scene in drive_tokens(area):
        base = prgate.pick_baseline(store, scene=scene)
        if base is None:
            print(f"publish: skip drive scene {scene}: no baseline", file=sys.stderr)
            continue
        run_dir = Path(base)
        manifest_file = run_dir / "manifest.json"
        public_ok = manifest_file.exists()
        if public_ok:
            try:
                json.loads(manifest_file.read_text())
            except (OSError, ValueError):
                public_ok = False
        if public_ok:
            public_ok = all(
                (publish._stage(run_dir, "outputs") / name).exists()
                for name in publish.PUBLIC_FILES
            )
        if not public_ok:
            print(f"publish: skip drive {run_dir.name}: not publishable", file=sys.stderr)
            continue
        selected.append(run_dir.name)
    return selected


def publish_run(
    store: Path,
    run_id,
    dry_run: bool = False,
    force: bool = False,
    web: Path = WEB,
) -> str:
    """Publish run_id (or an area name) if it improves on the published run. Returns a status line;
    a skip returns "skipped: reason". Raises SiteStop when it cannot go on."""
    store = Path(store)
    # Area input: resolve_area -> use area twin gates.json.
    area = None
    try:
        area = resolve_area(store, str(run_id))
    except SiteStop:
        area = None
    if area is not None:
        gates_file = area / "gates.json"
        if not gates_file.exists():
            return f"skipped: no gates.json for area {area.name}"
        report = json.loads(gates_file.read_text())
        selected = area_runs(store, area)
        if not selected:
            return "skipped: no publishable drives for area"
        build_input = selected
        build_id = hashlib.sha256(
            (gates_file.read_text() + json.dumps(selected)).encode()
        ).hexdigest()
        publish_id = build_id
    else:
        gates_file = store / str(run_id) / "gates.json"
        if not gates_file.exists():
            raise SiteStop(f"no gates.json for {run_id}: run `twin eval` first")
        report = json.loads(gates_file.read_text())
        build_input = [str(run_id)]
        publish_id = str(run_id)
        build_id = publish_id
    published = history(store)
    if published and not force:
        last = published[-1]
        if last.get("build_id", last.get("run_id")) == publish_id:
            return "skipped: already published"
        improve, reason = _improves(report, published[-1], store)
        if not improve:
            return f"skipped: worse: {reason}"
    token = None if dry_run else read_token()
    build(build_input, store, report, web)
    if dry_run:
        return f"dry run: built {web / 'out'}, nothing deployed"
    deploy(token, web)
    _record(
        store,
        {
            "run_id": publish_id,
            "build_id": build_id,
            "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "verdict": report["verdict"],
            "margins": margins(report),
            "go_count": go_count(report),
            "margin_sum": margin_sum(report),
            # An area build is rebuilt in place, so keep its runs and report to rebuild / later (#222).
            "runs": build_input,
            "report": report,
        },
    )
    return f"published {publish_id}"


def entry_inputs(store: Path, entry: dict) -> tuple[list[str], dict]:
    """The runs and gate report a history entry was published from (single-run entries predate #222)."""
    if "runs" in entry:
        return entry["runs"], entry["report"]
    return [entry["run_id"]], json.loads((Path(store) / entry["run_id"] / "gates.json").read_text())


def _build_and_deploy(runs: list[str], store: Path, report: dict, web: Path, dry_run: bool) -> bool:
    """Build the site from runs and report; deploy unless dry_run. True when deployed."""
    token = None if dry_run else read_token()
    build(runs, store, report, web)
    if dry_run:
        return False
    deploy(token, web)
    return True


def rollback(store: Path, dry_run: bool = False, web: Path = WEB) -> str:
    """Republish the run published before the current one."""
    past = history(Path(store))
    if not past:
        raise SiteStop("nothing has been published")
    earlier = [e for e in past if e["run_id"] != past[-1]["run_id"]]
    if not earlier:
        raise SiteStop("no earlier published run to roll back to")
    entry = earlier[-1]
    if "runs" not in entry:  # published before #222: a single run id
        return publish_run(Path(store), entry["run_id"], dry_run, force=True, web=web)
    runs, report = entry_inputs(Path(store), entry)
    if not _build_and_deploy(runs, Path(store), report, web, dry_run):
        return f"dry run: built {web / 'out'}, nothing deployed"
    _record(Path(store), {**entry, "published_at": datetime.now(UTC).isoformat(timespec="seconds")})
    return f"rolled back to {entry['run_id']}"


def redeploy(store: Path, dry_run: bool = False, web: Path = WEB) -> str:
    """Rebuild the last published entry with the current web/ code and deploy it. No new history entry:
    the last one gets redeployed_at (#247)."""
    store = Path(store)
    past = history(store)
    if not past:
        raise SiteStop("nothing has been published")
    last = past[-1]
    runs, report = entry_inputs(store, last)
    if not _build_and_deploy(runs, store, report, web, dry_run):
        return f"dry run: built {web / 'out'}, nothing deployed"
    past[-1] = {**last, "redeployed_at": datetime.now(UTC).isoformat(timespec="seconds")}
    _history_file(store).write_text(json.dumps(past, indent=2) + "\n")
    return f"redeployed {last['run_id']}"


def site_command(
    action: str,
    run_id: str | None,
    dry_run: bool,
    store: Path | None,
    latest: str | None = None,
) -> int:
    store = store or default_store()
    try:
        if latest:
            print(publish_latest(store, latest, dry_run))
        elif action == "history":
            for e in history(store):
                print(e["published_at"], e["run_id"], e["verdict"])
        elif action == "rollback":
            print(rollback(store, dry_run))
        elif action == "redeploy":
            print(redeploy(store, dry_run))
        elif run_id:
            print(publish_run(store, run_id, dry_run))
        else:
            print("twin site publish: needs a run id", file=sys.stderr)
            return 2
    except SiteStop as exc:
        print(f"twin site: {exc}", file=sys.stderr)
        return 1
    return 0


# ---- Latest build view: every area evaluation, whatever the verdict (issue #192) ----
# The GO-published twin above is unchanged. Beside it the site serves /latest, which reads
# web/public/latest-build/{scorecard,trend}.json and cloud.bin, staged from <store>/published/latest/.
# A deploy replaces all site assets, so every deploy (GO publish or latest) restages the latest bundle.

LATEST_DIR = "latest-build"
MAX_BUNDLE_BYTES = 25 * 1024 * 1024  # whole latest bundle, as the issue's size cap
CLOUD_TARGET_POINTS = 1_500_000  # 7 bytes a point: about 10 MB
CLOUD_PRESAMPLE = (
    8_000_000  # stride-sample first so a 100 M point cloud decimates in seconds
)
TREND_KEEP = 200


def latest_dir(store: Path) -> Path:
    return Path(store) / "published" / "latest"


def resolve_area(store: Path, area: str) -> Path:
    """AREA as a path, as `areas/<name>` or `<name>` under the store, or `<name>` under <store>/areas."""
    for cand in (Path(area), Path(store) / area, Path(store) / "areas" / area):
        if (cand / "merged.npz").is_file():
            return cand
    raise SiteStop(f"no merged area build for {area!r} (looked for merged.npz)")


def decimate_cloud(npz, target: int = CLOUD_TARGET_POINTS) -> tuple[bytes, dict]:
    """Voxel-thin the merged cloud to at most `target` points and quantise to 7 bytes a point:
    uint16 x, y, z (each over its own extent) then uint8 drive. Returns (bytes, meta)."""
    with np.load(npz) as z:
        n_total = len(z["x"])
        step = max(1, math.ceil(n_total / CLOUD_PRESAMPLE))
        pts = np.column_stack([z[k][::step] for k in "xyz"]).astype(np.float64)
        drive = z["drive"][::step]
    lo = pts.min(axis=0)
    span = np.maximum(pts.max(axis=0) - lo, 1e-6)
    voxel = 0.2
    while True:
        cells = np.floor((pts - lo) / voxel).astype(np.int64)
        dims = cells.max(axis=0) + 1
        keys = (cells[:, 0] * dims[1] + cells[:, 1]) * dims[2] + cells[:, 2]
        _, keep = np.unique(keys, return_index=True)
        if len(keep) <= target:
            break
        voxel *= 1.25
    keep.sort()
    q = np.round((pts[keep] - lo) / span * 65535).astype("<u2")
    data = b"".join(
        [q[:, i].tobytes() for i in range(3)]
        + [np.minimum(drive[keep], 255).astype(np.uint8).tobytes()]
    )
    meta = {
        "n_points": len(keep),
        "n_total": int(n_total),
        "voxel_m": round(voxel, 3),
        "origin": [float(v) for v in lo],
        "span": [float(v) for v in span],
        "bytes": len(data),
    }
    return data, meta


def _metric_values(report: dict) -> dict[str, float]:
    return {
        c["metric"]: c["value"]
        for g in report["gates"].values()
        for c in g["checks"]
        if c["value"] is not None
    }


def latest_trend(store: Path) -> list[dict]:
    path = latest_dir(store) / "trend.json"
    return json.loads(path.read_text()) if path.exists() else []


def latest_payload(store: Path, area: str, now: datetime | None = None) -> dict:
    """Stage the latest-build bundle in <store>/published/latest/ and return its description.
    Pure file work (no Node, no network): this is what `--dry-run` shows."""
    store = Path(store)
    src = resolve_area(store, area)
    gates_file = src / "gates.json"
    if not gates_file.is_file():
        raise SiteStop(f"no gates.json in {src}: run `twin eval` first")
    report = json.loads(gates_file.read_text())
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    cloud, cmeta = decimate_cloud(src / "merged.npz")
    drives_file = src / "drives.json"
    drives = json.loads(drives_file.read_text()) if drives_file.is_file() else []
    scorecard = {
        "area": src.name,
        "built_at": datetime.fromtimestamp(
            (src / "merged.npz").stat().st_mtime, UTC
        ).isoformat(timespec="seconds"),
        "published_at": at,
        "run_id": report["run_id"],
        "verdict": report["verdict"],
        "gate_passed": report["verdict"] == GO,
        "gates_version": report["gates_version"],
        "gates": report["gates"],
        "cloud": cmeta,
        "drives": [
            {
                k: d.get(k)
                for k in (
                    "index",
                    "scene",
                    "date",
                    "n_points",
                    "role",
                    "fitness",
                    "rmse_m",
                )
            }
            for d in drives
        ],
    }
    trend = latest_trend(store)
    entry = {
        "built_at": scorecard["built_at"],
        "verdict": report["verdict"],
        "metrics": _metric_values(report),
    }
    if trend and trend[-1]["built_at"] == entry["built_at"]:
        trend[-1] = entry  # the same build evaluated again: replace, do not repeat
    else:
        trend.append(entry)
    trend = trend[-TREND_KEEP:]
    files = {
        "scorecard.json": json.dumps(scorecard, indent=1).encode(),
        "trend.json": json.dumps(trend, indent=1).encode(),
        "cloud.bin": cloud,
    }
    health_file = store / "health.json"
    if health_file.is_file():  # pipeline status card (#200): the public copy, no errors or paths
        from twin import health

        files["health.json"] = json.dumps(health.public(json.loads(health_file.read_text())), indent=1).encode()
    size = sum(map(len, files.values()))
    if size > MAX_BUNDLE_BYTES:
        raise SiteStop(
            f"latest bundle is {size} bytes, over the {MAX_BUNDLE_BYTES} byte cap"
        )
    out = latest_dir(store)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    return {
        "area": src.name,
        "verdict": report["verdict"],
        "built_at": scorecard["built_at"],
        "files": {k: len(v) for k, v in files.items()},
        "bytes": size,
        "n_points": cmeta["n_points"],
    }


def stage_latest_into(store: Path, web: Path = WEB) -> bool:
    """Copy the staged latest bundle into web/public so the next build ships it."""
    dst = web / "public" / LATEST_DIR
    shutil.rmtree(dst, ignore_errors=True)
    src = latest_dir(store)
    if not (src / "scorecard.json").exists():
        return False
    dst.mkdir(parents=True)
    for name in ("scorecard.json", "trend.json", "cloud.bin", "health.json"):
        if (src / name).is_file():
            shutil.copy(src / name, dst / name)
    return True


def build_latest(store: Path, web: Path = WEB) -> None:
    """Static export carrying the latest bundle and, unchanged, the last GO-published showcase."""
    if not shutil.which("npm", path=node_env()["PATH"]):
        raise SiteStop(
            "npm not found: Node is needed to build web/ (not installed on this machine)"
        )
    past = history(store)
    showcase = web / "public" / "showcase"
    shutil.rmtree(showcase, ignore_errors=True)
    if past:
        runs, report = entry_inputs(store, past[-1])
        try:
            publish.publish_runs(runs, showcase, store)
        except (OSError, ValueError) as exc:
            raise SiteStop(
                f"cannot rebuild the published showcase from {','.join(runs)}: {exc}"
            ) from exc
        write_status(showcase, report, past[-1]["published_at"])
    stage_latest_into(store, web)
    if not (web / "node_modules").exists():
        _run(["npm", "ci"], web)
    _run(["npm", "run", "build"], web)


def publish_latest(
    store: Path, area: str, dry_run: bool = False, web: Path = WEB
) -> str:
    """Stage the area's latest build and deploy it to the site's /latest view, whatever the verdict.
    Returns a status line. Raises SiteStop when it cannot go on."""
    store = Path(store)
    token = None if dry_run else read_token()
    info = latest_payload(store, area)
    build_latest(store, web)
    mb = info["bytes"] / 1e6
    line = f"{info['area']} {info['verdict']}, {info['n_points']} points, {mb:.1f} MB"
    if dry_run:
        return f"dry run: built {web / 'out'}, nothing deployed ({line})"
    deploy(token, web)
    return f"published latest build: {line}"
