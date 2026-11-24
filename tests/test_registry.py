import logging
from pathlib import Path

import pytest

from twin import registry
from twin.contracts import Params, StageResult
from twin.runner import StageContext

KEY = ("ground", "ransac-tiles")


@pytest.fixture
def ctx(tmp_path):
    return StageContext.for_params(tmp_path, "scene-1", Params(), logging.getLogger("t"))


def run(ctx, stage, method, params=None):
    return registry.run_stage(ctx, stage, method, params or Params())


def test_unknown_method_is_a_failed_result(ctx):
    res = run(ctx, "ground", "nope")
    assert res.status == "failed" and "nope" in res.message


def test_crash_is_a_failed_result(ctx):
    def boom(ctx, params):
        raise ValueError("bad")

    with registry.substitute({KEY: boom}):
        res = run(ctx, *KEY)
    assert res.status == "failed" and res.message == "ValueError: bad"


def test_wrong_return_type_is_a_failed_result(ctx):
    with registry.substitute({KEY: lambda ctx, params: {"status": "ok"}}):
        res = run(ctx, *KEY)
    assert res.status == "failed" and res.message == "returned dict"


def test_stage_gets_its_parameter_group(ctx):
    got = []

    def fn(ctx, params):
        got.append(params)
        return StageResult(status="ok")

    params = Params()
    with registry.substitute({KEY: fn}):
        assert run(ctx, *KEY, params).status == "ok"
    assert got == [getattr(params, params.groups_for("ground")[0])]


def test_substitute_restores_the_registry_after_an_error(ctx):
    original = registry.lookup(*KEY)
    with pytest.raises(RuntimeError), registry.substitute({KEY: lambda ctx, params: StageResult(status="ok")}):
        assert registry.lookup(*KEY) is not original
        raise RuntimeError("inside")
    assert registry.lookup(*KEY) is original


def test_context_reads_min_observed_from_params(tmp_path):
    params = Params(facilities={"min_observed": 0.8})
    ctx = StageContext.for_params(tmp_path, "s", params, logging.getLogger("t"))
    assert (ctx.min_observed, ctx.seed, ctx.run_dir) == (0.8, params.seed, Path(tmp_path))
