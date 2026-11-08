import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.api import ALLOWED_ORIGIN, create_app
from twin.contracts import STAGE_NAMES, Manifest
from twin.fake_run import write_fake_runs


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("api") / "runs"
    write_fake_runs(base, drives=2)
    return base


@pytest.fixture(scope="module")
def client(store):
    return TestClient(create_app(store))


def _ids(store: Path) -> list[str]:
    return sorted(
        p.name for p in store.iterdir() if p.is_dir() and p.name != "showcase"
    )


def test_registry(client):
    body = client.get("/api/r/registry").json()
    assert [s["name"] for s in body["stages"]] == list(STAGE_NAMES)
    load = body["stages"][0]
    assert load["methods"] == ["nuscenes"] and load["requires"] == []
    assert "properties" in body["params_schema"]


def test_runs_newest_first(client, store):
    rows = client.get("/api/r/runs").json()
    assert [r["run_id"] for r in rows] == sorted(_ids(store), reverse=True)
    assert rows[0]["status"] == "ok" and rows[0]["parent"] is None
    assert rows[0]["scene_token"]


def test_run_manifest(client, store):
    rid = _ids(store)[0]
    resp = client.get(f"/api/r/runs/{rid}")
    assert resp.status_code == 200
    assert Manifest.model_validate(resp.json()).run_id == rid


def test_run_file(client, store):
    rid = _ids(store)[0]
    resp = client.get(f"/api/r/runs/{rid}/files/01_load/poses.json")
    assert resp.status_code == 200
    assert resp.content == (store / rid / "01_load" / "poses.json").read_bytes()


def test_bad_run_id_400(client):
    assert client.get("/api/r/runs/not-a-run").status_code == 400
    assert client.get("/api/r/runs/not-a-run/files/x").status_code == 400
    assert client.get("/api/r/compare?a=bad&b=bad").status_code == 400


def test_missing_run_404(client):
    rid = "20000101-000000-000000"
    assert client.get(f"/api/r/runs/{rid}").status_code == 404
    assert client.get(f"/api/r/runs/{rid}/files/x").status_code == 404


def test_missing_file_404(client, store):
    rid = _ids(store)[0]
    assert client.get(f"/api/r/runs/{rid}/files/nope.txt").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "../manifest.json",
        "01_load/../../manifest.json",
        "%2e%2e/manifest.json",
        "01_load/%2e%2e/%2e%2e/manifest.json",
        "%2Fetc%2Fpasswd",
        "%2fetc%2fpasswd",
    ],
)
def test_file_path_rejected(client, store, path):
    rid = _ids(store)[0]
    resp = client.get(f"/api/r/runs/{rid}/files/{path}")
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200


def test_file_symlink_outside_run_rejected(tmp_path):
    store = tmp_path / "runs"
    write_fake_runs(store, drives=1)
    rid = _ids(store)[0]
    secret = tmp_path / "secret.txt"
    secret.write_text("outside")
    (store / rid / "link.txt").symlink_to(secret)
    client = TestClient(create_app(store))
    assert client.get(f"/api/r/runs/{rid}/files/link.txt").status_code == 400


def test_compare_finds_changed_param(tmp_path):
    store = tmp_path / "runs"
    write_fake_runs(store, drives=2)
    a, b = _ids(store)
    # Change one param in run b's manifest (test copy only; real runs are never edited).
    path = store / b / "manifest.json"
    data = json.loads(path.read_text())
    data["params"]["ground"]["voxel_m"] = 0.123
    path.write_text(json.dumps(data))
    client = TestClient(create_app(store))
    diffs = client.get(f"/api/r/compare?a={a}&b={b}").json()
    by_path = {d["path"]: d for d in diffs}
    assert by_path["params.ground.voxel_m"]["b"] == 0.123
    assert by_path["params.ground.voxel_m"]["a"] != 0.123
    assert (
        "data.scene_token" not in by_path
    )  # only pipeline, params, metrics are compared


def test_compare_same_run_empty(client, store):
    rid = _ids(store)[0]
    assert client.get(f"/api/r/compare?a={rid}&b={rid}").json() == []


def test_no_write_routes(client, store):
    rid = _ids(store)[0]
    assert client.post(f"/api/w/runs/{rid}/cancel").status_code in (404, 405)


def test_cors_allows_only_panel_origin(client):
    ok = client.get("/api/r/registry", headers={"Origin": ALLOWED_ORIGIN})
    assert ok.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert ok.headers["access-control-allow-credentials"] == "true"
    other = client.get("/api/r/registry", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
