"""Method-change gate for pull requests (ADR 0005, #154).

`twin prgate poll` lists open PRs labelled `method` (gh) and queues one `prgate` job per new head
commit. The worker runs the job: check the head out into <root>/<pr> (a separate clone), run
scene-0757 there, `twin eval` it against the best main run in the main store, then post the report
as a PR comment and set the commit status `twin-gates`.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from twin import jobqueue
from twin.gates import GO, NO_GO

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


def method_prs(repo: str = REPO, gh=gh) -> list[dict]:
    out = gh("pr", "list", "-R", repo, "--label", LABEL, "--state", "open",
             "--json", "number,headRefOid")  # fmt: skip
    return [{"pr": p["number"], "sha": p["headRefOid"]} for p in json.loads(out)]


def poll(store: Path, repo: str = REPO, dry_run: bool = False, gh=gh) -> list[str]:
    """Queue a prgate job for every method PR whose head has no job yet. Returns lines."""
    seen = {
        (j.get("pr"), j.get("sha"))
        for j in jobqueue.list_jobs(store)
        if j["type"] == "prgate"
    }
    lines = []
    for p in method_prs(repo, gh):
        if (p["pr"], p["sha"]) in seen:
            continue
        if dry_run:
            lines.append(f"would queue PR #{p['pr']} {p['sha'][:7]}")
            continue
        job = {"type": "prgate", "pr": p["pr"], "sha": p["sha"], "repo": repo}
        lines.append(f"queued {jobqueue.add(store, job)} PR #{p['pr']} {p['sha'][:7]}")
    return lines


def pick_baseline(store: Path, scene: str = SCENE) -> Path | None:
    """The main-store run to compare with: finished runs of the scene, a go verdict first,
    then fewest no-go checks, then the newest."""
    best, best_key = None, None
    for d in sorted(Path(store).glob("2*")):
        try:
            m = json.loads((d / "manifest.json").read_text())
        except (OSError, ValueError):
            continue
        stages = m.get("stages", [])
        if m.get("data", {}).get("scene_token") != scene or any(
            s.get("status") != "ok" for s in stages
        ) or not stages:  # fmt: skip
            continue
        try:
            rep = json.loads((d / "gates.json").read_text())
            checks = [c["status"] for g in rep["gates"].values() for c in g["checks"]]
            key = (rep["verdict"] == GO, -checks.count(NO_GO))
        except (OSError, ValueError, KeyError):
            key = (False, -99)
        if best_key is None or key >= best_key:  # sorted by id: ties go to the newest
            best, best_key = d, key
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


def set_status(repo, sha, state, text, dry_run, gh=gh) -> None:
    if dry_run:
        print(f"[dry-run] status {CONTEXT}={state}: {text}")
    else:
        gh(*status_args(repo, sha, state, text))


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
