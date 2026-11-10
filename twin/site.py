"""Auto-publish the public site (ADR 0005): a run that is GO on every gate and beats the
published run goes to twin.papyrus-ai.net. History of published runs: <store>/published/history.json.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

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
    action: str, run_id: str | None, dry_run: bool, store: Path | None
) -> int:
    store = store or default_store()
    try:
        if action == "history":
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
