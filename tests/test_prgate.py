import json

import pytest

from twin import jobqueue, prgate
from twin.contracts import STAGE_NAMES


def fake_gh(prs, calls):
    def gh(*args):
        calls.append(args)
        if args[:2] == ("pr", "diff"):
            return "twin/stages/ground.py\ntests/test_ground.py\n"
        if args[0] == "pr":
            return json.dumps(
                [
                    {"number": n, "headRefOid": s, "labels": [{"name": "method"}]}
                    for n, s in prs
                ]
            )
        if args[-1] == "--paginate":
            return json.dumps([{"id": 7, "body": prgate.MARKER + " old"}])
        return ""

    return gh


def test_poll_queues_once_per_head(tmp_path):
    calls = []
    gh = fake_gh([(5, "a" * 40)], calls)
    assert len(prgate.poll(tmp_path, gh=gh)) == 1
    assert prgate.poll(tmp_path, gh=gh) == []  # same head: no second job
    gh = fake_gh([(5, "b" * 40)], calls)
    assert len(prgate.poll(tmp_path, gh=gh)) == 1  # head moved
    assert [j["type"] for j in jobqueue.list_jobs(tmp_path)] == ["prgate"] * 2
    assert prgate.poll(tmp_path, dry_run=True, gh=fake_gh([(9, "c" * 40)], calls))[
        0
    ].startswith("would")
    assert len(jobqueue.list_jobs(tmp_path)) == 2


def test_poll_marks_other_prs_na(tmp_path):
    calls = []

    def gh(*args):
        calls.append(args)
        return json.dumps([{"number": 3, "headRefOid": "e" * 40, "labels": []}])

    assert prgate.poll(tmp_path, gh=gh) == []
    assert "state=success" in calls[-1] and jobqueue.list_jobs(tmp_path) == []
    posts = sum("state=success" in c for c in calls)
    prgate.poll(tmp_path, gh=gh)  # a second poll of the same head posts nothing new
    assert sum("state=success" in c for c in calls) == posts


def test_prgate_job_needs_sha(tmp_path):
    with pytest.raises(ValueError):
        jobqueue.add(tmp_path, {"type": "prgate", "pr": 5})


def _run(store, name, verdict, nogo=0, scene=prgate.SCENE, status="ok", stages=None):
    d = store / name
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"data": {"scene_token": scene, "nuscenes_version": "v1.0-mini"},
                    "stages": [{"name": n, "status": status} for n in (stages or STAGE_NAMES)]})
    )
    if verdict:
        checks = [{"status": "no-go"}] * nogo
        rep = {"verdict": verdict, "gates": {"G1": {"checks": checks}}}
        (d / "gates.json").write_text(json.dumps(rep))


def test_pick_baseline(tmp_path):
    _run(tmp_path, "20261101-000000-aaaaaa", "go")
    _run(tmp_path, "20261102-000000-bbbbbb", "no-go", 3)
    _run(tmp_path, "20261103-000000-cccccc", "go", status="running")
    _run(tmp_path, "20261104-000000-dddddd", "go", scene="other")
    # the newest finished run is current main, whatever its verdict
    assert prgate.pick_baseline(tmp_path).name == "20261102-000000-bbbbbb"
    # a stage that is off by default (skipped) does not disqualify a run
    _run(tmp_path, "20261105-000000-eeeeee", "no-go", 1, status="skipped")
    assert prgate.pick_baseline(tmp_path).name == "20261105-000000-eeeeee"
    # a partial chain (prefetch load+mask) never becomes the baseline
    _run(tmp_path, "20261106-000000-ffffff", "no-go", stages=["load", "mask"])
    assert prgate.pick_baseline(tmp_path).name == "20261105-000000-eeeeee"
    assert prgate.pick_baseline(tmp_path / "none") is None


@pytest.mark.parametrize(
    "verdict,state,worse",
    [
        ("go", "success", None),
        ("no-go", "failure", None),
        ("not measured", "success", None),
        ("no-go", "success", []),  # no-go like main, but nothing worse than the baseline
        ("no-go", "failure", [{"metric": "m"}]),
    ],
)
def test_gate_posts_comment_and_status(tmp_path, monkeypatch, verdict, state, worse):
    store, root = tmp_path / "main", tmp_path / "root"
    store.mkdir()
    _run(store, "20261101-000000-aaaaaa", "go")
    sha = "d" * 40

    def sh(cmd, cwd=None):
        if cmd[:3] == ["uv", "run", "twin"]:
            runs = root / "5-runs" / "20261110-000000-eeeeee"
            runs.mkdir(parents=True)
            rep = {"verdict": verdict} | ({} if worse is None else {"regressions": worse})
            (runs / "gates.json").write_text(json.dumps(rep))
            (runs / "gates.md").write_text("REPORT\n")
            return "20261110-000000-eeeeee\n"
        return ""

    monkeypatch.setattr(prgate, "_sh", sh)
    monkeypatch.setattr(prgate, "checkout", lambda *a: tmp_path)
    monkeypatch.setattr(prgate.subprocess, "run", lambda *a, **k: None)
    calls = []
    out = prgate.gate(store, 5, sha, "o/r", root, gh=fake_gh([], calls))
    assert out["eval_result"] == verdict
    states = [c[c.index("-f") + 1] for c in calls if any("statuses" in a for a in c)]
    assert states == ["state=pending", f"state={state}"]
    patch = [c for c in calls if "PATCH" in c]  # the existing comment is edited
    assert "REPORT" in patch[0][-1] and "comments/7" in patch[0][3]


def test_gate_error_sets_error_status(tmp_path, monkeypatch):
    def boom(*a):
        raise prgate.PrGateError("clone failed")

    monkeypatch.setattr(prgate, "checkout", boom)
    calls = []
    with pytest.raises(prgate.PrGateError):
        prgate.gate(tmp_path, 5, "d" * 40, "o/r", tmp_path, gh=fake_gh([], calls))
    assert "state=error" in calls[-1]


def test_method_pr_without_single_drive_change_is_n_a(tmp_path):
    files = {5: "twin/merge.py\ntests/test_merge.py\n", 6: "twin/params.py\n", 7: "twin/stages/ground.py\n"}
    calls = []

    def gh(*args):
        calls.append(args)
        if args[:2] == ("pr", "diff"):
            return files[int(args[2])]
        if args[0] == "pr":
            return json.dumps([{"number": n, "headRefOid": str(n) * 40, "labels": [{"name": "method"}]} for n in files])
        return ""

    lines = prgate.poll(tmp_path, gh=gh)
    assert [j["pr"] for j in jobqueue.list_jobs(tmp_path)] == [6, 7]  # merge-only PR 5 is not gated
    assert len(lines) == 2
    posts = [c for c in calls if "state=success" in c]
    assert len(posts) == 1 and "n/a: no single-drive stage changed" in " ".join(posts[0]) and "5" * 40 in " ".join(posts[0])
    prgate.poll(tmp_path, gh=gh)
    assert len([c for c in calls if "state=success" in c]) == 1  # once per head


def test_unreadable_diff_still_gates(tmp_path):
    def gh(*args):
        if args[:2] == ("pr", "diff"):
            raise prgate.PrGateError("boom")
        return json.dumps([{"number": 5, "headRefOid": "a" * 40, "labels": [{"name": "method"}]}])

    assert len(prgate.poll(tmp_path, gh=gh)) == 1
