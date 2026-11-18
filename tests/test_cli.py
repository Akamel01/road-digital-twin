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
