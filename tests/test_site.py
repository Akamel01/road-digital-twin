import json
from pathlib import Path

import pytest

from twin import jobqueue, site
from twin.cli import main
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A store, a fake build and deploy that record their calls, and a token file."""
    calls = []
    monkeypatch.setattr(
        site,
        "build",
        lambda run_ids, store, rep, web=None: calls.append(("build", run_ids)),
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
    assert calls == [("build", ["r1"]), ("deploy", "secret")]
    assert site.history(store)[-1]["run_id"] == "r1"


def test_not_worse_publishes_worse_skips(env):
    store, _calls, run, _ = env
    site.publish_run(store, run("r1"))
    assert site.publish_run(store, run("r2", marking=0.1)) == "published r2"
    assert site.publish_run(store, run("r3", marking=0.1)) == "published r3"  # a tie publishes
    assert "worse" in site.publish_run(
        store, run("r4", marking=0.1, cov=0.75)
    )  # one worse
    assert [e["run_id"] for e in site.history(store)] == ["r1", "r2", "r3"]


def test_no_go_first_run_publishes(env):
    store, calls, run, _ = env
    assert site.publish_run(store, run("r1", verdict="no-go")) == "published r1"
    assert calls == [("build", ["r1"]), ("deploy", "secret")]


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
    assert calls == [("build", ["r1"])] and site.history(store) == []


def test_rollback_republishes_previous(env, capsys):
    store, calls, run, _ = env
    site.publish_run(store, run("r1"))
    site.publish_run(store, run("r2", marking=0.1))
    assert main(["site", "rollback", "--store", str(store)]) == 0
    assert site.history(store)[-1]["run_id"] == "r1"
    assert calls[-2:] == [("build", ["r1"]), ("deploy", "secret")]


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
    monkeypatch.setattr(
        site, "build_latest", lambda store, web=None: calls.append("build")
    )
    monkeypatch.setattr(site, "deploy", lambda token, web=None: calls.append("deploy"))
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(tmp_path / "none"))
    assert site.publish_latest(tmp_path, "a1", dry_run=True).startswith("dry run")
    assert calls == ["build"]
    assert (
        main(
            ["site", "publish", "--latest", "a1", "--dry-run", "--store", str(tmp_path)]
        )
        == 0
    )


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
        (run / "manifest.json").write_text("{}")
    out = publish._stage(good, "outputs")
    out.mkdir(parents=True)
    for name in publish.PUBLIC_FILES:
        (out / name).write_text("x")
    runs = {"tok-s1": good, "tok-s2": partial}  # s3 has no full run
    monkeypatch.setattr(site.prgate, "pick_baseline", lambda store, scene: runs.get(scene))
    assert site.area_runs(tmp_path, area) == ["r-good"]


def test_build_writes_parseable_status_with_check_counts(tmp_path, monkeypatch):
    web = tmp_path / "web"
    (web / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(site.shutil, "which", lambda *a, **k: "/bin/npm")
    monkeypatch.setattr(
        site.publish,
        "publish_runs",
        lambda ids, out, store: out.mkdir(parents=True, exist_ok=True) or (None, None),
    )
    monkeypatch.setattr(site, "stage_latest_into", lambda store, web: False)
    monkeypatch.setattr(site, "_run", lambda cmd, cwd, env=None: None)
    rep = report("no-go")
    site.build(["r1"], tmp_path, rep, web)
    status = json.loads((web / "public" / "showcase" / "status.json").read_text())  # the browser must parse it
    assert status["verdict"] == "no-go"
    assert (status["checks_passed"], status["checks_total"]) == (GateReport(rep).passed, GateReport(rep).total)


def test_area_entry_rebuilds_from_recorded_runs_and_report(tmp_path):
    entry = {"run_id": "abc123", "runs": ["r1", "r2"], "report": {"verdict": "no-go"}}
    assert site.entry_inputs(tmp_path, entry) == (["r1", "r2"], {"verdict": "no-go"})
    (tmp_path / "r0").mkdir()
    (tmp_path / "r0" / "gates.json").write_text('{"verdict": "go"}')
    assert site.entry_inputs(tmp_path, {"run_id": "r0"}) == (["r0"], {"verdict": "go"})


def test_rollback_of_area_entry_uses_recorded_runs(env):
    store, calls, _run, _ = env
    site._record(store, {"run_id": "old", "runs": ["a", "b"], "report": report("no-go"), "published_at": "t"})
    site._record(store, {"run_id": "new", "runs": ["c"], "report": report("no-go"), "published_at": "t"})
    assert site.rollback(store) == "rolled back to old"
    assert calls[-2:] == [("build", ["a", "b"]), ("deploy", "secret")]


def test_redeploy_rebuilds_last_entry_and_adds_no_history(env, capsys):
    store, calls, run, _ = env
    site.publish_run(store, run("r1"))
    site.publish_run(store, run("r2", marking=0.1))
    calls.clear()
    assert main(["site", "redeploy", "--store", str(store)]) == 0
    assert calls == [("build", ["r2"]), ("deploy", "secret")]
    hist = site.history(store)
    assert [e["run_id"] for e in hist] == ["r1", "r2"]
    assert "redeployed_at" in hist[-1] and "redeployed_at" not in hist[0]
    assert "redeployed r2" in capsys.readouterr().out


def test_redeploy_dry_run_builds_without_deploy_or_record(env):
    store, calls, run, _ = env
    site.publish_run(store, run("r1"))
    calls.clear()
    assert site.redeploy(store, dry_run=True).startswith("dry run")
    assert calls == [("build", ["r1"])]
    assert "redeployed_at" not in site.history(store)[-1]


def test_redeploy_needs_a_published_run(env):
    store, _, _, _ = env
    with pytest.raises(site.SiteStop):
        site.redeploy(store)


def test_no_score_on_already_published(env, monkeypatch):
    store, _calls, run, _ = env
    site.publish_run(store, run("r1"))
    import twin.score as score_mod

    def boom(*a, **k):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(score_mod, "score_target", boom)
    assert site.publish_run(store, run("r1")) == "skipped: already published"


def _labelled(store, run_id, offset_m, version=1):
    store = Path(store)
    (store / run_id).mkdir(parents=True, exist_ok=True)
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


def test_labelled_store_tie_publishes_and_records_score(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _labelled(store, "r1", 0)
    _labelled(store, "r2", 0)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    assert site.publish_run(store, "r1") == "published r1"
    assert site.publish_run(store, "r2") == "published r2"
    assert site.history(store)[-1]["score"]["compare"]["publish"] is True
    assert site.history(store)[-1]["score"]["compare"]["elements"]["marking"]["status"] == "tie"


def test_labelled_store_regression_skips(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _labelled(store, "r1", 0)
    _labelled(store, "r2", 0.10)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    assert site.publish_run(store, "r1") == "published r1"
    out = site.publish_run(store, "r2")
    assert out.startswith("skipped: worse:")
    assert len(site.history(store)) == 1
    assert json.loads((store / "r2" / "score.json").read_text())["compare"]["publish"] is False


def test_old_history_entry_falls_back_with_note(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _labelled(store, "r1", 0)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    site._record(store, {"run_id": "old", "go_count": 0, "margin_sum": site.GateReport(report()).score(),
                        "published_at": "t", "verdict": "go", "margins": {}, "runs": ["old"], "report": report()})
    assert site.publish_run(store, "r1") == "published r1"
    assert "no per-element score" in capsys.readouterr().err


def test_more_gate_checks_do_not_override_score_regression(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _labelled(store, "b1", 0)
    _labelled(store, "r2", 0.10)
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
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    assert site.publish_run(store, "b1") == "published b1"
    out = site.publish_run(store, "r2")
    assert out.startswith("skipped: worse")
    doc = json.loads((store / "r2" / "score.json").read_text())
    assert doc["compare"]["elements"]["marking"]["status"] == "worse"


def test_label_version_bump_falls_back_with_note(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    _labelled(store, "r1", 0, version=1)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    assert site.publish_run(store, "r1") == "published r1"
    _labelled(store, "r2", 0.10, version=1)
    meta = json.loads((store / "labels" / "site-a" / "site.json").read_text())
    meta["version"] = 2
    (store / "labels" / "site-a" / "site.json").write_text(json.dumps(meta))
    assert site.publish_run(store, "r2") == "published r2"
    assert "not comparable" in capsys.readouterr().err


def test_run_after_area_falls_back_with_note(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    site._record(store, {"run_id": "area-base", "go_count": 0, "margin_sum": 0.0,
                        "published_at": "t", "verdict": "go", "margins": {}, "runs": ["area-base"],
                        "report": report(),
                        "score": {"target": "area-base", "target_kind": "area",
                                  "sites": [{"id": "a", "version": 1, "label_hash": "a" * 12},
                                            {"id": "b", "version": 1, "label_hash": "b" * 12}],
                                  "elements": {}, "compare": {"comparable": True, "publish": True}}})
    _labelled(store, "r1", 0)
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    assert site.publish_run(store, "r1") == "published r1"
    assert "not comparable" in capsys.readouterr().err


def test_area_publish_records_score(tmp_path, monkeypatch):
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
    monkeypatch.setattr(site, "area_runs", lambda store, area: ["r1"])
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)
    out = site.publish_run(store, str(store / "areas" / "seaport-1-twin"))
    assert out.startswith("published ")
    assert site.history(store)[-1]["score"] is not None


def test_corrupt_label_cannot_stop_publish(tmp_path, monkeypatch, capsys):
    token = tmp_path / "tok"
    token.write_text("secret\n")
    monkeypatch.setenv("TWIN_CF_TOKEN_FILE", str(token))
    monkeypatch.setattr(site, "build", lambda run_ids, store, rep, web=None: None)
    monkeypatch.setattr(site, "deploy", lambda token, web=None: None)

    # case 1: corrupt JSON
    store = tmp_path / "store1"
    _labelled(store, "r1", 0)
    (store / "labels" / "site-a" / "labels.geojson").write_text("{not json")
    assert site.publish_run(store, "r1") == "published r1"
    assert "score failed" in capsys.readouterr().err
    assert site.history(store)[-1]["score"] is None

    # case 2: invalid polygon
    store = tmp_path / "store2"
    _labelled(store, "r1", 0)
    (store / "labels" / "site-a" / "labels.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"id": "lab1", "element": "marking",
                      "type": "solid_line", "origin": "operator", "source_marking_type": "divider"},
                      "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}}]
    }))
    assert site.publish_run(store, "r1") == "published r1"
    assert "score failed" in capsys.readouterr().err
    assert site.history(store)[-1]["score"] is None
