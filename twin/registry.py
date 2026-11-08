"""Stage method registry: (stage, method) -> run(ctx, params) -> StageResult.

Stage names, methods and requires come from twin.contracts.STAGES.
"""

from collections.abc import Callable
from typing import Any

from twin.contracts import STAGES, StageResult

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
    return _REGISTRY.get((stage, method))
