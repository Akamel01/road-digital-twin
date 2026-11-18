import json
from pathlib import Path

import pytest

from twin import site
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


def _labelled_store(store, run_id, offset_m):
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
        "version": 1, "created_at": "2026-01-01T00:00:00", "source_area": "a",
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


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: twin" in capsys.readouterr().out


def _make_cli_area(store, name="a1"):
    areas = store / "areas"
    build = areas / f"{name}-twin"
    (build / "5_features").mkdir(parents=True, exist_ok=True)
    area_def = {
        "name": name,
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[-50, -50], [200, -50], [200, 200], [-50, 200], [-50, -50]]]},
        "drives": [],
    }
    (areas / f"{name}.json").write_text(json.dumps(area_def))
    (build / "drives.json").write_text(json.dumps([]))
    return areas


def _patch_cli_export(monkeypatch):
    import twin.labelraster as lr
    from twin.labelraster import blank_window

    def fake(store, runs, *, site, x0, y1, **kwargs):
        return blank_window(site, x0, y1, [])

    monkeypatch.setattr(lr, "export_window", fake)


def test_labels_tool_missing_site_without_area_exit_2(tmp_path, capsys, monkeypatch):
    store = tmp_path / "store"
    _patch_cli_export(monkeypatch)
    rc = main(["labels", "tool", "s1", "--store", str(store)])
    assert rc == 2
    err = capsys.readouterr().err
    assert err


def test_labels_import_set_mismatch_exit_2(tmp_path, capsys):
    store = tmp_path / "store"
    _make_cli_area(store)
    # create site
    from twin import labels

    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    d = {"set": "other", "version": 1, "surfaces": [{"id": "x", "type": "curb", "geom": "polyline", "xy": [[0, 0], [1, 1]], "by": "operator"}], "supports": [], "devices": []}
    dpath = tmp_path / "d.json"
    dpath.write_text(json.dumps(d))
    rc = main(["labels", "import", "s1", str(dpath), "--store", str(store)])
    assert rc == 2
    assert capsys.readouterr().err


def test_labels_tool_existing_site_without_runs_exit_2(tmp_path, capsys, monkeypatch):
    store = tmp_path / "store"
    areas = store / "areas"
    build = areas / "a1-twin"
    (build / "5_features").mkdir(parents=True, exist_ok=True)
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    (areas / "a1.json").write_text(json.dumps(area_def))
    (build / "drives.json").write_text(json.dumps([{"scene": "sc1"}]))
    from twin import labels

    labels.draft(store, "s1", "a1", areas_root=areas)
    _patch_cli_export(monkeypatch)
    rc = main(["labels", "tool", "s1", "--area", "a1", "--store", str(store), "--areas", str(areas)])
    assert rc == 2
    assert "no resolvable runs" in capsys.readouterr().err


def test_labels_import_frozen_site_exit_2(tmp_path, capsys):
    store = tmp_path / "store"
    _make_cli_area(store)
    from twin import labels

    labels.draft(store, "s1", "a1", areas_root=store / "areas")
    labels.approve(store, "s1", "op")
    d = {"set": "s1", "version": 1, "surfaces": [{"id": "x", "type": "curb", "geom": "polyline", "xy": [[0, 0], [1, 1]], "by": "operator"}], "supports": [], "devices": []}
    dpath = tmp_path / "d.json"
    dpath.write_text(json.dumps(d))
    rc = main(["labels", "import", "s1", str(dpath), "--store", str(store)])
    assert rc == 2
    assert capsys.readouterr().err


def test_labels_tool_reset_refuses_frozen_exit_2(tmp_path, capsys, monkeypatch):
    store = tmp_path / "store"
    areas = store / "areas"
    build = areas / "a1-twin"
    (build / "5_features").mkdir(parents=True, exist_ok=True)
    area_def = {
        "name": "a1",
        "dataset_version": "v1.0-trainval",
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]]},
        "drives": [{"scene": "sc1", "scene_token": "t1"}],
    }
    (areas / "a1.json").write_text(json.dumps(area_def))
    (build / "drives.json").write_text(json.dumps([{"scene": "sc1"}]))
    run = store / "20261101-000000-aaaaaa"
    run.mkdir(parents=True, exist_ok=True)
    manifest = {
        "data": {"scene_token": "t1", "nuscenes_version": "v1.0-trainval"},
        "stages": [
            {"name": "load", "status": "ok"},
            {"name": "align", "status": "ok"},
            {"name": "ground", "status": "ok"},
        ],
    }
    (run / "manifest.json").write_text(json.dumps(manifest))
    from twin import labels

    labels.draft(store, "s1", "a1", areas_root=areas)
    labels.approve(store, "s1", "op")
    _patch_cli_export(monkeypatch)
    rc = main(["labels", "tool", "s1", "--area", "a1", "--reset", "--store", str(store), "--areas", str(areas)])
    assert rc == 2
    assert "frozen" in capsys.readouterr().err.lower()


def test_labels_tool_prints_path_and_default_note(tmp_path, capsys, monkeypatch):
    store = tmp_path / "store"
    areas = _make_cli_area(store)
    _patch_cli_export(monkeypatch)
    rc = main(["labels", "tool", "s1", "--area", "a1", "--store", str(store), "--areas", str(areas)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tool.html" in out
    assert "127.0.0.1:8090" in out


def test_score_writes_score_json_and_exits_zero(tmp_path, capsys):
    store = tmp_path / "store"
    _labelled_store(store, "r1", 0)
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 0
    assert (store / "r1" / "score.json").exists()
    out = capsys.readouterr().out
    assert "score r1" in out
    assert "publish: yes" in out


def test_score_regression_exits_one(tmp_path, capsys):
    store = tmp_path / "store"
    _labelled_store(store, "r1", 0)
    _labelled_store(store, "r2", 0.10)
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 0
    r1_doc = json.loads((store / "r1" / "score.json").read_text())
    site._record(store, {"run_id": "r1", "score": r1_doc})
    rc = main(["score", "r2", "--sites", "audit", "--store", str(store)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "publish: no" in out
    assert "p95" in out


def test_score_without_labels_exits_two(tmp_path, capsys):
    store = tmp_path / "store"
    (store / "r1").mkdir(parents=True, exist_ok=True)
    (store / "r1" / "gates.json").write_text(json.dumps(report()))
    (store / "r1" / "5_features").mkdir(exist_ok=True)
    feat = {
        "type": "Feature",
        "properties": {"id": "r1", "kind": "marking", "reliability": "observed",
                       "marking_type": "divider", "element": "marking", "type": "solid_line"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]},
    }
    (store / "r1" / "5_features" / "markings.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feat]})
    )
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot score: no labels dir" in err
    assert not (store / "r1" / "score.json").exists()


def test_score_without_features_exits_two(tmp_path, capsys):
    store = tmp_path / "store"
    (store / "r1").mkdir(parents=True, exist_ok=True)
    (store / "r1" / "gates.json").write_text(json.dumps(report()))
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot score: no 5_features" in err


def test_score_sites_role_filters(tmp_path, capsys):
    store = tmp_path / "store"
    _labelled_store(store, "r1", 0)
    # add a dev site
    dev_dir = store / "labels" / "site-dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "site.json").write_text(json.dumps({
        "id": "site-dev", "role": "dev",
        "polygon": {"type": "Polygon", "coordinates": [[[0, -10], [50, -10], [50, 10], [0, 10], [0, -10]]]},
        "version": 1, "created_at": "2026-01-01T00:00:00", "source_area": "a",
    }))
    label = {
        "type": "Feature",
        "properties": {"id": "lab1", "element": "marking", "type": "solid_line",
                       "origin": "operator", "source_marking_type": "divider"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]},
    }
    (dev_dir / "labels.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [label]})
    )
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 0
    r1_doc = json.loads((store / "r1" / "score.json").read_text())
    site._record(store, {"run_id": "r1", "score": r1_doc})
    # r2 run
    _labelled_store(store, "r2", 0)
    rc = main(["score", "r2", "--sites", "dev", "--store", str(store)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "dev labels never decide publishing" in err
    doc2 = json.loads((store / "r2" / "score.json").read_text())
    assert doc2["compare"]["comparable"] is False
    assert doc2["compare"]["publish"] is None


def test_score_no_dev_sites_exits_two(tmp_path, capsys):
    store = tmp_path / "store"
    _labelled_store(store, "r1", 0)
    rc = main(["score", "r1", "--sites", "dev", "--store", str(store)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot score: no dev label sites" in err


def test_score_corrupt_labels_exits_two(tmp_path, capsys):
    store = tmp_path / "store"
    _labelled_store(store, "r1", 0)
    (store / "labels" / "site-a" / "labels.geojson").write_text("{not json")
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cannot score:" in err


def test_score_not_comparable_exits_two(tmp_path, capsys):
    store = tmp_path / "store"
    _labelled_store(store, "r1", 0)
    rc = main(["score", "r1", "--sites", "audit", "--store", str(store)])
    assert rc == 0
    r1_doc = json.loads((store / "r1" / "score.json").read_text())
    # bump version
    sp = store / "labels" / "site-a" / "site.json"
    meta = json.loads(sp.read_text())
    meta["version"] = 2
    sp.write_text(json.dumps(meta))
    site._record(store, {"run_id": "r1", "score": r1_doc})
    # r2 run dir without resetting labels
    (store / "r2").mkdir(parents=True, exist_ok=True)
    (store / "r2" / "gates.json").write_text(json.dumps(report()))
    (store / "r2" / "5_features").mkdir(exist_ok=True)
    feat = {
        "type": "Feature",
        "properties": {"id": "r1", "kind": "marking", "reliability": "observed",
                       "marking_type": "divider", "element": "marking", "type": "solid_line"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [40, 0]]},
    }
    (store / "r2" / "5_features" / "markings.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [feat]})
    )
    rc = main(["score", "r2", "--sites", "audit", "--store", str(store)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not comparable" in err
    doc2 = json.loads((store / "r2" / "score.json").read_text())
    assert doc2["compare"]["comparable"] is False

