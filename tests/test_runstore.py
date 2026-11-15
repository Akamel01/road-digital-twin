"""RunStore: which runs exist and count, on a tmp store of fake manifests."""

import json

from twin.contracts import STAGE_NAMES
from twin.runstore import RunStore

MINI = "v1.0-mini"


def _run(store, name, scene="s1", status="ok", stages=None, version=MINI, parent=None, gates=False):
    d = store / name
    d.mkdir()
    doc = {
        "data": {"scene_token": scene, "nuscenes_version": version},
        "stages": [{"name": n, "status": status} for n in (stages or STAGE_NAMES)],
    }
    if parent:
        doc["parent"] = {"run_id": parent, "from_stage": STAGE_NAMES[1]}
    (d / "manifest.json").write_text(json.dumps(doc))
    if gates:
        (d / "gates.json").write_text("{}")


def _ids(runs):
    return [r.id for r in runs]


def test_runs_newest_first_and_filters(tmp_path):
    _run(tmp_path, "20261101-000000-aaaaaa")
    _run(tmp_path, "20261102-000000-bbbbbb", scene="s2")
    _run(tmp_path, "20261103-000000-cccccc", version="v1.0-trainval")
    _run(tmp_path, "20261104-000000-dddddd", parent="20261101-000000-aaaaaa")
    (tmp_path / "20261105-000000-eeeeee").mkdir()  # no manifest: not a run
    (tmp_path / "notes").mkdir()
    store = RunStore(tmp_path)
    assert _ids(store.runs()) == [
        "20261104-000000-dddddd",
        "20261103-000000-cccccc",
        "20261102-000000-bbbbbb",
        "20261101-000000-aaaaaa",
    ]
    assert _ids(store.runs(scene="s2")) == ["20261102-000000-bbbbbb"]
    assert "20261104-000000-dddddd" not in _ids(store.runs(no_parent=True))
    assert _ids(store.runs(dataset_version="v1.0-trainval")) == ["20261103-000000-cccccc"]
    assert RunStore(tmp_path / "none").runs() == []


def test_full_chain_and_with_gates(tmp_path):
    _run(tmp_path, "20261101-000000-aaaaaa", gates=True)
    _run(tmp_path, "20261102-000000-bbbbbb", status="skipped")
    _run(tmp_path, "20261103-000000-cccccc", status="running")
    _run(tmp_path, "20261104-000000-dddddd", stages=["load", "mask"])
    store = RunStore(tmp_path)
    assert _ids(store.runs(full_chain=True)) == ["20261102-000000-bbbbbb", "20261101-000000-aaaaaa"]
    assert _ids(store.runs(full_chain=True, with_gates=True)) == ["20261101-000000-aaaaaa"]


def test_complete_and_failed(tmp_path):
    _run(tmp_path, "20261101-000000-aaaaaa")
    _run(tmp_path, "20261102-000000-bbbbbb", stages=["load"], status="failed")
    _run(tmp_path, "20261103-000000-cccccc", stages=["load"])
    store = RunStore(tmp_path)
    ok, bad, partial = (store.get(i) for i in ("20261101-000000-aaaaaa", "20261102-000000-bbbbbb", "20261103-000000-cccccc"))
    assert store.complete(ok) and not store.failed(ok)
    assert not store.complete(bad) and store.failed(bad)[0]["status"] == "failed"
    assert not store.complete(partial) and not store.failed(partial)
    assert (ok.status, bad.status) == ("ok", "failed")


def test_newest_baseline(tmp_path, monkeypatch):
    monkeypatch.delenv("NUSCENES_VERSION", raising=False)
    _run(tmp_path, "20261101-000000-aaaaaa", gates=True)
    _run(tmp_path, "20261102-000000-bbbbbb", gates=True, parent="20261101-000000-aaaaaa")  # a rerun
    _run(tmp_path, "20261103-000000-cccccc")  # no gates yet
    _run(tmp_path, "20261104-000000-dddddd", gates=True, version="v1.0-trainval")
    store = RunStore(tmp_path)
    assert store.newest_baseline("s1").id == "20261101-000000-aaaaaa"
    assert store.newest_baseline("other") is None
    monkeypatch.setenv("NUSCENES_VERSION", "v1.0-trainval")
    assert store.newest_baseline("s1").id == "20261104-000000-dddddd"
