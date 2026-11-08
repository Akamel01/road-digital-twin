"""Control API read routes (/api/r/*). Spec: docs/design/twin-v1-spec.md, sections 3 and 4.

Read-only and public. Write routes (/api/w/*) come in ticket 11b and reuse the
CORS settings here. There is no shell access and no subprocess call.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from twin.contracts import STAGE_NAMES, STAGES, Manifest, Params
from twin.runner import default_store

ALLOWED_ORIGIN = "https://twin.papyrus-ai.net"
RUN_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
COMPARE_SECTIONS = ("pipeline", "params", "metrics")


def _check_id(run_id: str) -> None:
    if not RUN_ID.fullmatch(run_id):
        raise HTTPException(400, "bad run id")


def _load(store: Path, run_id: str) -> Manifest:
    _check_id(run_id)
    path = store / run_id / "manifest.json"
    if not path.is_file():
        raise HTTPException(404, "run not found")
    return Manifest.model_validate_json(path.read_text())


def _status(m: Manifest) -> str:
    statuses = {s.status for s in m.stages}
    for name in ("failed", "cancelled", "running", "pending"):
        if name in statuses:
            return name
    return "ok" if statuses else "pending"


def _flat(node: Any, path: str = "") -> dict[str, Any]:
    """Leaf values keyed by dotted path; list items as [i]."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(_flat(value, f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(node, list):
        out = {}
        for i, value in enumerate(node):
            out.update(_flat(value, f"{path}[{i}]"))
        return out
    return {path: node}


def _safe_file(run_dir: Path, rel: str) -> Path:
    parts = PurePosixPath(rel)
    if not rel or "\\" in rel or parts.is_absolute() or ".." in parts.parts:
        raise HTTPException(400, "bad file path")
    target = (run_dir / rel).resolve()
    if not target.is_relative_to(run_dir.resolve()):
        raise HTTPException(400, "bad file path")
    return target


def create_app(store: Path) -> FastAPI:
    app = FastAPI(title="twin control API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/r/registry")
    def registry_route() -> dict[str, Any]:
        return {
            "stages": [
                {
                    "name": name,
                    "number": STAGES[name].number,
                    "methods": list(STAGES[name].methods),
                    "requires": list(STAGES[name].requires),
                    "outputs": list(STAGES[name].outputs),
                    "optional": STAGES[name].optional,
                }
                for name in STAGE_NAMES
            ],
            "params_schema": Params.model_json_schema(),
        }

    @app.get("/api/r/runs")
    def list_runs() -> list[dict[str, Any]]:
        if not store.is_dir():
            return []
        rows = []
        for folder in store.iterdir():
            if not (RUN_ID.fullmatch(folder.name) and folder.is_dir()):
                continue
            try:
                m = Manifest.model_validate_json((folder / "manifest.json").read_text())
            except (OSError, ValueError):
                continue  # no readable manifest yet: not a run to list
            rows.append(
                {
                    "run_id": m.run_id,
                    "scene_token": m.data.scene_token,
                    "parent": m.parent.run_id if m.parent else None,
                    "status": _status(m),
                    "started": f"{m.run_id[:8]}T{m.run_id[9:15]}Z",
                }
            )
        return sorted(rows, key=lambda r: r["run_id"], reverse=True)

    @app.get("/api/r/runs/{run_id}")
    def get_run(run_id: str) -> Manifest:
        return _load(store, run_id)

    @app.get("/api/r/runs/{run_id}/files/{path:path}")
    def get_file(run_id: str, path: str) -> FileResponse:
        _check_id(run_id)
        run_dir = store / run_id
        if not run_dir.is_dir():
            raise HTTPException(404, "run not found")
        target = _safe_file(run_dir, path)
        if not target.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(target)

    @app.get("/api/r/compare")
    def compare(a: str = Query(...), b: str = Query(...)) -> list[dict[str, Any]]:
        dump_a = _load(store, a).model_dump(mode="json")
        dump_b = _load(store, b).model_dump(mode="json")
        flat_a = _flat({k: dump_a[k] for k in COMPARE_SECTIONS})
        flat_b = _flat({k: dump_b[k] for k in COMPARE_SECTIONS})
        return [
            {"path": p, "a": flat_a.get(p), "b": flat_b.get(p)}
            for p in sorted(set(flat_a) | set(flat_b))
            if p not in flat_a or p not in flat_b or flat_a[p] != flat_b[p]
        ]

    return app


def serve_command(store: Path | None, host: str, port: int) -> int:
    import uvicorn

    uvicorn.run(create_app(store or default_store()), host=host, port=port)
    return 0
