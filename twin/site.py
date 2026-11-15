"""Auto-publish the public site (ADR 0005): a run that is GO on every gate and beats the
published run goes to twin.papyrus-ai.net. History of published runs: <store>/published/history.json.
"""

import json
import math
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from twin.gates import GO
from twin.publish import publish_runs
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


def build(run_id: str, store: Path, report: dict, web: Path = WEB) -> None:
    """Showcase bundle, status.json and the static export in web/out."""
    if not shutil.which("npm", path=node_env()["PATH"]):
        raise SiteStop(
            "npm not found: Node is needed to build web/ (not installed on this machine)"
        )
    showcase = web / "public" / "showcase"
    shutil.rmtree(showcase, ignore_errors=True)
    try:
        publish_runs([run_id], showcase, store)
    except (OSError, ValueError) as exc:
        raise SiteStop(f"cannot build the showcase from {run_id}: {exc}") from exc
    stage_latest_into(store, web)
    status = {
        "run_id": run_id,
        "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "verdict": report["verdict"],
        "gates_version": report["gates_version"],
    }
    (showcase / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    if not (web / "node_modules").exists():
        _run(["npm", "ci"], web)
    _run(["npm", "run", "build"], web)


def deploy(token: str, web: Path = WEB) -> None:
    env = node_env({"CLOUDFLARE_API_TOKEN": token})
    env.setdefault("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    _run(["npx", "-y", WRANGLER, "deploy"], web, env)


def publish_run(
    store: Path,
    run_id: str,
    dry_run: bool = False,
    force: bool = False,
    web: Path = WEB,
) -> str:
    """Publish run_id if it is GO and beats the published run. Returns a status line;
    a skip returns "skipped: reason". Raises SiteStop when it cannot go on."""
    store = Path(store)
    gates_file = store / run_id / "gates.json"
    if not gates_file.exists():
        raise SiteStop(f"no gates.json for {run_id}: run `twin eval` first")
    report = json.loads(gates_file.read_text())
    if report["verdict"] != GO:
        return f"skipped: verdict is {report['verdict']}"
    published = history(store)
    if published and not force:
        if published[-1]["run_id"] == run_id:
            return "skipped: already published"
        why = beats(margins(report), published[-1]["margins"])
        if why:
            return f"skipped: {why}"
    token = None if dry_run else read_token()
    build(run_id, store, report, web)
    if dry_run:
        return f"dry run: built {web / 'out'}, nothing deployed"
    deploy(token, web)
    _record(
        store,
        {
            "run_id": run_id,
            "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "verdict": report["verdict"],
            "margins": margins(report),
        },
    )
    return f"published {run_id}"


def rollback(store: Path, dry_run: bool = False, web: Path = WEB) -> str:
    """Republish the run published before the current one."""
    past = history(Path(store))
    if not past:
        raise SiteStop("nothing has been published")
    earlier = [e for e in past if e["run_id"] != past[-1]["run_id"]]
    if not earlier:
        raise SiteStop("no earlier published run to roll back to")
    return publish_run(Path(store), earlier[-1]["run_id"], dry_run, force=True, web=web)


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
    for name in ("scorecard.json", "trend.json", "cloud.bin"):
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
        run_id = past[-1]["run_id"]
        report = json.loads((Path(store) / run_id / "gates.json").read_text())
        try:
            publish_runs([run_id], showcase, store)
        except (OSError, ValueError) as exc:
            raise SiteStop(
                f"cannot rebuild the published showcase from {run_id}: {exc}"
            ) from exc
        status = {
            "run_id": run_id,
            "published_at": past[-1]["published_at"],
            "verdict": report["verdict"],
            "gates_version": report["gates_version"],
        }
        (showcase / "status.json").write_text(json.dumps(status, indent=2) + "\n")
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
