"""Write routes (/api/w/*): Access check, validation, busy, low disk. Synthetic data only."""

import re
import time

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock, Timeout

from twin import registry, runner
from twin.access import DevNoAuth, verifier_from_env
from twin.api import ALLOWED_ORIGIN, create_app
from twin.contracts import STAGE_NAMES, STAGES, Manifest, StageResult

RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
GB = 1024**3
NEW = "/api/w/runs"


@pytest.fixture(autouse=True)
def roomy_disk(monkeypatch):
    monkeypatch.setattr(runner, "free_bytes", lambda path: 100 * GB)


@pytest.fixture
def stubs(monkeypatch):
    """Empty registry plus stub stages that write one file each and succeed."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    for name in STAGE_NAMES:

        def run(ctx, params, name=name):
            (ctx.stage_dir(name) / "out.txt").write_text(name)
            return StageResult(status="ok")

        registry.register(name, STAGES[name].methods[0])(run)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "runs"
    path.mkdir()
    return path


@pytest.fixture
def client(store, access):
    return TestClient(create_app(store, access.verifier))


@pytest.fixture
def auth(access):
    return {"Cf-Access-Jwt-Assertion": access.token()}


def wait_idle(store) -> None:
    """Block until the worker thread has released the run store lock."""
    deadline = time.time() + 10
    while True:
        lock = FileLock(str(store / runner.LOCK_FILE), thread_local=False)
        try:
            lock.acquire(timeout=0)
            lock.release()
            return
        except Timeout:
            assert time.time() < deadline, "run did not finish"
            time.sleep(0.02)


def _manifest(store, run_id) -> Manifest:
    return Manifest.model_validate_json((store / run_id / "run.json").read_text())


def _start(client, auth) -> str:
    resp = client.post(NEW, json={"scene_token": "scene-1"}, headers=auth)
    assert resp.status_code == 202, resp.text
    return resp.json()["run_id"]


# ---- Access: section 8 security items


def test_valid_token_starts_run(client, auth, store, stubs):
    run_id = _start(client, auth)
    assert RUN_ID.fullmatch(run_id)
    # The folder and manifest exist when the response is sent; stages run in a thread.
    assert (store / run_id / "run.json").is_file()
    wait_idle(store)
    manifest = _manifest(store, run_id)
    assert {s.name for s in manifest.stages if s.status != "ok"} == {"semantics", "splats"}  # off by default
    assert len(manifest.stages) == len(STAGE_NAMES)
    assert (store / run_id / "1_load" / "out.txt").read_text() == "load"


def test_missing_header_401(client, store, stubs):
    resp = client.post(NEW, json={"scene_token": "scene-1"})
    assert resp.status_code == 401
    assert not any(p.is_dir() for p in store.iterdir())


@pytest.mark.parametrize(
    "token_kwargs, status",
    [
        ({"key": "forged"}, 401),  # wrong signature: signed with another key
        ({"aud": "other-app"}, 401),
        ({"exp_in": -10}, 401),  # expired
        ({"iss": "https://evil.cloudflareaccess.com"}, 401),
        ({"alg": "HS256"}, 401),
        ({"email": "someone@example.com"}, 403),
    ],
    ids=["forged", "wrong-aud", "expired", "wrong-iss", "hs256", "wrong-email"],
)
def test_bad_token_refused(client, store, stubs, access, token_kwargs, status):
    kwargs = dict(token_kwargs)
    if kwargs.get("key") == "forged":
        kwargs["key"] = access.forged
    token = access.token(**kwargs)
    resp = client.post(NEW, json={"scene_token": "scene-1"}, headers={
        "Cf-Access-Jwt-Assertion": token
    })
    assert resp.status_code == status, resp.text
    assert not any(p.is_dir() for p in store.iterdir())


def test_cancel_and_rerun_need_token(client, store, stubs):
    run_id = "20000101-000000-abcdef"
    assert client.post(f"/api/w/runs/{run_id}/cancel").status_code == 401
    assert client.post(f"/api/w/runs/{run_id}/rerun", json={"from_stage": "load"}).status_code == 401


def test_cors_preflight_allows_panel_origin(client):
    resp = client.options(
        NEW,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"


# ---- validation and refusals


def test_invalid_pipeline_422(client, auth, store, stubs):
    body = {"scene_token": "scene-1", "pipeline": {"mask": {"method": "nope"}}}
    resp = client.post(NEW, json=body, headers=auth)
    assert resp.status_code == 422
    assert "stage mask: method 'nope' not in" in resp.text
    assert not any(p.is_dir() for p in store.iterdir())


def test_unknown_param_422(client, auth, store, stubs):
    resp = client.post(NEW, json={"scene_token": "scene-1", "params": {"bogus": 1}}, headers=auth)
    assert resp.status_code == 422


def test_earlier_stage_rerun_422(client, auth, store, stubs):
    parent = _start(client, auth)
    wait_idle(store)
    body = {"from_stage": "features", "params": {"mask": {"box_margin_m": 0.5}}}
    resp = client.post(f"/api/w/runs/{parent}/rerun", json=body, headers=auth)
    assert resp.status_code == 422
    assert "re-run from stage mask" in resp.text
    assert len([p for p in store.iterdir() if p.is_dir()]) == 1


def test_rerun_from_later_stage_202(client, auth, store, stubs):
    parent = _start(client, auth)
    wait_idle(store)
    body = {"from_stage": "ground", "params": {"ground": {"voxel_m": 0.1}}}
    resp = client.post(f"/api/w/runs/{parent}/rerun", json=body, headers=auth)
    assert resp.status_code == 202, resp.text
    child = resp.json()["run_id"]
    wait_idle(store)
    manifest = _manifest(store, child)
    assert manifest.parent.run_id == parent and manifest.parent.from_stage == "ground"
    assert manifest.params.ground.voxel_m == 0.1


def test_rerun_unknown_run_404(client, auth, stubs):
    resp = client.post(
        "/api/w/runs/20000101-000000-abcdef/rerun", json={"from_stage": "load"}, headers=auth
    )
    assert resp.status_code == 404


def test_bad_run_id_400(client, auth, stubs):
    assert client.post("/api/w/runs/not-a-run/cancel", headers=auth).status_code == 400


def test_busy_409(client, auth, store, stubs):
    holder = FileLock(str(store / runner.LOCK_FILE), thread_local=False)
    holder.acquire()
    try:
        resp = client.post(NEW, json={"scene_token": "scene-1"}, headers=auth)
    finally:
        holder.release()
    assert resp.status_code == 409
    assert "another run is in progress" in resp.text


def test_low_disk_507(client, auth, store, stubs, monkeypatch):
    monkeypatch.setattr(runner, "free_bytes", lambda path: 5 * GB)
    resp = client.post(NEW, json={"scene_token": "scene-1"}, headers=auth)
    assert resp.status_code == 507
    assert "need 10 GB" in resp.text


def test_cancel_marks_request_and_unknown_404(client, auth, store, stubs):
    run_id = _start(client, auth)
    wait_idle(store)
    assert client.post(f"/api/w/runs/{run_id}/cancel", headers=auth).status_code == 202
    assert (store / run_id / runner.CANCEL_FILE).exists()
    missing = "20000101-000000-abcdef"
    assert client.post(f"/api/w/runs/{missing}/cancel", headers=auth).status_code == 404


# ---- startup refusal


def test_app_refuses_to_start_without_access_config(store, monkeypatch):
    monkeypatch.delenv("TWIN_DEV_NO_AUTH", raising=False)
    monkeypatch.delenv("TWIN_ACCESS_AUD", raising=False)
    monkeypatch.delenv("TWIN_OPERATOR_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="TWIN_ACCESS_AUD"):
        create_app(store)


def test_env_builds_access_verifier(monkeypatch):
    monkeypatch.delenv("TWIN_DEV_NO_AUTH", raising=False)
    monkeypatch.setenv("TWIN_ACCESS_AUD", "aud-tag")
    monkeypatch.setenv("TWIN_OPERATOR_EMAIL", "op@example.com")
    monkeypatch.delenv("TWIN_ACCESS_TEAM", raising=False)
    verifier = verifier_from_env()
    assert verifier.issuer == "https://papyrus.cloudflareaccess.com"
    assert verifier.aud == "aud-tag" and verifier.operator_email == "op@example.com"
    assert isinstance(DevNoAuth(), DevNoAuth)


# ---- sign-in helpers for the developer panel (ticket 13b)


def test_whoami_needs_token(client):
    assert client.get("/api/w/whoami").status_code == 401


def test_whoami_returns_operator_email(client, auth):
    resp = client.get("/api/w/whoami", headers=auth)
    assert resp.status_code == 200
    assert resp.json() == {"email": "operator@example.com"}


def test_signin_redirects_to_panel_page(client, auth):
    target = f"{ALLOWED_ORIGIN}/dev/?run=1"
    resp = client.get("/api/w/signin", params={"next": target}, headers=auth, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == target


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/",
        "https://twin.papyrus-ai.net.evil.example/",
        "https://twin.papyrus-ai.net@evil.example/",
        "https://twin.papyrus-ai.netx/",
        "http://twin.papyrus-ai.net/",
        "//evil.example/",
        "/dev",
        "javascript:alert(1)",
        "https://twin.papyrus-ai.net/é",  # non-ASCII would break the Location header
        "https://twin.papyrus-ai.net/\nSet-Cookie: x=1",
        "",
    ],
)
def test_signin_refuses_other_targets(client, auth, target):
    resp = client.get("/api/w/signin", params={"next": target}, headers=auth, follow_redirects=False)
    assert resp.status_code == 400
    assert "location" not in resp.headers


def test_signin_needs_token(client):
    resp = client.get(
        "/api/w/signin", params={"next": f"{ALLOWED_ORIGIN}/dev/"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_signin_extra_origin_only_when_env_set(store, access, monkeypatch, auth):
    local = "http://127.0.0.1:3000"
    target = f"{local}/dev/"
    monkeypatch.delenv("TWIN_EXTRA_ORIGIN", raising=False)
    client = TestClient(create_app(store, access.verifier))
    resp = client.get("/api/w/signin", params={"next": target}, headers=auth, follow_redirects=False)
    assert resp.status_code == 400

    monkeypatch.setenv("TWIN_EXTRA_ORIGIN", local)
    client = TestClient(create_app(store, access.verifier))
    resp = client.get("/api/w/signin", params={"next": target}, headers=auth, follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == target


# ---- M7 additions ----

from twin import labels as _labels_store
from twin.contracts import SiteMeta as _SiteMeta


def _make_site(store, site="site1", frozen=False, approved=False):
    meta = _SiteMeta(
        id=site,
        role="dev",
        polygon={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        version=1,
        created_at="2024-01-01T00:00:00Z",
        source_area="area",
        frozen=frozen,
        approved_by="op" if approved else None,
        approved_at="2024-01-02T00:00:00Z" if approved else None,
    )
    _labels_store.write_site(store, site, meta)
    _labels_store.labels_path(store, site).write_text('{"type": "FeatureCollection", "features": []}\n')
    return site


def test_tool_page_loopback_served(store, access):
    site = _make_site(store)
    d = _labels_store.labels_dir(store, site)
    d.mkdir(parents=True, exist_ok=True)
    (d / "tool.html").write_text("<html>tool</html>")
    client = TestClient(create_app(store, access.verifier), base_url="http://127.0.0.1:8090", client=("127.0.0.1", 50000))
    resp = client.get(f"/api/r/labels/{site}/tool")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert resp.headers.get("cache-control") == "no-store"


def test_tool_page_refused_for_non_loopback_peer(store, access):
    site = _make_site(store)
    d = _labels_store.labels_dir(store, site)
    d.mkdir(parents=True, exist_ok=True)
    (d / "tool.html").write_text("<html>tool</html>")
    client = TestClient(create_app(store, access.verifier))
    resp = client.get(f"/api/r/labels/{site}/tool")
    assert resp.status_code == 404


def test_tool_page_refused_for_non_loopback_host(store, access):
    site = _make_site(store)
    d = _labels_store.labels_dir(store, site)
    d.mkdir(parents=True, exist_ok=True)
    (d / "tool.html").write_text("<html>tool</html>")
    client = TestClient(create_app(store, access.verifier), base_url="http://127.0.0.1:8090", client=("127.0.0.1", 50000))
    resp = client.get(f"/api/r/labels/{site}/tool", headers={"Host": "evil.example"})
    assert resp.status_code == 404


def test_tool_page_missing_file_404(store, access):
    site = _make_site(store)
    client = TestClient(create_app(store, access.verifier), base_url="http://127.0.0.1:8090", client=("127.0.0.1", 50000))
    resp = client.get(f"/api/r/labels/{site}/tool")
    assert resp.status_code == 404


def test_tool_page_missing_site_404(store, access):
    client = TestClient(create_app(store, access.verifier), base_url="http://127.0.0.1:8090", client=("127.0.0.1", 50000))
    resp = client.get("/api/r/labels/nope/tool")
    assert resp.status_code == 404


def test_tool_page_bad_site_422(store, access):
    client = TestClient(create_app(store, access.verifier), base_url="http://127.0.0.1:8090", client=("127.0.0.1", 50000))
    resp = client.get("/api/r/labels/bad..site/tool")
    assert resp.status_code == 422


@pytest.mark.parametrize("control", ["signalised", "stop_controlled", "uncontrolled", "mid_block"])
def test_site_meta_put_each_control_value(store, access, control):
    site = _make_site(store)
    client = TestClient(create_app(store, access.verifier))
    auth = {"Cf-Access-Jwt-Assertion": access.token()}
    before = client.get(f"/api/r/labels/{site}").json()
    resp = client.put(f"/api/w/labels/{site}", json={"control": control, "notes": "n1"}, headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control"] == control
    assert body["notes"] == "n1"
    assert body["version"] == before["version"]


def test_site_meta_put_invalid_control_422(store, access):
    site = _make_site(store)
    client = TestClient(create_app(store, access.verifier))
    auth = {"Cf-Access-Jwt-Assertion": access.token()}
    resp = client.put(f"/api/w/labels/{site}", json={"control": "bogus"}, headers=auth)
    assert resp.status_code == 422


def test_site_meta_put_needs_token_401(store, access):
    site = _make_site(store)
    client = TestClient(create_app(store, access.verifier))
    resp = client.put(f"/api/w/labels/{site}", json={"control": "mid_block"})
    assert resp.status_code == 401


def test_site_meta_put_missing_site_404(store, access):
    client = TestClient(create_app(store, access.verifier))
    auth = {"Cf-Access-Jwt-Assertion": access.token()}
    resp = client.put("/api/w/labels/nope", json={"control": "mid_block"}, headers=auth)
    assert resp.status_code == 404


def test_site_meta_put_allowed_when_frozen(store, access):
    site = _make_site(store, frozen=True, approved=True)
    client = TestClient(create_app(store, access.verifier))
    auth = {"Cf-Access-Jwt-Assertion": access.token()}
    resp = client.put(f"/api/w/labels/{site}", json={"control": "mid_block"}, headers=auth)
    assert resp.status_code == 200
    # labels PUT is 423
    body = {"version": 1, "feature_collection": {"type": "FeatureCollection", "features": []}}
    resp2 = client.put(f"/api/w/labels/{site}/labels", json=body, headers=auth)
    assert resp2.status_code == 423


def test_labels_put_then_get_reflects_edit(store, access):
    site = _make_site(store)
    client = TestClient(create_app(store, access.verifier))
    auth = {"Cf-Access-Jwt-Assertion": access.token()}
    feat = {
        "type": "Feature",
        "id": "op-1",
        "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
        "properties": {
            "id": "op-1",
            "element": "marking",
            "type": "solid_line",
            "origin": "operator",
        },
    }
    fc = {"type": "FeatureCollection", "features": [feat]}
    body = {"version": 1, "feature_collection": fc}
    resp = client.put(f"/api/w/labels/{site}/labels", json=body, headers=auth)
    assert resp.status_code == 200, resp.text
    # edit coordinate
    feat2 = dict(feat)
    feat2["geometry"] = {"type": "LineString", "coordinates": [[2.0, 3.0], [4.0, 5.0]]}
    body2 = {"version": 1, "feature_collection": {"type": "FeatureCollection", "features": [feat2]}}
    resp2 = client.put(f"/api/w/labels/{site}/labels", json=body2, headers=auth)
    assert resp2.status_code == 200, resp2.text
    got = client.get(f"/api/r/labels/{site}/labels").json()
    assert got["features"][0]["properties"]["id"] == "op-1"
    assert got["features"][0]["geometry"]["coordinates"] == [[2.0, 3.0], [4.0, 5.0]]


def test_labels_put_stale_version_409(store, access):
    site = _make_site(store)
    client = TestClient(create_app(store, access.verifier))
    auth = {"Cf-Access-Jwt-Assertion": access.token()}
    # bump version
    client.post(f"/api/w/labels/{site}/new-version", headers=auth)
    # now meta version 2; put labels with old version 1 -> 409
    body = {"version": 1, "feature_collection": {"type": "FeatureCollection", "features": []}}
    resp = client.put(f"/api/w/labels/{site}/labels", json=body, headers=auth)
    assert resp.status_code == 409
    # equal version last-writer-wins: put with current version 2 -> 200, version stays 2
    body2 = {"version": 2, "feature_collection": {"type": "FeatureCollection", "features": []}}
    resp2 = client.put(f"/api/w/labels/{site}/labels", json=body2, headers=auth)
    assert resp2.status_code == 200
    assert resp2.json()["version"] == 2


def test_latlon_endpoint_test_point(store, access):
    client = TestClient(create_app(store, access.verifier))
    resp = client.get("/api/r/geo/latlon", params={"x": 332414.0, "y": 4690067.2})
    assert resp.status_code == 200
    assert resp.json() == {"lat": 42.344822, "lon": -71.034536}


def test_serve_refuses_dev_auth_on_public_host(store, monkeypatch):
    monkeypatch.setenv("TWIN_DEV_NO_AUTH", "1")
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    from twin.api import serve_command
    rc = serve_command(store, "0.0.0.0", 8090)
    assert rc == 2
    # positive arm: loopback is not refused
    called = {"n": 0}

    def _run(*a, **k):
        called["n"] += 1

    monkeypatch.setattr(uvicorn, "run", _run)
    rc2 = serve_command(store, "127.0.0.1", 8090)
    assert rc2 != 2
    assert called["n"] == 1
