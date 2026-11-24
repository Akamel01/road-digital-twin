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
from typing import NamedTuple

import numpy as np

from twin import prgate, publish, score
from twin.areastore import MERGED_NAME, open_area
from twin.contracts import stage_dir
from twin.gates import GO, GateReport
from twin.runner import default_store
from twin.runrecord import read_record, record_path

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
        "checks_passed": GateReport(report).passed,
        "checks_total": GateReport(report).total,
    }
    (showcase / "status.json").write_text(json.dumps(status, indent=2) + "\n")


class NodeWeb:
    """The web toolchain: export() writes the static site to web/out, deploy() ships it to Cloudflare.
    Tests pass a fake with the same two methods and a `web` folder."""

    def __init__(self, web: Path = WEB):
        self.web = web

    def export(self) -> None:
        if not shutil.which("npm", path=node_env()["PATH"]):
            raise SiteStop(
                "npm not found: Node is needed to build web/ (not installed on this machine)"
            )
        if not (self.web / "node_modules").exists():
            _run(["npm", "ci"], self.web)
        _run(["npm", "run", "build"], self.web)

    def deploy(self) -> None:
        env = node_env({"CLOUDFLARE_API_TOKEN": read_token()})
        env.setdefault("CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
        _run(["npx", "-y", WRANGLER, "deploy"], self.web, env)


def _ship(
    store: Path,
    web: Path,
    toolchain,
    showcase_from: tuple[list[str], dict, str] | None,
    dry_run: bool,
    detail: str | None = None,
) -> str | None:
    """Stage the showcase (runs, gate report, published_at) and the latest bundle into web/public, export,
    then deploy. A dry run stops before the deploy and returns its status line; a deploy returns None."""
    toolchain = toolchain or NodeWeb(web)
    showcase = web / "public" / "showcase"
    shutil.rmtree(showcase, ignore_errors=True)
    files = 0
    if showcase_from:
        runs, report, at = showcase_from
        try:
            _area, pub_report = publish.publish_runs(runs, showcase, store)
        except (OSError, ValueError) as exc:
            raise SiteStop(f"cannot build the showcase from {','.join(runs)}: {exc}") from exc
        write_status(showcase, report, at)
        files = getattr(pub_report, "total_files", 0)
    stage_latest_into(store, web)
    toolchain.export()
    if not dry_run:
        toolchain.deploy()
        return None
    return f"dry run: built {web / 'out'}, nothing deployed ({detail or f'files={files}'})"


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


# Margin-sum noise between rebuilds of the same code (seen 0.005); within it a build counts as a tie and
# publishes, so merged code reaches the site. Operator, 2026-11-16: "publish if not worse".
TIE_MARGIN = 0.01


def _score_or_none(store, target_dir, baseline_doc):
    try:
        doc, reason = score.score_target(store, target_dir, sites="audit", baseline=baseline_doc)
    except score.SCORE_ERRORS as exc:
        print(f"publish: score failed ({exc}); comparing gate margins", file=sys.stderr)
        return None
    if doc is None:
        print(f"publish: cannot score ({reason}); comparing gate margins", file=sys.stderr)
    return doc


def _already_published(past: list[dict], publish_id: str) -> bool:
    return bool(past) and past[-1].get("build_id", past[-1].get("run_id")) == publish_id


class Decision(NamedTuple):
    publish: bool
    reason: str  # why not, when publish is False
    note: str = ""  # a diagnostic for stderr (a fallback was taken)


def decide(candidate: dict, past: list[dict], score_doc, *, publish_id: str, force: bool) -> Decision:
    """The publish rule (#292 item 18): no element worse beyond the noise, ties publish. Pure: the caller
    computes score_doc (None when unavailable) and acts on the answer."""
    if not past or force:
        return Decision(True, "")
    last = past[-1]
    if _already_published(past, publish_id):
        return Decision(False, "already published")
    pub_gc = last.get("go_count")
    pub_ms = last.get("margin_sum")
    if pub_gc is None or pub_ms is None:
        return Decision(True, "")
    cand_gc = GateReport(candidate).passed
    if cand_gc < pub_gc:
        return Decision(False, f"worse: fewer gate checks pass ({cand_gc} vs {pub_gc})")
    note = ""
    if score_doc is not None and last.get("score") is not None:
        cmp = score_doc.get("compare") or {}
        if cmp.get("comparable") is not False:
            if cmp.get("publish") is True:
                return Decision(True, "")
            return Decision(False, f"worse: {cmp.get('reason') or 'per-element score worse'}")
        note = "baseline score not comparable (label sites changed): comparing gate margins"
    else:
        note = "no per-element score for the candidate and the published run: comparing gate margins"
    cand_ms = GateReport(candidate).score()
    if cand_ms >= pub_ms - TIE_MARGIN:
        return Decision(True, "", note)
    return Decision(False, f"worse: margin sum {cand_ms:g} is worse than published {pub_ms:g}", note)


def area_runs(store: Path, area) -> list[str]:
    """For each drive of the area build, the newest full single-drive run (prgate.pick_baseline) that has
    every public file; drives without one are left out and logged."""
    store = Path(store)
    area = area if isinstance(area, Path) else cloud_build(store, str(area))
    selected: list[str] = []
    for scene in open_area(store, area).drive_tokens():
        base = prgate.pick_baseline(store, scene=scene)
        if base is None:
            print(f"publish: skip drive scene {scene}: no baseline", file=sys.stderr)
            continue
        run_dir = Path(base)
        manifest_file = record_path(run_dir)
        public_ok = manifest_file.exists()
        if public_ok:
            try:
                read_record(run_dir)
            except (OSError, ValueError):
                public_ok = False
        if public_ok:
            public_ok = all(
                (stage_dir(run_dir, "outputs") / name).exists()
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
    toolchain=None,
) -> str:
    """Publish run_id (or an area name) if it improves on the published run. Returns a status line;
    a skip returns "skipped: reason". Raises SiteStop when it cannot go on."""
    store = Path(store)
    # Area input: a build holding the merged cloud -> use its gates.json.
    area = None
    try:
        area = cloud_build(store, str(run_id))
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
    target_dir = area if area is not None else store / str(run_id)
    published = history(store)
    baseline_doc = published[-1].get("score") if published else None
    score_doc = None
    if not dry_run:
        if force or not _already_published(published, publish_id):  # a no-op publish is not scored
            score_doc = _score_or_none(store, target_dir, baseline_doc)
        decision = decide(report, published, score_doc, publish_id=publish_id, force=force)
        if decision.note:
            print(f"publish: {decision.note}", file=sys.stderr)
        if not decision.publish:
            return f"skipped: {decision.reason}"
    at = datetime.now(UTC).isoformat(timespec="seconds")
    line = _ship(store, web, toolchain, (build_input, report, at), dry_run)
    if line:
        return line
    _record(
        store,
        {
            "run_id": publish_id,
            "build_id": build_id,
            "published_at": at,
            "verdict": report["verdict"],
            "margins": GateReport(report).rooms(),
            "go_count": GateReport(report).passed,
            "margin_sum": GateReport(report).score(),
            "score": score_doc,
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


def rollback(store: Path, dry_run: bool = False, web: Path = WEB, toolchain=None) -> str:
    """Republish the run published before the current one."""
    past = history(Path(store))
    if not past:
        raise SiteStop("nothing has been published")
    earlier = [e for e in past if e["run_id"] != past[-1]["run_id"]]
    if not earlier:
        raise SiteStop("no earlier published run to roll back to")
    entry = earlier[-1]
    if "runs" not in entry:  # published before #222: a single run id
        return publish_run(Path(store), entry["run_id"], dry_run, force=True, web=web, toolchain=toolchain)
    runs, report = entry_inputs(Path(store), entry)
    at = datetime.now(UTC).isoformat(timespec="seconds")
    line = _ship(Path(store), web, toolchain, (runs, report, at), dry_run)
    if line:
        return line
    _record(Path(store), {**entry, "published_at": at})
    return f"rolled back to {entry['run_id']}"


def redeploy(store: Path, dry_run: bool = False, web: Path = WEB, toolchain=None) -> str:
    """Rebuild the last published entry with the current web/ code and deploy it. No new history entry:
    the last one gets redeployed_at (#247)."""
    store = Path(store)
    past = history(store)
    if not past:
        raise SiteStop("nothing has been published")
    last = past[-1]
    runs, report = entry_inputs(store, last)
    at = datetime.now(UTC).isoformat(timespec="seconds")
    line = _ship(store, web, toolchain, (runs, report, at), dry_run)
    if line:
        return line
    past[-1] = {**last, "redeployed_at": at}
    _history_file(store).write_text(json.dumps(past, indent=2) + "\n")
    return f"redeployed {last['run_id']}"


def site_command(
    action: str,
    run_id: str | None,
    dry_run: bool,
    store: Path | None,
    latest: str | None = None,
    toolchain=None,
) -> int:
    store = store or default_store()
    try:
        if latest:
            print(publish_latest(store, latest, dry_run, toolchain=toolchain))
        elif action == "history":
            for e in history(store):
                print(e["published_at"], e["run_id"], e["verdict"])
        elif action == "rollback":
            print(rollback(store, dry_run, toolchain=toolchain))
        elif action == "redeploy":
            print(redeploy(store, dry_run, toolchain=toolchain))
        elif run_id:
            print(publish_run(store, run_id, dry_run, toolchain=toolchain))
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


def cloud_build(store: Path, ref: str) -> Path:
    """The build folder REF names (see areastore.open_area) when it holds the merged cloud; SiteStop otherwise."""
    build = open_area(store, ref).cloud_dir()
    if build is None:
        raise SiteStop(f"no merged area build for {ref!r} (looked for {MERGED_NAME})")
    return build


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


def latest_trend(store: Path) -> list[dict]:
    path = latest_dir(store) / "trend.json"
    return json.loads(path.read_text()) if path.exists() else []


def latest_payload(store: Path, area: str, now: datetime | None = None) -> dict:
    """Stage the latest-build bundle in <store>/published/latest/ and return its description.
    Pure file work (no Node, no network): this is what `--dry-run` shows."""
    store = Path(store)
    src = cloud_build(store, area)
    gates_file = src / "gates.json"
    if not gates_file.is_file():
        raise SiteStop(f"no gates.json in {src}: run `twin eval` first")
    report = json.loads(gates_file.read_text())
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    cloud, cmeta = decimate_cloud(src / MERGED_NAME)
    drives = open_area(store, src).drive_records()
    scorecard = {
        "area": src.name,
        "built_at": datetime.fromtimestamp(
            (src / MERGED_NAME).stat().st_mtime, UTC
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
        "metrics": GateReport(report).values(),
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


def publish_latest(
    store: Path, area: str, dry_run: bool = False, web: Path = WEB, toolchain=None
) -> str:
    """Stage the area's latest build and deploy it to the site's /latest view, whatever the verdict. The
    site also carries, unchanged, the last GO-published showcase. Returns a status line. Raises SiteStop
    when it cannot go on."""
    store = Path(store)
    info = latest_payload(store, area)
    past = history(store)
    showcase_from = None
    if past:
        runs, report = entry_inputs(store, past[-1])
        showcase_from = (runs, report, past[-1]["published_at"])
    mb = info["bytes"] / 1e6
    line = f"{info['area']} {info['verdict']}, {info['n_points']} points, {mb:.1f} MB"
    if dry := _ship(store, web, toolchain, showcase_from, dry_run, detail=line):
        return dry
    return f"published latest build: {line}"
