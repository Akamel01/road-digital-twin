"""Run one contract stage as a Node-ready command (A1.2)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml
from recon_core.checks import Check, write_checks

from twin import registry
from twin.contracts import STAGES, Params, Pipeline, StageResult, flatten, stage_dir
from twin.runner import StageContext
from twin.runrecord import read_record

STAGE_DIR_RE = re.compile(r"^(\d+)_([a-z]+)$")

# Inputs the stage code actually reads, beyond STAGES[name].requires (A1.2).
EXTRA_REQUIRES: dict[str, tuple[str, ...]] = {
    "features": ("load", "align", "ground"),
    "profile": ("load", "ground"),
    "isd": ("load", "mask", "align", "ground"),
    "accuracy": ("load", "features"),
}


def _stage_name_from_dir(path: Path) -> str | None:
    m = STAGE_DIR_RE.match(path.name)
    if not m or m.group(2) not in STAGES:
        return None
    if int(m.group(1)) != STAGES[m.group(2)].number:
        return None
    return m.group(2)


def _add_stage_dir(found: dict[str, Path], path: Path) -> None:
    name = _stage_name_from_dir(path)
    if name is not None:
        found[name] = path


def collect_inputs(inputs: list[Path]) -> dict[str, Path]:
    """Map stage name -> stage dir from run folders, stage dirs, or core node dirs."""
    found: dict[str, Path] = {}
    for raw in inputs:
        path = raw.expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"input is not a directory: {raw}")
        name = _stage_name_from_dir(path)
        if name is not None:
            found[name] = path
            continue
        # Run folder or node dir: scan children one level for <number>_<stage>.
        matched = False
        for child in sorted(path.iterdir()):
            if child.is_dir():
                before = len(found)
                _add_stage_dir(found, child)
                if len(found) != before:
                    matched = True
        if not matched:
            raise ValueError(f"input resolves to no stage dir: {raw}")
    return found


def required_inputs(name: str) -> tuple[str, ...]:
    req = list(STAGES[name].requires)
    for extra in EXTRA_REQUIRES.get(name, ()):  # preserve order, no dups
        if extra not in req:
            req.append(extra)
    return tuple(req)


def _scene_from_inputs(inputs: list[Path]) -> str | None:
    for raw in inputs:
        path = raw.expanduser().resolve()
        # If it's a run folder, it may have run.json/manifest.json.
        for candidate in (path, path.parent):
            try:
                doc = read_record(candidate)
            except (OSError, ValueError, TypeError):
                continue
            scene = doc.get("data", {}).get("scene_token")
            if isinstance(scene, str) and scene:
                return scene
    return None


def _load_params(params_path: Path | None) -> Params:
    if params_path is None:
        return Params()
    data = yaml.safe_load(params_path.read_text()) or {}
    return Params.model_validate(data)


def metrics_checks(metrics: dict[str, Any], status: str) -> list[Check]:
    checks: list[Check] = []
    for key, value in flatten(metrics).items():
        checks.append(Check(name=key, value=value, passed=True, threshold=None, unit=None))
    checks.append(
        Check(
            name="stage_ok",
            value=status,
            passed=status in ("ok", "skipped"),
            threshold=None,
            unit=None,
        )
    )
    return checks


def _write_node_outputs(out: Path, result: StageResult) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(result.metrics, sort_keys=True, indent=2) + "\n")
    write_checks(out, metrics_checks(result.metrics, result.status))


def _move_stage_output(tmp_root: Path, out: Path, name: str) -> None:
    src = stage_dir(tmp_root, name)
    dst = stage_dir(out, name)
    if not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    out.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def _carry_top_level(tmp_root: Path, out: Path, stage_name: str) -> None:
    stage_folder = f"{STAGES[stage_name].number}_{stage_name}"
    for child in tmp_root.iterdir():
        if child.name == stage_folder:
            continue
        if child.is_symlink():
            continue
        target = out / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(child), str(target))


def stage_command(
    name: str,
    inputs: list[Path],
    out: Path,
    method: str | None = None,
    params_path: Path | None = None,
    scene: str | None = None,
) -> int:
    if name not in STAGES:
        print(f"twin stage: unknown stage {name!r}", flush=True)
        return 2
    spec = STAGES[name]
    try:
        params = _load_params(params_path)
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
        print(f"twin stage: bad params: {exc}", flush=True)
        return 2

    resolved_method = method or getattr(Pipeline(), name).method
    if resolved_method not in spec.methods:
        print(
            f"twin stage: method {resolved_method!r} not valid for {name}; expected one of {list(spec.methods)}",
            flush=True,
        )
        return 2

    try:
        found = collect_inputs(inputs)
    except ValueError as exc:
        print(f"twin stage: {exc}", flush=True)
        return 2

    missing = [r for r in required_inputs(name) if r not in found]
    if missing:
        print(f"twin stage: missing required input(s) for {name}: {', '.join(missing)}", flush=True)
        return 2

    out = out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    scene_token = scene or _scene_from_inputs(inputs) or name
    log = logging.getLogger("twin.stage")

    tmp_root = Path(tempfile.mkdtemp(prefix=f".stage-{name}-", dir=str(out.parent)))
    try:
        for stage_name, src_dir in found.items():
            link = stage_dir(tmp_root, stage_name)
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src_dir, link)

        ctx = StageContext(
            run_dir=tmp_root,
            scene_token=scene_token,
            seed=params.seed,
            log=log,
            min_observed=params.facilities.min_observed,
        )
        fn = registry.lookup(name, resolved_method)
        if fn is None:
            result = StageResult(status="failed", message=f"no registered method {resolved_method!r}")
        else:
            groups = params.groups_for(name)
            stage_params = getattr(params, groups[0]) if groups else None
            try:
                got = fn(ctx, stage_params)
            except Exception as exc:
                log.exception("stage %s crashed", name)
                result = StageResult(status="failed", message=f"{type(exc).__name__}: {exc}")
            else:
                if isinstance(got, StageResult):
                    result = got
                else:
                    result = StageResult(status="failed", message=f"returned {type(got).__name__}")

        _move_stage_output(tmp_root, out, name)
        _carry_top_level(tmp_root, out, name)
        _write_node_outputs(out, result)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"twin stage: {exc}", flush=True)
        return 2
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if result.status not in ("ok", "skipped"):
        print(f"twin stage: {name} {result.status}: {result.message}", flush=True)
        return 1
    return 0
