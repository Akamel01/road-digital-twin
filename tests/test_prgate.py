import json

import pytest

from twin import jobqueue, prgate


def fake_gh(prs, calls):
    def gh(*args):
        calls.append(args)
        if args[0] == "pr":
            return json.dumps([{"number": n, "headRefOid": s} for n, s in prs])
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


def test_prgate_job_needs_sha(tmp_path):
    with pytest.raises(ValueError):
        jobqueue.add(tmp_path, {"type": "prgate", "pr": 5})


def _run(store, name, verdict, nogo=0, scene=prgate.SCENE, status="ok"):
    d = store / name
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"data": {"scene_token": scene}, "stages": [{"status": status}]})
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
    assert prgate.pick_baseline(tmp_path).name == "20261101-000000-aaaaaa"
    # no go anywhere: fewest no-go checks wins
    only = tmp_path / "x"
    only.mkdir()
    _run(only, "20261101-000000-aaaaaa", "no-go", 3)
    _run(only, "20261102-000000-bbbbbb", "no-go", 1)
    assert prgate.pick_baseline(only).name == "20261102-000000-bbbbbb"
    assert prgate.pick_baseline(tmp_path / "none") is None


@pytest.mark.parametrize(
    "verdict,state",
    [("go", "success"), ("no-go", "failure"), ("not measured", "success")],
)
def test_gate_posts_comment_and_status(tmp_path, monkeypatch, verdict, state):
    store, root = tmp_path / "main", tmp_path / "root"
    store.mkdir()
    _run(store, "20261101-000000-aaaaaa", "go")
    sha = "d" * 40

    def sh(cmd, cwd=None):
        if cmd[:3] == ["uv", "run", "twin"]:
            runs = root / "5-runs" / "20261110-000000-eeeeee"
            runs.mkdir(parents=True)
            (runs / "gates.json").write_text(json.dumps({"verdict": verdict}))
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
