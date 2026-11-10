"""GPU lease: while a twin job that uses the GPU runs, unload the models loaded in Librarian's
ollama instances so the job has the card. Uses only the ollama HTTP API (/api/ps, then
/api/generate with keep_alive 0); never touches the containers. Ollama reloads a model on demand
the next time Librarian calls it, so nothing is restored. The outcome goes in the job record.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import contextmanager

from twin.contracts import STAGE_NAMES, Pipeline

GPU_STAGES = ("colour", "semantics")  # add splats when that stage exists
RECHECK_SECONDS = 15
HTTP_TIMEOUT = 5


def needs_gpu(job: dict, load=lambda v: v) -> bool:
    """True when a run/rerun job will run a GPU stage. `load` resolves a pipeline given as a path."""
    if job.get("type") not in ("run", "rerun"):
        return False
    first = STAGE_NAMES.index(job["from_stage"]) if job.get("type") == "rerun" else 0
    pipeline = load(job.get("pipeline")) or {}
    for stage in GPU_STAGES:
        # A stage the pipeline does not mention has its default: semantics is off by default, colour on.
        spec = pipeline.get(stage)
        on = spec.get("enabled", True) if spec else getattr(Pipeline(), stage).enabled
        if STAGE_NAMES.index(stage) >= first and on:
            return True
    return False


def endpoints() -> list[str]:
    """Ollama base URLs. TWIN_OLLAMA_URLS (comma list; empty disables) wins; else read the
    container IPs of every running container named *ollama* (the host reaches the docker bridge)."""
    env = os.environ.get("TWIN_OLLAMA_URLS")
    if env is not None:
        return [u.strip() for u in env.split(",") if u.strip()]
    try:
        names = subprocess.run(
            ["docker", "ps", "--filter", "name=ollama", "--format", "{{.Names}} {{.Image}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.splitlines()
        # The sme_ollama_gen* containers are nginx auth fronts (401, no models); skip them.
        names = [ln.split()[0] for ln in names if ln.split() and not ln.split()[-1].startswith("nginx")]
        if not names:
            return []
        fmt = "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}"
        out = subprocess.run(
            ["docker", "inspect", "--format", fmt, *names],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    return [f"http://{ip}:11434" for ip in out]


def free_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return int(out.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _call(url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, None if body is None else json.dumps(body).encode()
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read() or b"{}")


def unload_all(urls: list[str], record: dict) -> None:
    """Unload every loaded model at each endpoint; add what happened to record['unloaded'] and
    record['skipped'] (endpoints that refused or did not answer, e.g. 401 behind a gateway)."""
    for url in urls:
        try:
            models = [m["name"] for m in _call(f"{url}/api/ps").get("models", [])]
        except (OSError, ValueError) as exc:
            record["skipped"][url] = f"{type(exc).__name__}: {exc}"
            continue
        for model in models:
            try:
                _call(f"{url}/api/generate", {"model": model, "keep_alive": 0})
                record["unloaded"].append({"endpoint": url, "model": model})
            except (OSError, ValueError) as exc:
                record["errors"].append(f"{url} {model}: {type(exc).__name__}: {exc}")


@contextmanager
def lease(
    record: dict, urls: list[str] | None = None, recheck: float = RECHECK_SECONDS
):
    """Hold the GPU for the with-block. Fills `record` (the job's gpu_lease): endpoints, unloaded
    models, skipped endpoints, errors, free_mib_before / _after_unload / _after_job. A watcher
    unloads again if a model reloads mid-job. Never raises: a broken lease must not fail the job."""
    urls = endpoints() if urls is None else urls
    record.update(endpoints=urls, unloaded=[], skipped={}, errors=[])
    record["free_mib_before"] = free_mib()
    stop = threading.Event()
    try:
        unload_all(urls, record)
    except Exception as exc:  # noqa: BLE001
        record["errors"].append(f"{type(exc).__name__}: {exc}")
    # Loud, not silent: a lease that reached no ollama frees nothing, and a big job may OOM.
    record["ok"] = any(u not in record["skipped"] for u in urls)
    if not record["ok"]:
        print(
            f"gpulease WARNING: reached no ollama endpoint (found {len(urls)}); VRAM not freed: {record['skipped']}",
            file=sys.stderr,
        )
    before = record["free_mib_before"]
    for _ in range(
        20
    ):  # ollama frees the memory a moment after the unload call returns
        record["free_mib_after_unload"] = free_mib()
        if (
            not record["unloaded"]
            or before is None
            or record["free_mib_after_unload"] > before
        ):
            break
        time.sleep(0.5)

    def watch():
        while not stop.wait(recheck):
            try:
                unload_all([u for u in urls if u not in record["skipped"]], record)
            except Exception as exc:  # noqa: BLE001
                record["errors"].append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield record
    finally:
        stop.set()
        thread.join()
        record["free_mib_after_job"] = free_mib()
