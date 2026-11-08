"""Run store: make a run folder, run enabled stages in order, keep manifest.json current.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4 and 8.
"""

import hashlib
import logging
import os
import re
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
from pydantic import BaseModel

from twin import registry
from twin.contracts import (
    STAGE_NAMES,
    STAGES,
    Manifest,
    ManifestCode,
    ManifestData,
    ManifestParent,
    ManifestStage,
    OsmNames,
    Params,
    Pipeline,
    StageResult,
    check_rerun,
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
    pipeline, params = _checked(scene_token, pipeline, params)
    return _execute_run(Path(store), scene_token, pipeline, params)


def _checked(scene_token: str, pipeline: Any, params: Any) -> tuple[Pipeline, Params]:
    pipeline = Pipeline.model_validate(pipeline)
    params = Params.model_validate(params)
    if not scene_token:
        raise ValueError("scene token is empty")
    for name in STAGE_NAMES:
        stage = getattr(pipeline, name)
        if stage.enabled and registry.lookup(name, stage.method) is None:
            raise ValueError(f"stage {name}: no registered method {stage.method!r}")
    return pipeline, params


def _link_stage(parent_dir: Path, run_dir: Path, name: str) -> None:
    """Hard-link every file of a parent stage folder into the new run. Dirs are recreated."""
    src = parent_dir / f"{STAGES[name].number}_{name}"
    if not src.is_dir():
        return
    dst = run_dir / src.name
    dst.mkdir()
    for path in sorted(src.rglob("*")):
        target = dst / path.relative_to(src)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, target)


def _execute_run(
    store: Path,
    scene_token: str,
    pipeline: Pipeline,
    params: Params,
    parent_dir: Path | None = None,
    parent: Manifest | None = None,
    from_stage: str | None = None,
) -> str:
    """Create a run folder and run the stages. For a re-run (parent set), stages
    before from_stage are hard-linked from parent_dir and not run."""
    store.mkdir(parents=True, exist_ok=True)
    run_id, run_dir = _create_run_dir(store)
    (run_dir / "pipeline.yaml").write_text(
        yaml.safe_dump(pipeline.model_dump(mode="json"), sort_keys=False)
    )
    (run_dir / "params.yaml").write_text(
        yaml.safe_dump(params.model_dump(mode="json"), sort_keys=False)
    )

    if parent is None:
        data = ManifestData(
            scene_token=scene_token,
            # Placeholder: the date of this run. The load stage should record the real Overpass query date.
            osm_names=OsmNames(overpass_query_date=datetime.now(UTC).date()),
        )
        parent_ref = None
    else:
        data = parent.data
        parent_ref = ManifestParent(run_id=parent.run_id, from_stage=from_stage)
    manifest = Manifest(
        run_id=run_id,
        parent=parent_ref,
        code=_code_info(),
        data=data,
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
    keep = STAGES[from_stage].number - 1 if from_stage else 0
    for index, name in enumerate(STAGE_NAMES):
        stage = getattr(pipeline, name)
        if index < keep:  # earlier stage of a re-run: linked from the parent, not run
            _link_stage(parent_dir, run_dir, name)
            manifest.stages.append(next(s for s in parent.stages if s.name == name))
            if name in parent.metrics:
                manifest.metrics[name] = parent.metrics[name]
            _write_manifest(run_dir, manifest)
            continue
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


def _load_yaml(path: Path | None) -> Any:
    return None if path is None else (yaml.safe_load(path.read_text()) or {})


def _deep_merge(base: dict[str, Any], over: Any) -> dict[str, Any]:
    if not isinstance(over, dict):
        raise TypeError("override must be a mapping")
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _merge(base: BaseModel, override: Any, model: type) -> Any:
    """Parent values overridden by the given partial dict or model (set fields only)."""
    if override is None:
        return base
    if isinstance(override, BaseModel):
        override = override.model_dump(mode="json", exclude_unset=True)
    return model.model_validate(_deep_merge(base.model_dump(mode="json"), override))


def rerun(
    store: Path | str,
    parent_run_id: str,
    from_stage: str,
    pipeline: Pipeline | dict[str, Any] | None = None,
    params: Params | dict[str, Any] | None = None,
) -> str:
    """Re-run stages from_stage and later of a parent run in a new run folder.

    Stages before from_stage are hard-linked from the parent. Returns the new run id.
    Raises ValueError, before creating any folder, when the re-run is refused.
    The parent folder is only read.
    """
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", parent_run_id):
        raise ValueError(f"bad run id {parent_run_id!r}")
    if from_stage not in STAGES:
        raise ValueError(f"unknown stage {from_stage!r}")
    store = Path(store)
    parent_dir = store / parent_run_id
    if not (parent_dir / "manifest.json").is_file():
        raise ValueError(f"run {parent_run_id} not found in {store}")
    parent = Manifest.model_validate_json((parent_dir / "manifest.json").read_text())
    parent_pipeline = Pipeline.model_validate(
        yaml.safe_load((parent_dir / "pipeline.yaml").read_text()) or {}
    )
    parent_params = Params.model_validate(
        yaml.safe_load((parent_dir / "params.yaml").read_text()) or {}
    )
    new_pipeline = _merge(parent_pipeline, pipeline, Pipeline)
    new_params = _merge(parent_params, params, Params)
    check_rerun(parent_pipeline, parent_params, new_pipeline, new_params, from_stage)

    by_name = {s.name: s for s in parent.stages}
    for name in STAGE_NAMES[: STAGES[from_stage].number - 1]:
        stage = by_name.get(name)
        if stage is None or stage.status not in ("ok", "skipped"):
            status = "missing" if stage is None else stage.status
            raise ValueError(
                f"parent run {parent_run_id} stage {name} is {status}; "
                f"cannot re-run from stage {from_stage}"
            )
    new_pipeline, new_params = _checked(
        parent.data.scene_token, new_pipeline, new_params
    )
    return _execute_run(
        store,
        parent.data.scene_token,
        new_pipeline,
        new_params,
        parent_dir=parent_dir,
        parent=parent,
        from_stage=from_stage,
    )


def _exit_code(store: Path, run_id: str) -> int:
    """1 when a stage of the run failed (message on stderr), else 0."""
    run_dir = store / run_id
    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    failed = [s for s in manifest.stages if s.status not in ("ok", "skipped")]
    if failed:
        print(
            f"twin: stage {failed[0].name} {failed[0].status}; see {run_dir / 'manifest.json'}",
            file=sys.stderr,
        )
        return 1
    return 0


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
    return _exit_code(Path(store), run_id)


def rerun_command(
    run_id: str,
    from_stage: str,
    pipeline_path: Path | None,
    params_path: Path | None,
    store: Path | None,
) -> int:
    """`twin rerun`. Exit 0 success, 1 a stage failed, 2 invalid or refused re-run."""
    store = store or default_store()
    try:
        new_id = rerun(
            store,
            run_id,
            from_stage,
            _load_yaml(pipeline_path),
            _load_yaml(params_path),
        )
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        print(f"twin rerun: {exc}", file=sys.stderr)
        return 2
    print(new_id)
    return _exit_code(Path(store), new_id)
