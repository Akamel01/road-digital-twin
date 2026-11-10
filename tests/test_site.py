import json

import pytest

from twin import jobqueue, site
from twin.cli import main


def report(verdict="go", marking=0.2, cov=0.8):
    checks = [
        {
            "metric": "accuracy.elements.markings.p95_m",
            "op": "<=",
            "threshold": 0.3,
            "value": marking,
        },
        {
            "metric": "accuracy.elements.markings.coverage",
            "op": ">=",
            "threshold": 0.7,
            "value": cov,
        },
    ]
    return {
        "run_id": "x",
        "verdict": verdict,
        "gates_version": 1,
        "gates": {"G5": {"name": "Accuracy", "status": verdict, "checks": checks}},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A store, a fake build and deploy that record their calls, and a token file."""
    calls = []
    monkeypatch.setattr(
        site,
        "build",
        lambda run_id, store, rep, web=None: calls.append(("build", run_id)),
    )
    monkeypatch.setattr(
        site, "deploy", lambda token, web=None: calls.append(("deploy", token))
    )
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    store = tmp_path / "store"

    def run(run_id, **kw):
        (store / run_id).mkdir(parents=True, exist_ok=True)
        (store / run_id / "gates.json").write_text(json.dumps(report(**kw)))
        return run_id

    return store, calls, run, token


def test_go_first_run_publishes(env):
    store, calls, run, _ = env
    assert site.publish_run(store, run("r1")) == "published r1"
    assert calls == [("build", "r1"), ("deploy", "secret")]
    assert site.history(store)[-1]["run_id"] == "r1"


def test_better_publishes_worse_or_equal_skips(env):
    store, _calls, run, _ = env
    site.publish_run(store, run("r1"))
    assert site.publish_run(store, run("r2", marking=0.1)) == "published r2"
    assert site.publish_run(store, run("r3", marking=0.1)).startswith(
        "skipped"
    )  # equal
    assert "worse" in site.publish_run(
        store, run("r4", marking=0.1, cov=0.75)
    )  # one worse
    assert [e["run_id"] for e in site.history(store)] == ["r1", "r2"]


def test_no_go_skips(env):
    store, calls, run, _ = env
    assert (
        site.publish_run(store, run("r1", verdict="no-go"))
        == "skipped: verdict is no-go"
    )
    assert calls == []


def test_missing_token_stops_with_message(env):
    store, calls, run, token = env
    token.unlink()
    with pytest.raises(site.SiteStop, match="no Cloudflare token at"):
        site.publish_run(store, run("r1"))
    assert calls == [] and site.history(store) == []


def test_dry_run_builds_without_token_or_deploy(env):
    store, calls, run, token = env
    token.unlink()
    assert site.publish_run(store, run("r1"), dry_run=True).startswith("dry run")
    assert calls == [("build", "r1")] and site.history(store) == []


def test_rollback_republishes_previous(env, capsys):
    store, calls, run, _ = env
    site.publish_run(store, run("r1"))
    site.publish_run(store, run("r2", marking=0.1))
    assert main(["site", "rollback", "--store", str(store)]) == 0
    assert site.history(store)[-1]["run_id"] == "r1"
    assert calls[-2:] == [("build", "r1"), ("deploy", "secret")]


def test_rollback_needs_an_earlier_run(env):
    store, _, run, _ = env
    site.publish_run(store, run("r1"))
    with pytest.raises(site.SiteStop):
        site.rollback(store)


def test_publish_job_missing_token_fails_job_clearly(env):
    store, _, run, token = env
    token.unlink()
    jobqueue.add(store, {"type": "publish", "run_id": run("r1")})
    jobqueue.process_one(store, lambda: None)
    job = jobqueue.list_jobs(store)[0]
    assert job["state"] == "failed" and "no Cloudflare token" in job["error"]


def test_publish_job_and_eval_chain(env, monkeypatch):
    store, _, run, _ = env
    jobqueue.add(store, {"type": "publish", "run_id": run("r1")})
    jobqueue.process_one(store, lambda: None)
    assert jobqueue.list_jobs(store)[0]["publish_result"] == "published r1"
    monkeypatch.setattr(jobqueue, "run_eval", lambda s, j, r: ("no-go", None))
    jobqueue.add(store, {"type": "eval", "run_id": run("r2"), "publish": True})
    jobqueue.process_one(store, lambda: None)
    assert "publish_result" not in jobqueue.list_jobs(store)[-1]
