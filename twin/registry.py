"""Stage method registry: (stage, method) -> run(ctx, params) -> StageResult.

Stage names, methods and requires come from twin.contracts.STAGES.
"""

import importlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from twin.contracts import STAGES, Params, StageResult

StageFn = Callable[[Any, Any], StageResult]

_REGISTRY: dict[tuple[str, str], StageFn] = {}


def register(stage: str, method: str) -> Callable[[StageFn], StageFn]:
    """Decorator: register a stage method. Refuses names the contracts don't list."""
    if stage not in STAGES or method not in STAGES[stage].methods:
        raise ValueError(f"contracts list no method {method!r} for stage {stage!r}")

    def decorator(fn: StageFn) -> StageFn:
        if (stage, method) in _REGISTRY:
            raise ValueError(f"{stage}/{method} is already registered")
        _REGISTRY[(stage, method)] = fn
        return fn

    return decorator


def lookup(stage: str, method: str) -> StageFn | None:
    """Find a stage method. Stage code lives in twin/stages/<stage>.py and registers on import."""
    if (stage, method) not in _REGISTRY:
        try:
            importlib.import_module(f"twin.stages.{stage}")
        except ModuleNotFoundError as exc:
            if exc.name != f"twin.stages.{stage}":
                raise
    return _REGISTRY.get((stage, method))


def run_stage(ctx: Any, stage: str, method: str, params: Params) -> StageResult:
    """Run one stage method with the stage's parameter group. Never raises: an unknown method, a crash
    or a return value that is not a StageResult is a failed StageResult."""
    fn = lookup(stage, method)
    if fn is None:
        return StageResult(status="failed", message=f"no registered method {method!r}")
    groups = params.groups_for(stage)
    stage_params = getattr(params, groups[0]) if groups else None
    try:
        result = fn(ctx, stage_params)
    except Exception as exc:  # a stage crash is a failed stage, not a runner crash
        ctx.log.exception("stage %s crashed", stage)
        return StageResult(status="failed", message=f"{type(exc).__name__}: {exc}")
    if not isinstance(result, StageResult):
        return StageResult(status="failed", message=f"returned {type(result).__name__}")
    return result


@contextmanager
def substitute(methods: Mapping[tuple[str, str], StageFn]) -> Iterator[None]:
    """Inside the block, these (stage, method) pairs resolve to the given functions; every other pair
    resolves as before. Restores the registry on exit, also on error."""
    for stage, method in methods:
        lookup(stage, method)  # import the stage module first, so its own registration is not refused later
    saved = dict(_REGISTRY)
    _REGISTRY.update(methods)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)
