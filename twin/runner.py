"""Run store: make a run folder, run enabled stages in order, keep manifest.json current.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4 and 8.
"""

import hashlib
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from twin import registry
from twin.contracts import (
    STAGE_NAMES,
    STAGES,
    Manifest,
    ManifestCode,
    ManifestData,
    ManifestStage,
    OsmNames,
    Params,
    Pipeline,
    StageResult,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_STORE = "/data/twin-runs"

# The Params field each stage reads. outputs takes no parameters.
STAGE_PARAMS: dict[str, str | None] = {
    "load": "facilities",
    "mask": "mask",
    "align": "align",
    "ground": "ground",
    "features": "features",
    "colour": "colour",
    "profile": "profile",
    "isd": "isd",
    "accuracy": "accuracy",
    "outputs": None,
}


@dataclass
class StageContext:
    run_dir: Path
    scene_token: str
    seed: int
    log: logging.Logger

    def stage_dir(self, name: str) -> Path:
        return self.run_dir / f"{STAGES[name].number}_{name}"

    def input_dir(self, stage: str) -> Path:
        path = self.stage_dir(stage)
        if not path.is_dir():
            raise FileNotFoundError(
                f"stage {stage} has no output folder in {self.run_dir}"
            )
        return path


def default_store() -> Path:
    return Path(os.environ.get("TWIN_RUNS") or DEFAULT_STORE)


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout


def _code_info() -> ManifestCode:
    sha = (_git("rev-parse", "HEAD") or "").strip() or "unknown"
    dirty = bool((_git("status", "--porcelain") or "").strip())
    lock = REPO / "uv.lock"
    lock_sha = (
        hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else "unknown"
    )
    return ManifestCode(git_sha=sha, dirty=dirty, lockfile_sha256=lock_sha)


def _make_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def _create_run_dir(store: Path) -> tuple[str, Path]:
    while True:
        run_id = _make_run_id()
        run_dir = store / run_id
        try:
            run_dir.mkdir()  # fails if the folder exists: runs are never overwritten
        except FileExistsError:
            continue
        return run_id, run_dir


def _write_manifest(run_dir: Path, manifest: Manifest) -> None:
    # Re-validate every write, then replace atomically so readers never see a partial file.
    text = Manifest.model_validate(manifest.model_dump(mode="json")).model_dump_json(
        indent=2
    )
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix=".manifest-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(text + "\n")
    os.replace(tmp, run_dir / "manifest.json")


def _list_files(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(
        p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()
    )


def _run_stage(
    ctx: StageContext, name: str, method: str, params: Params
) -> StageResult:
    fn = registry.lookup(name, method)
    if fn is None:
        return StageResult(status="failed", message=f"no registered method {method!r}")
    field = STAGE_PARAMS[name]
    stage_params = getattr(params, field) if field else None
    try:
        result = fn(ctx, stage_params)
    except Exception as exc:  # a stage crash is a failed stage, not a runner crash
        ctx.log.exception("stage %s crashed", name)
        return StageResult(status="failed", message=f"{type(exc).__name__}: {exc}")
    if not isinstance(result, StageResult):
        return StageResult(status="failed", message=f"returned {type(result).__name__}")
    return result


def start_run(
    store: Path | str,
    scene_token: str,
    pipeline: Pipeline | dict[str, Any],
    params: Params | dict[str, Any],
) -> str:
    """Run the pipeline on one scene. Returns the run id.

    Raises ValueError before creating any folder when the input is invalid.
    A failed stage does not raise: it is recorded in manifest.json.
    """
    pipeline = Pipeline.model_validate(pipeline)
    params = Params.model_validate(params)
    if not scene_token:
        raise ValueError("scene token is empty")
    for name in STAGE_NAMES:
        stage = getattr(pipeline, name)
        if stage.enabled and registry.lookup(name, stage.method) is None:
            raise ValueError(f"stage {name}: no registered method {stage.method!r}")

    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    run_id, run_dir = _create_run_dir(store)
    (run_dir / "pipeline.yaml").write_text(
        yaml.safe_dump(pipeline.model_dump(mode="json"), sort_keys=False)
    )
    (run_dir / "params.yaml").write_text(
        yaml.safe_dump(params.model_dump(mode="json"), sort_keys=False)
    )

    manifest = Manifest(
        run_id=run_id,
        code=_code_info(),
        data=ManifestData(
            scene_token=scene_token,
            # Placeholder: the date of this run. The load stage should record the real Overpass query date.
            osm_names=OsmNames(overpass_query_date=datetime.now(UTC).date()),
        ),
        pipeline=pipeline,
        params=params,
    )
    _write_manifest(run_dir, manifest)

    ctx = StageContext(
        run_dir=run_dir,
        scene_token=scene_token,
        seed=params.seed,
        log=logging.getLogger("twin.run"),
    )
    for name in STAGE_NAMES:
        stage = getattr(pipeline, name)
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        if stage.enabled:
            ctx.stage_dir(name).mkdir()
            result = _run_stage(ctx, name, stage.method, params)
        else:
            result = StageResult(status="skipped", message="disabled in pipeline")
        if result.status not in ("ok", "skipped"):
            ctx.log.error(
                "run %s stage %s %s: %s", run_id, name, result.status, result.message
            )
        if result.metrics:
            manifest.metrics[name] = result.metrics
        manifest.stages.append(
            ManifestStage(
                name=name,
                method=stage.method,
                status=result.status,
                started=started,
                seconds=time.perf_counter() - t0,
                files=_list_files(ctx.stage_dir(name)),
            )
        )
        _write_manifest(run_dir, manifest)
        if result.status not in ("ok", "skipped"):
            break  # later stages stay pending: they are not in the manifest
    return run_id


def _load_model(path: Path | None, model: type) -> Any:
    if path is None:
        return model()
    return model.model_validate(yaml.safe_load(path.read_text()) or {})


def run_command(
    scene: str,
    pipeline_path: Path | None,
    params_path: Path | None,
    store: Path | None,
) -> int:
    """`twin run`. Exit 0 success, 1 a stage failed, 2 invalid input."""
    store = store or default_store()
    try:
        pipeline = _load_model(pipeline_path, Pipeline)
        params = _load_model(params_path, Params)
        run_id = start_run(store, scene, pipeline, params)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"twin run: {exc}", file=sys.stderr)
        return 2
    print(run_id)
    run_dir = Path(store) / run_id
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    failed = [s for s in manifest.stages if s.status not in ("ok", "skipped")]
    if failed:
        print(
            f"twin run: stage {failed[0].name} {failed[0].status}; see {run_dir / 'manifest.json'}",
            file=sys.stderr,
        )
        return 1
    return 0
