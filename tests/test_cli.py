import pytest

from twin.cli import main


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: twin" in capsys.readouterr().out

import json


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
    areas = _make_cli_area(store)
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
