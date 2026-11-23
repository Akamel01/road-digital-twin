import json
import shutil
from functools import partial
from pathlib import Path

import pytest

from twin import jobqueue, site
from twin.contracts import stage_dir
from twin.fake_run import write_fake_runs
from twin.gates import GateReport


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


class FakeWeb:
    """The web toolchain seam: records export and deploy. deploy reads the token as the real one does."""

    def __init__(self, web, calls=None):
        self.web = web
        self.calls = [] if calls is None else calls

    def export(self):
        showcase = self.web / "public" / "showcase"
        runs = sorted(d.name for d in showcase.iterdir() if d.is_dir() and d.name != "tiles") if showcase.is_dir() else []
        self.calls.append(("export", runs))

    def deploy(self):
        self.calls.append(("deploy", site.read_token()))


def _kw(tmp_path, calls=None):
    """Keyword arguments that point a publish at a fake toolchain and a scratch web folder."""
    web = tmp_path / "web"
    return {"web": web, "toolchain": FakeWeb(web, calls)}


@pytest.fixture(scope="module")
def fake_store(tmp_path_factory):
    """Two real synthetic runs (twin.fake_run): the showcase build is not faked."""
    base = tmp_path_factory.mktemp("fake_runs")
    return base, [d.name for d in write_fake_runs(base, drives=2)]


def _real_run(store, fake_store, run_id, index=0):
    """A real run folder under store named run_id (a copy of a synthetic run)."""
    base, ids = fake_store
    shutil.copytree(base / ids[index], store / run_id)


@pytest.fixture
def env(tmp_path, monkeypatch, fake_store):
    """A store, a fake toolchain that records its calls, and a token file."""
    calls = []
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    store = tmp_path / "store"

    def run(run_id, **kw):
        if not (store / run_id).exists():
            _real_run(store, fake_store, run_id)
        (store / run_id / "gates.json").write_text(json.dumps(report(**kw)))
        return run_id

    return store, calls, run, token, _kw(tmp_path, calls)


def _steps(calls):
    return [c[0] for c in calls]


def test_go_first_run_publishes(env):
    store, calls, run, _, kw = env
    assert site.publish_run(store, run("r1"), **kw) == "published r1"
    assert _steps(calls) == ["export", "deploy"] and calls[1] == ("deploy", "secret")
    assert len(calls[0][1]) == 1  # the showcase holds the run
    assert site.history(store)[-1]["run_id"] == "r1"


def test_not_worse_publishes_worse_skips(env):
    store, _calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    assert site.publish_run(store, run("r2", marking=0.1), **kw) == "published r2"
    assert site.publish_run(store, run("r3", marking=0.1), **kw) == "published r3"  # a tie publishes
    assert "worse" in site.publish_run(
        store, run("r4", marking=0.1, cov=0.75), **kw
    )  # one worse
    assert [e["run_id"] for e in site.history(store)] == ["r1", "r2", "r3"]


def test_no_go_first_run_publishes(env):
    store, calls, run, _, kw = env
    assert site.publish_run(store, run("r1", verdict="no-go"), **kw) == "published r1"
    assert _steps(calls) == ["export", "deploy"]


def test_missing_token_stops_with_message(env):
    store, calls, run, token, kw = env
    token.unlink()
    with pytest.raises(site.SiteStop, match="no Cloudflare token at"):
        site.publish_run(store, run("r1"), **kw)
    assert _steps(calls) == ["export"] and site.history(store) == []  # nothing recorded, nothing deployed


def test_node_web_deploy_without_token_stops_before_any_command(env):
    _, _, _, token, _ = env
    token.unlink()
    with pytest.raises(site.SiteStop, match="no Cloudflare token at"):
        site.NodeWeb(Path("/nonexistent-web")).deploy()


def test_dry_run_builds_without_token_or_deploy(env):
    store, calls, run, token, kw = env
    token.unlink()
    assert site.publish_run(store, run("r1"), dry_run=True, **kw).startswith("dry run")
    assert _steps(calls) == ["export"] and site.history(store) == []


def test_dry_run_stages_the_showcase_and_does_not_score(env, monkeypatch):
    store, _calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    monkeypatch.setattr(site.score, "score_target", lambda *a, **k: pytest.fail("scored on a dry run"))
    out = site.publish_run(store, run("r2", marking=0.1), dry_run=True, **kw)
    assert out.startswith("dry run: built ") and "nothing deployed (files=" in out
    assert (kw["web"] / "public" / "showcase" / "status.json").is_file()
    assert len(site.history(store)) == 1


def test_rollback_republishes_previous(env, capsys):
    store, calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    site.publish_run(store, run("r2", marking=0.1), **kw)
    calls.clear()
    assert site.rollback(store, **kw) == "rolled back to r1"
    assert site.history(store)[-1]["run_id"] == "r1"
    assert _steps(calls) == ["export", "deploy"]


def test_rollback_needs_an_earlier_run(env):
    store, _, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    with pytest.raises(site.SiteStop):
        site.rollback(store, **kw)


def test_publish_job_missing_token_fails_job_clearly(env, monkeypatch):
    store, _, run, token, kw = env
    token.unlink()
    monkeypatch.setattr(site, "publish_run", partial(site.publish_run, **kw))
    jobqueue.add(store, {"type": "publish", "run_id": run("r1")})
    jobqueue.process_one(store, lambda: None)
    job = jobqueue.list_jobs(store)[0]
    assert job["state"] == "failed" and "no Cloudflare token" in job["error"]


def test_publish_job_and_eval_chain(env, monkeypatch):
    store, _, run, _, kw = env
    monkeypatch.setattr(site, "publish_run", partial(site.publish_run, **kw))
    jobqueue.add(store, {"type": "publish", "run_id": run("r1")})
    jobqueue.process_one(store, lambda: None)
    assert jobqueue.list_jobs(store)[0]["publish_result"] == "published r1"
    monkeypatch.setattr(jobqueue, "run_eval", lambda s, j, r: ("no-go", None))
    jobqueue.add(store, {"type": "eval", "run_id": run("r2"), "publish": True})
    jobqueue.process_one(store, lambda: None)
    assert "publish_result" not in jobqueue.list_jobs(store)[-1]


def _area(store, verdict="no-go", g2=4.3):
    import numpy as np

    d = store / "areas" / "a1"
    d.mkdir(parents=True)
    rng = np.random.default_rng(0)
    n = 5000
    np.savez_compressed(
        d / "merged.npz",
        x=rng.uniform(0, 100, n) + 3e5,
        y=rng.uniform(0, 80, n) + 4e6,
        z=rng.uniform(0, 3, n),
        intensity=rng.uniform(0, 1, n),
        drive=rng.integers(0, 3, n).astype("u2"),
    )
    rep = report(verdict)
    rep["run_id"] = "area-a1"
    rep["gates"]["G2"] = {
        "name": "x",
        "status": verdict,
        "checks": [{"metric": "align.p95", "op": "<=", "threshold": 0.05, "value": g2}],
    }
    (d / "gates.json").write_text(json.dumps(rep))
    (d / "drives.json").write_text(
        json.dumps([{"index": 0, "scene": "s1", "date": "2018-08-01"}])
    )
    return d


def test_latest_payload_is_staged_for_any_verdict(tmp_path):
    store = tmp_path
    _area(store)
    info = site.latest_payload(store, "areas/a1")
    assert info["verdict"] == "no-go" and info["bytes"] < site.MAX_BUNDLE_BYTES
    assert info["files"]["cloud.bin"] == 7 * info["n_points"]
    out = site.latest_dir(store)
    card = json.loads((out / "scorecard.json").read_text())
    assert card["gate_passed"] is False and "G2" in card["gates"]
    assert card["cloud"]["n_points"] == info["n_points"]
    site.latest_payload(store, "a1")  # same build again: trend replaces, not repeats
    assert len(json.loads((out / "trend.json").read_text())) == 1


def test_latest_cloud_is_thinned_to_target():
    import io

    import numpy as np

    pts = np.random.default_rng(1).uniform(0, 50, (20000, 3))
    buf = io.BytesIO()
    np.savez(buf, x=pts[:, 0], y=pts[:, 1], z=pts[:, 2], drive=np.zeros(20000, "u2"))
    buf.seek(0)
    data, meta = site.decimate_cloud(buf, target=2000)
    assert meta["n_points"] <= 2000 and len(data) == 7 * meta["n_points"]


def test_publish_latest_dry_run_needs_no_token(tmp_path, monkeypatch):
    _area(tmp_path)
    calls = []
    kw = _kw(tmp_path, calls)
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(tmp_path / "none"))
    out = site.publish_latest(tmp_path, "a1", dry_run=True, **kw)
    assert out.startswith("dry run") and "nothing deployed (a1 no-go" in out
    assert _steps(calls) == ["export"]
    assert (kw["web"] / "public" / "latest-build" / "scorecard.json").is_file()  # the bundle is staged
    assert site.site_command("publish", None, True, tmp_path, latest="a1", toolchain=kw["toolchain"]) == 0


def test_publish_latest_deploys_and_carries_the_published_showcase(env):
    store, calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    _area(store)
    calls.clear()
    assert site.publish_latest(store, "a1", **kw).startswith("published latest build: a1 no-go")
    assert _steps(calls) == ["export", "deploy"]
    assert len(calls[0][1]) == 1  # the last published showcase is rebuilt unchanged
    web = kw["web"] / "public"
    assert (web / "showcase" / "status.json").is_file() and (web / "latest-build" / "cloud.bin").is_file()


def test_area_runs_maps_drive_names_to_tokens_and_skips_unpublishable(tmp_path, monkeypatch):
    from twin import publish

    area = _area(tmp_path)  # areas/a1, drives.json lists scene "s1"
    drives = json.loads((area / "drives.json").read_text()) + [{"scene": "s2"}, {"scene": "s3"}]
    (area / "drives.json").write_text(json.dumps(drives))
    defs = [{"scene": s, "scene_token": f"tok-{s}"} for s in ("s1", "s2", "s3")]
    (tmp_path / "areas" / "a1.json").write_text(json.dumps({"drives": defs}))
    good, partial = tmp_path / "r-good", tmp_path / "r-partial"
    for run in (good, partial):
        run.mkdir()
        (run / "run.json").write_text("{}")
    out = stage_dir(good, "outputs")
    out.mkdir(parents=True)
    for name in publish.PUBLIC_FILES:
        (out / name).write_text("x")
    runs = {"tok-s1": good, "tok-s2": partial}  # s3 has no full run
    monkeypatch.setattr(site.prgate, "pick_baseline", lambda store, scene: runs.get(scene))
    assert site.area_runs(tmp_path, area) == ["r-good"]


def test_showcase_status_is_parseable_with_check_counts(env):
    store, _calls, run, _, kw = env
    rid = run("r1", verdict="no-go")
    site.publish_run(store, rid, **kw)
    status = json.loads((kw["web"] / "public" / "showcase" / "status.json").read_text())  # the browser must parse it
    rep = report("no-go")
    assert status["verdict"] == "no-go"
    assert (status["checks_passed"], status["checks_total"]) == (GateReport(rep).passed, GateReport(rep).total)


def test_area_entry_rebuilds_from_recorded_runs_and_report(tmp_path):
    entry = {"run_id": "abc123", "runs": ["r1", "r2"], "report": {"verdict": "no-go"}}
    assert site.entry_inputs(tmp_path, entry) == (["r1", "r2"], {"verdict": "no-go"})
    (tmp_path / "r0").mkdir()
    (tmp_path / "r0" / "gates.json").write_text('{"verdict": "go"}')
    assert site.entry_inputs(tmp_path, {"run_id": "r0"}) == (["r0"], {"verdict": "go"})


def test_rollback_of_area_entry_uses_recorded_runs(env, fake_store):
    store, calls, _run, _, kw = env
    a, b = fake_store[1]
    _real_run(store, fake_store, a, 0)
    _real_run(store, fake_store, b, 1)
    site._record(store, {"run_id": "old", "runs": [a, b], "report": report("no-go"), "published_at": "t"})
    site._record(store, {"run_id": "new", "runs": [a], "report": report("no-go"), "published_at": "t"})
    assert site.rollback(store, **kw) == "rolled back to old"
    assert calls == [("export", sorted([a, b])), ("deploy", "secret")]
    assert site.history(store)[-1]["run_id"] == "old"


def test_redeploy_rebuilds_last_entry_and_adds_no_history(env, capsys):
    store, calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    site.publish_run(store, run("r2", marking=0.1), **kw)
    calls.clear()
    assert site.site_command("redeploy", None, False, store, toolchain=kw["toolchain"]) == 0
    assert _steps(calls) == ["export", "deploy"]
    hist = site.history(store)
    assert [e["run_id"] for e in hist] == ["r1", "r2"]
    assert "redeployed_at" in hist[-1] and "redeployed_at" not in hist[0]
    assert "redeployed r2" in capsys.readouterr().out


def test_redeploy_dry_run_builds_without_deploy_or_record(env):
    store, calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    calls.clear()
    assert site.redeploy(store, dry_run=True, **kw).startswith("dry run")
    assert _steps(calls) == ["export"]
    assert "redeployed_at" not in site.history(store)[-1]


def test_redeploy_needs_a_published_run(env):
    store, _, _, _, kw = env
    with pytest.raises(site.SiteStop):
        site.redeploy(store, **kw)


def test_no_score_on_already_published(env, monkeypatch):
    store, _calls, run, _, kw = env
    site.publish_run(store, run("r1"), **kw)
    import twin.score as score_mod

    def boom(*a, **k):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(score_mod, "score_target", boom)
    assert site.publish_run(store, run("r1"), **kw) == "skipped: already published"


def _labelled(fake_store, store, run_id, offset_m, version=1):
    store = Path(store)
    if not (store / run_id).exists():
        _real_run(store, fake_store, run_id)
    (store / run_id / "gates.json").write_text(json.dumps(report()))
    (store / run_id / "5_features").mkdir(exist_ok=True)
    feat = {
        "type": "Feature",
        "properties": {"id": "r1", "kind": "marking", "reliability": "observed",
                       "marking_type": "divider", "element": "marking", "type": "solid_line"},
        "geometry": {"type": "LineString", "coordinates": [[0, offset_m], [40, offset_m]]},
    }
    (store / run_id / "5_features" / "markings.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feat]})
    )
    site_dir = store / "labels" / "site-a"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "site.json").write_text(json.dumps({
        "id": "site-a", "role": "audit",
        "polygon": {"type": "Polygon", "coordinates": [[[0, -10], [50, -10], [50, 10], [0, 10], [0, -10]]]},
        "version": version, "created_at": "2026-01-01T00:00:00", "source_area": "a",
    }))
    label = {
        "type": "Feature",
        "properties": {"id": "lab1", "element": "marking", "type": "solid_line",
                       "origin": "operator", "source_marking_type": "divider"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]},
    }
    (site_dir / "labels.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [label]})
    )


def test_labelled_store_tie_publishes_and_records_score(fake_store, tmp_path, monkeypatch):
    store = tmp_path / "store"
    _labelled(fake_store, store, "r1", 0)
    _labelled(fake_store, store, "r2", 0)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)
    assert site.publish_run(store, "r1", **kw) == "published r1"
    assert site.publish_run(store, "r2", **kw) == "published r2"
    assert site.history(store)[-1]["score"]["compare"]["publish"] is True
    assert site.history(store)[-1]["score"]["compare"]["elements"]["marking"]["status"] == "tie"


def test_labelled_store_regression_skips(fake_store, tmp_path, monkeypatch):
    store = tmp_path / "store"
    _labelled(fake_store, store, "r1", 0)
    _labelled(fake_store, store, "r2", 0.10)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)
    assert site.publish_run(store, "r1", **kw) == "published r1"
    out = site.publish_run(store, "r2", **kw)
    assert out.startswith("skipped: worse:")
    assert len(site.history(store)) == 1
    assert json.loads((store / "r2" / "score.json").read_text())["compare"]["publish"] is False


def test_old_history_entry_falls_back_with_note(fake_store, tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _labelled(fake_store, store, "r1", 0)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)
    site._record(store, {"run_id": "old", "go_count": 0, "margin_sum": site.GateReport(report()).score(),
                        "published_at": "t", "verdict": "go", "margins": {}, "runs": ["old"], "report": report()})
    assert site.publish_run(store, "r1", **kw) == "published r1"
    assert "no per-element score" in capsys.readouterr().err


def test_more_gate_checks_do_not_override_score_regression(fake_store, tmp_path, monkeypatch):
    store = tmp_path / "store"
    _labelled(fake_store, store, "b1", 0)
    _labelled(fake_store, store, "r2", 0.10)
    # make all checks "go"
    for rid in ("b1", "r2"):
        p = store / rid / "gates.json"
        rep = json.loads(p.read_text())
        for g in rep["gates"].values():
            for c in g["checks"]:
                c["status"] = "go"
        p.write_text(json.dumps(rep))
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)
    assert site.publish_run(store, "b1", **kw) == "published b1"
    out = site.publish_run(store, "r2", **kw)
    assert out.startswith("skipped: worse")
    doc = json.loads((store / "r2" / "score.json").read_text())
    assert doc["compare"]["elements"]["marking"]["status"] == "worse"


def test_label_version_bump_falls_back_with_note(fake_store, tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _labelled(fake_store, store, "r1", 0, version=1)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)
    assert site.publish_run(store, "r1", **kw) == "published r1"
    _labelled(fake_store, store, "r2", 0.10, version=1)
    meta = json.loads((store / "labels" / "site-a" / "site.json").read_text())
    meta["version"] = 2
    (store / "labels" / "site-a" / "site.json").write_text(json.dumps(meta))
    assert site.publish_run(store, "r2", **kw) == "published r2"
    assert "not comparable" in capsys.readouterr().err


def test_run_after_area_falls_back_with_note(fake_store, tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    site._record(store, {"run_id": "area-base", "go_count": 0, "margin_sum": 0.0,
                        "published_at": "t", "verdict": "go", "margins": {}, "runs": ["area-base"],
                        "report": report(),
                        "score": {"target": "area-base", "target_kind": "area",
                                  "sites": [{"id": "a", "version": 1, "label_hash": "a" * 12},
                                            {"id": "b", "version": 1, "label_hash": "b" * 12}],
                                  "elements": {}, "compare": {"comparable": True, "publish": True}}})
    _labelled(fake_store, store, "r1", 0)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)
    assert site.publish_run(store, "r1", **kw) == "published r1"
    assert "not comparable" in capsys.readouterr().err


def test_area_publish_records_score(fake_store, tmp_path, monkeypatch):
    import numpy as np

    store = tmp_path / "store"
    area = store / "areas" / "seaport-1-twin"
    area.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(area / "merged.npz", x=np.array([1.0]), y=np.array([2.0]), z=np.array([3.0]),
                        intensity=np.array([0.5]), drive=np.array([0], dtype="u2"))
    (area / "gates.json").write_text(json.dumps(report()))
    (area / "5_features").mkdir(exist_ok=True)
    feat = {"type": "Feature", "properties": {"id": "r1", "kind": "marking", "reliability": "observed",
             "marking_type": "divider", "element": "marking", "type": "solid_line"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]}}
    (area / "5_features" / "markings.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feat]})
    )
    site_dir = store / "labels" / "site-a"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "site.json").write_text(json.dumps({
        "id": "site-a", "role": "audit",
        "polygon": {"type": "Polygon", "coordinates": [[[0, -10], [50, -10], [50, 10], [0, 10], [0, -10]]]},
        "version": 1, "created_at": "2026-01-01T00:00:00", "source_area": "a",
    }))
    label = {"type": "Feature", "properties": {"id": "lab1", "element": "marking", "type": "solid_line",
             "origin": "operator", "source_marking_type": "divider"},
             "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]}}
    (site_dir / "labels.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [label]})
    )
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    _real_run(store, fake_store, "r1")
    monkeypatch.setattr(site, "area_runs", lambda store, area: ["r1"])
    kw = _kw(tmp_path)
    out = site.publish_run(store, str(store / "areas" / "seaport-1-twin"), **kw)
    assert out.startswith("published ")
    assert site.history(store)[-1]["score"] is not None


def test_corrupt_label_cannot_stop_publish(fake_store, tmp_path, monkeypatch, capsys):
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    kw = _kw(tmp_path)

    # case 1: corrupt JSON
    store = tmp_path / "store1"
    _labelled(fake_store, store, "r1", 0)
    (store / "labels" / "site-a" / "labels.geojson").write_text("{not json")
    assert site.publish_run(store, "r1", **kw) == "published r1"
    assert "score failed" in capsys.readouterr().err
    assert site.history(store)[-1]["score"] is None

    # case 2: invalid polygon
    store = tmp_path / "store2"
    _labelled(fake_store, store, "r1", 0)
    (store / "labels" / "site-a" / "labels.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"id": "lab1", "element": "marking",
                      "type": "solid_line", "origin": "operator", "source_marking_type": "divider"},
                      "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}}]
    }))
    assert site.publish_run(store, "r1", **kw) == "published r1"
    assert "score failed" in capsys.readouterr().err
    assert site.history(store)[-1]["score"] is None


# ---- decide: the publish rule, pure ----


def _entry(rid="p", rep=None, score=None, **kw):
    rep = rep or report()
    gr = GateReport(rep)
    return {"run_id": rid, "go_count": gr.passed, "margin_sum": gr.score(), "score": score, **kw}


def _passing(n):
    """A report with its first n checks marked go."""
    rep = report()
    for i, check in enumerate(rep["gates"]["G5"]["checks"]):
        check["status"] = "go" if i < n else "no-go"
    return rep


_COMPARABLE_OK = {"compare": {"comparable": True, "publish": True}}
_COMPARABLE_WORSE = {"compare": {"comparable": True, "publish": False, "reason": "marking worse"}}
_NOT_COMPARABLE = {"compare": {"comparable": False}}


@pytest.mark.parametrize(
    ("cand", "past", "score_doc", "kw", "publish", "reason"),
    [
        (report(), [], None, {}, True, ""),  # empty history
        (report(), [_entry("a")], None, {"publish_id": "a"}, False, "already published"),
        (report(), [_entry("a")], None, {"publish_id": "a", "force": True}, True, ""),
        (report(), [_entry("a", build_id="b1")], None, {"publish_id": "b1"}, False, "already published"),
        (report(marking=0.195), [_entry("a")], None, {}, True, ""),  # tie within TIE_MARGIN
        (report(marking=0.1), [_entry("a")], None, {}, True, ""),  # better margin sum
        (_passing(1), [_entry("a", rep=_passing(2))], None, {}, False, "worse: fewer gate checks pass (1 vs 2)"),
        (_passing(2), [_entry("a", rep=_passing(1))], None, {}, True, ""),
        (report(marking=0.1, cov=0.75), [_entry("a", rep=report(marking=0.1))], None, {}, False, None),  # margin sum
        (report(), [_entry("a", score=_COMPARABLE_OK)], _COMPARABLE_OK, {}, True, ""),
        (report(), [_entry("a", score={})], _COMPARABLE_WORSE, {}, False, "worse: marking worse"),
        (report(marking=0.1), [_entry("a", score={})], _NOT_COMPARABLE, {}, True, ""),  # falls to margin sum
        (report(), [{"run_id": "a"}], None, {}, True, ""),  # entry without gate figures
    ],
)
def test_decide_table(cand, past, score_doc, kw, publish, reason):
    kw = {"publish_id": "new", "force": False, **kw}
    d = site.decide(cand, past, score_doc, **kw)
    assert d.publish is publish
    if reason is not None:
        assert d.reason == reason
    else:
        assert d.reason.startswith("worse: margin sum")


def test_decide_margin_sum_fallback_beyond_noise_skips_and_notes():
    worse = report(marking=0.29)  # one check still passes both, but margin sum drops by more than TIE_MARGIN
    published = _entry("a", rep=report(marking=0.1))
    d = site.decide(worse, [published], None, publish_id="n", force=False)
    assert not d.publish and d.reason.startswith("worse: margin sum") and "comparing gate margins" in d.note
    published["score"] = {}
    d = site.decide(worse, [published], _NOT_COMPARABLE, publish_id="n", force=False)
    assert not d.publish and "not comparable" in d.note
