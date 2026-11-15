"""Method-change gate for pull requests (ADR 0005, #154).

`twin prgate poll` lists open PRs labelled `method` (gh) and queues one `prgate` job per new head
commit. The worker runs the job: check the head out into <root>/<pr> (a separate clone), run
scene-0757 there, `twin eval` it against the best main run in the main store, then post the report
as a PR comment and set the commit status `twin-gates`.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from twin import jobqueue
from twin.contracts import STAGE_NAMES
from twin.gates import NO_GO

REPO = "Akamel01/road-digital-twin"
LABEL = "method"
CONTEXT = "twin-gates"
MARKER = "<!-- twin-gates -->"
SCENE = "2fc3753772e241f2ab2cd16a784cc680"  # scene-0757 in nuScenes mini
ROOT = Path.home() / "rdt-prgate"


class PrGateError(RuntimeError):
    pass


def gh(*args: str) -> str:
    try:
        done = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise PrGateError("gh is not installed on this machine") from exc
    if done.returncode:
        raise PrGateError(f"gh {' '.join(args[:2])} failed: {done.stderr.strip()}")
    return done.stdout


def open_prs(repo: str = REPO, gh=gh) -> list[dict]:
    out = gh("pr", "list", "-R", repo, "--state", "open", "--limit", "100",
             "--json", "number,headRefOid,labels")  # fmt: skip
    return [
        {
            "pr": p["number"],
            "sha": p["headRefOid"],
            "method": LABEL in [x["name"] for x in p["labels"]],
        }
        for p in json.loads(out)
    ]


SINGLE_DRIVE = ("twin/stages/", "twin/runner.py", "twin/contracts.py", "twin/params")  # path prefixes


def touches_single_drive(repo: str, pr: int, gh=gh) -> bool:
    """True when the PR's diff changes a single-drive stage, the runner or the contracts. When the diff
    cannot be read the gate runs: a skipped gate is the worse mistake."""
    try:
        files = gh("pr", "diff", str(pr), "-R", repo, "--name-only").split()
    except PrGateError:
        return True
    return any(f.startswith(SINGLE_DRIVE) for f in files)


def poll(store: Path, repo: str = REPO, dry_run: bool = False, gh=gh, extra: dict | None = None) -> list[str]:
    """Queue a prgate job for every method PR whose head has no job yet. Other open PRs get
    a success status `twin-gates` (n/a), so the check can be required on main. Returns lines."""
    seen = {
        (j.get("pr"), j.get("sha"))
        for j in jobqueue.list_jobs(store)
        if j["type"] == "prgate"
    }
    lines = []
    na_file = Path(store) / "queue" / "prgate-na.json"
    na = set(json.loads(na_file.read_text())) if na_file.exists() else set()
    for p in open_prs(repo, gh):
        why = "n/a: not a method PR"
        if p["method"] and (p["pr"], p["sha"]) not in seen and not touches_single_drive(repo, p["pr"], gh):
            why = "n/a: no single-drive stage changed"  # e.g. a merge-only PR: the scene-0757 run would not differ
        if why != "n/a: not a method PR" or not p["method"]:
            if p["sha"] in na:
                continue
            if set_status(repo, p["sha"], "success", why, dry_run, gh) and not dry_run:
                na.add(p["sha"])
                na_file.parent.mkdir(parents=True, exist_ok=True)
                na_file.write_text(json.dumps(sorted(na)))
            continue
        if (p["pr"], p["sha"]) in seen:
            continue
        if dry_run:
            lines.append(f"would queue PR #{p['pr']} {p['sha'][:7]}")
            continue
        job = {"type": "prgate", "pr": p["pr"], "sha": p["sha"], "repo": repo, **(extra or {})}
        lines.append(f"queued {jobqueue.add(store, job)} PR #{p['pr']} {p['sha'][:7]}")
    return lines


def pick_baseline(store: Path, scene: str = SCENE) -> Path | None:
    """The main-store run to compare with: the newest full run of the scene on the worker's
    dataset version whose stages all finished (ok, or skipped when off by default). The newest
    is current main, so a PR is compared with what it would replace."""
    best = None
    for d in sorted(Path(store).glob("2*")):
        try:
            m = json.loads((d / "manifest.json").read_text())
        except (OSError, ValueError):
            continue
        if m.get("parent") is not None:
            continue  # reruns are not baselines
        if m.get("data", {}).get("nuscenes_version") != os.environ.get(
            "NUSCENES_VERSION", "v1.0-mini"
        ):
            continue  # different dataset version
        stages = m.get("stages", [])
        if m.get("data", {}).get("scene_token") != scene or not stages or any(
            s.get("status") not in ("ok", "skipped") for s in stages
        ):  # fmt: skip
            continue
        if {s.get("name") for s in stages} != set(STAGE_NAMES):
            continue  # a partial chain (e.g. P4 prefetch, stop_after) is not a baseline
        if (d / "gates.json").exists():
            best = d  # sorted by id: the last one is the newest
    return best


def _sh(cmd: list[str], cwd: Path | None = None) -> str:
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode:
        tail = (done.stderr or done.stdout).strip()[-500:]
        raise PrGateError(f"{' '.join(cmd[:3])} exited {done.returncode}: {tail}")
    return done.stdout


def checkout(repo: str, pr: int, sha: str, root: Path) -> Path:
    clone = Path(root) / str(pr)
    if not (clone / ".git").is_dir():
        _sh(["git", "clone", "-q", f"https://github.com/{repo}.git", str(clone)])
    _sh(["git", "fetch", "-q", "origin", f"pull/{pr}/head"], clone)
    _sh(["git", "checkout", "-q", "-f", "--detach", sha], clone)
    if _sh(["git", "rev-parse", "HEAD"], clone).strip() != sha:
        raise PrGateError(
            f"PR #{pr}: head is not {sha[:7]} (it moved; next poll reruns)"
        )
    return clone


def status_args(repo: str, sha: str, state: str, text: str) -> list[str]:
    return ["api", "-X", "POST", f"repos/{repo}/statuses/{sha}", "-f", f"state={state}",
            "-f", f"context={CONTEXT}", "-f", f"description={text[:140]}"]  # fmt: skip


CAP = "reached the maximum number of statuses"


def set_status(repo, sha, state, text, dry_run, gh=gh) -> bool:
    """Post a commit status. True when it is on GitHub, or can never be (the SHA is at GitHub's
    per-SHA cap of 1000). Other errors are logged and return False: posting never kills a poll."""
    if dry_run:
        print(f"[dry-run] status {CONTEXT}={state}: {text}")
        return True
    try:
        gh(*status_args(repo, sha, state, text))
    except Exception as exc:  # noqa: BLE001
        if CAP in str(exc):
            return True
        print(f"prgate: set_status failed for {sha[:7]}: {exc}", file=sys.stderr)
        return False
    return True


def post_comment(repo: str, pr: int, body: str, dry_run: bool, gh=gh) -> None:
    """One comment per PR: edit ours when it exists."""
    if dry_run:
        print(f"[dry-run] comment on #{pr}:\n{body}")
        return
    found = json.loads(gh("api", f"repos/{repo}/issues/{pr}/comments", "--paginate"))
    mine = [c for c in found if MARKER in c["body"]]
    if mine:
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{mine[-1]['id']}",
           "-f", f"body={body}")  # fmt: skip
    else:
        gh("api", f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}")


def gate(store, pr, sha, repo=REPO, root=ROOT, dry_run=False, gh=gh) -> dict:
    """Run the gate for one PR head. Posts a result; on failure posts an error status."""
    store, root = Path(store), Path(root)
    set_status(repo, sha, "pending", "twin gates running on scene-0757", dry_run, gh)
    try:
        clone = checkout(repo, pr, sha, root)
        runs = root / f"{pr}-runs"  # this PR's run store, replaced on every head
        shutil.rmtree(runs, ignore_errors=True)
        _sh(["uv", "sync", "-q"], clone)
        run_id = _sh(["uv", "run", "twin", "run", "--scene", SCENE, "--store", str(runs)],
                     clone).split()[-1]  # fmt: skip
        base = pick_baseline(store)
        cmd = [sys.executable, "-m", "twin.cli", "eval", str(runs / run_id)]
        if base:
            cmd += ["--baseline", str(base)]
        subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )  # exit 1 = no-go
        report = json.loads((runs / run_id / "gates.json").read_text())
        text = (runs / run_id / "gates.md").read_text()
    except Exception as exc:
        set_status(repo, sha, "error", f"{type(exc).__name__}: {exc}", dry_run, gh)
        raise
    verdict = report["verdict"]
    head = f"{MARKER}\n**twin-gates** for `{sha[:7]}` on scene-0757. Baseline "
    head += f"`{base.name if base else 'none'}` (main store). A go still needs line-by-line review.\n\n"  # fmt: skip
    post_comment(repo, pr, head + text, dry_run, gh)
    # Only a failed gate or a regression blocks; "not measured" is not a no-go (it blocks publish only).
    # While main itself is no-go, an absolute verdict blocks every method PR. With a baseline, block
    # only a regression against it (gates.regressions, noise tolerance); the operator reviews the rest.
    worse = report.get("regressions")
    if base is not None and worse is not None:
        ok = not worse
        desc = f"{verdict}, {len(worse)} regression(s) vs baseline {base.name}: run {run_id}"
    else:
        ok = verdict != NO_GO
        desc = f"{verdict}: run {run_id}, baseline {base.name if base else 'none'}"
    set_status(repo, sha, "success" if ok else "failure", desc, dry_run, gh)
    return {"eval_result": verdict, "run_id": run_id, "pr": pr}


def prgate_command(args) -> int:
    from twin.runner import default_store

    store = args.store or default_store()
    try:
        if args.action == "poll":
            for line in poll(store, args.repo, args.dry_run):
                print(line)
        else:
            if not (args.pr and args.sha):
                raise PrGateError("run needs a PR number and a head sha")
            out = gate(store, args.pr, args.sha, args.repo, args.root, args.dry_run)
            print(out)
    except PrGateError as exc:
        print(f"twin prgate: {exc}", file=sys.stderr)
        return 2
    return 0
