"""Run Record naming and core-record evaluation.

The twin Run Record is `run.json` (same fields as the old `manifest.json`).
Legacy runs may still have only `manifest.json`; readers resolve and fall back.
Core (recon-core) Run Records have a different shape; `eval_document` converts
them into the metric/stage view `twin.gates.evaluate` consumes.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from twin.contracts import Manifest

RUN_FILE = "run.json"
LEGACY_FILE = "manifest.json"
CORE_KEYS = {"version", "pipeline", "manifest_hash", "core_version", "nodes"}


def record_path(run_dir: Path) -> Path:
    """The record file to read: run.json if present, else manifest.json."""
    run_dir = Path(run_dir)
    run = run_dir / RUN_FILE
    if run.is_file():
        return run
    return run_dir / LEGACY_FILE


def read_record(run_dir: Path) -> dict[str, Any]:
    """Read the run record as plain JSON."""
    path = record_path(run_dir)
    return json.loads(path.read_text())


def read_manifest(run_dir: Path) -> Manifest:
    """Read and validate the twin Run Record."""
    return Manifest.model_validate(read_record(run_dir))


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def write_record(run_dir: Path, manifest: Manifest) -> None:
    """Atomically write the twin Run Record as run.json."""
    text = Manifest.model_validate(manifest.model_dump(mode="json")).model_dump_json(indent=2)
    _atomic_write(Path(run_dir) / RUN_FILE, text + "\n")


def write_document(run_dir: Path, doc: dict[str, Any]) -> None:
    """Atomically write a Run Record document as run.json."""
    _atomic_write(Path(run_dir) / RUN_FILE, json.dumps(doc, indent=2) + "\n")


def is_core_record(doc: dict[str, Any]) -> bool:
    """A recon-core Run Record (v1) has these top-level keys."""
    return isinstance(doc, dict) and CORE_KEYS.issubset(doc.keys())


def _nest_dotted(flat: dict[str, Any]) -> dict[str, Any]:
    """Nest dotted keys into dicts, inverse of contracts.flatten for dict leaves."""
    out: dict[str, Any] = {}
    for key, value in flat.items():
        cur = out
        parts = key.split(".")
        for part in parts[:-1]:
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt
        cur[parts[-1]] = value
    return out


def eval_document(doc: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Return {run_id, metrics, stages} for twin.gates.evaluate.

    Twin records pass through (with run_id defaulted). Core records map each
    node's checks into nested metrics under metrics[node.name], sum duration_s
    into runtime.total_min, and emit stages with seconds = node duration_s.
    """
    if not is_core_record(doc):
        return {
            "run_id": doc.get("run_id", run_id),
            "metrics": doc.get("metrics", {}),
            "stages": doc.get("stages", []),
        }

    metrics: dict[str, Any] = {}
    total_s = 0.0
    stages = []
    for node in doc.get("nodes", []):
        name = node.get("name")
        duration = node.get("duration_s")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            total_s += float(duration)
            stages.append({"seconds": float(duration)})
        checks = node.get("checks") or []
        flat: dict[str, Any] = {}
        for check in checks:
            cname = check.get("name")
            if isinstance(cname, str):
                flat[cname] = check.get("value")
        nested = _nest_dotted(flat)
        if name:
            node_metrics = metrics.get(name)
            if isinstance(node_metrics, dict):
                node_metrics.update(nested)
            else:
                metrics[name] = nested

    metrics["runtime"] = {"total_min": round(total_s / 60.0, 3)}
    return {"run_id": doc.get("run_id", run_id), "metrics": metrics, "stages": stages}
