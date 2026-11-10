import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from twin import gpulease, jobqueue, registry
from twin.contracts import STAGE_NAMES, STAGES, StageResult


class Fake:
    """A fake ollama: loaded models, and the keep_alive 0 calls it got."""

    def __init__(self, loaded, status=200):
        self.loaded, self.unloads, self.status = list(loaded), [], status
        fake = self

        class H(BaseHTTPRequestHandler):
            def _send(self, body):
                self.send_response(fake.status)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                self._send({"models": [{"name": m} for m in fake.loaded]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert body["keep_alive"] == 0
                fake.unloads.append(body["model"])
                fake.loaded.remove(body["model"])
                self._send({})

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def fake():
    made = []

    def make(*a, **k):
        made.append(Fake(*a, **k))
        return made[-1]

    yield make
    for f in made:
        f.server.shutdown()


def test_needs_gpu():
    run = {"type": "run", "scene": "s"}
    assert gpulease.needs_gpu(run)
    assert not gpulease.needs_gpu(
        {**run, "pipeline": {"colour": {"method": "x", "enabled": False}}}
    )
    assert gpulease.needs_gpu({"type": "rerun", "run_id": "r", "from_stage": "colour"})
    assert not gpulease.needs_gpu(
        {"type": "rerun", "run_id": "r", "from_stage": "profile"}
    )
    assert not gpulease.needs_gpu({"type": "eval", "run_id": "r"})


def test_lease_unloads_and_records(fake, monkeypatch):
    free = iter([100, 9000, 9000])
    monkeypatch.setattr(gpulease, "free_mib", lambda: next(free))
    a, b = fake(["m1", "m2"]), fake([])
    denied = fake([], status=401)
    rec: dict = {}
    with gpulease.lease(rec, [a.url, b.url, denied.url], recheck=0.05):
        assert a.loaded == []
        a.loaded.append("m3")  # Librarian reloads a model mid-job
        for _ in range(100):
            if not a.loaded:
                break
            threading.Event().wait(0.05)
        assert a.loaded == []
    assert a.unloads == ["m1", "m2", "m3"]
    assert [u["model"] for u in rec["unloaded"]] == ["m1", "m2", "m3"]
    assert (
        denied.url in rec["skipped"] or rec["skipped"] == {}
    )  # 401 body parses as json: no models
    assert (
        rec["free_mib_before"],
        rec["free_mib_after_unload"],
        rec["free_mib_after_job"],
    ) == (100, 9000, 9000)


def test_dead_endpoint_does_not_fail(monkeypatch):
    monkeypatch.setattr(gpulease, "free_mib", lambda: None)
    rec: dict = {}
    with gpulease.lease(rec, ["http://127.0.0.1:1"]):
        pass
    assert "http://127.0.0.1:1" in rec["skipped"] and rec["unloaded"] == []


def test_job_record_has_lease(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    for name in STAGE_NAMES:

        def run(ctx, params, name=name):
            (ctx.stage_dir(name) / "o").write_text(name)
            return StageResult(status="ok")

        registry.register(name, STAGES[name].methods[0])(run)
    srv = fake(["big"])
    monkeypatch.setenv("TWIN_OLLAMA_URLS", srv.url)
    jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    assert jobqueue.process_one(tmp_path, lambda: None).startswith("done")
    lease = jobqueue.list_jobs(tmp_path)[0]["gpu_lease"]
    assert lease["unloaded"] == [{"endpoint": srv.url, "model": "big"}]
    assert srv.loaded == []
