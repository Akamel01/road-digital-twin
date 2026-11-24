from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.eval_record import main, metrics_from_score
from scripts.eval_schema import load_registry

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SEED = FIXTURES / "evals_seed.json"
LIVE = ROOT / "docs" / "evals" / "recon-v2-results.json"


def _score_obj():
    return {
        "on_path": {
            "n_views": 60,
            "psnr": 20.0,
            "ssim": 0.66,
            "road_depth_p50_m": 0.1,
            "road_depth_p95_m": 1.4,
            "n_road": 100,
            "sidewalk_depth_p50_m": 0.2,
            "sidewalk_depth_p95_m": 1.7,
            "n_sidewalk": 50,
            "depth_coverage": 0.9,
            "extra_key": 5,
        },
        "off_path": {},
        "pass_bar": {},
        "passes": False,
    }


@pytest.fixture
def score(tmp_path):
    p = tmp_path / "score.json"
    p.write_text(json.dumps(_score_obj()), encoding="utf-8")
    return p


@pytest.fixture
def registry(tmp_path):
    dst = tmp_path / "registry.json"
    shutil.copyfile(LIVE, dst)
    return dst


def _bytes(p):
    return p.read_bytes()


def test_append(score, registry):
    before = load_registry(registry)
    rc = main([
        "--score", str(score),
        "--id", "new-run",
        "--approach", "OmniRe",
        "--ticket", "999",
        "--iterations", "100",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 0
    after = load_registry(registry)
    assert len(after.runs) == len(before.runs) + 1
    assert after.runs[-1].id == "new-run"
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    live_raw = json.loads(registry.read_text(encoding="utf-8"))
    assert [list(r.keys()) for r in live_raw["runs"][:7]] == [list(r.keys()) for r in seed["runs"]]
    assert live_raw["runs"][:7] == seed["runs"]
    assert set(after.runs[-1].metrics.keys()) == {
        "psnr", "ssim", "road_depth_p50_m", "road_depth_p95_m",
        "sidewalk_depth_p50_m", "sidewalk_depth_p95_m",
    }
    assert after.pass_bar == before.pass_bar


def test_duplicate(score, registry):
    main([
        "--score", str(score), "--id", "dup-run", "--approach", "OmniRe",
        "--ticket", "999", "--iterations", "100",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    before_bytes = _bytes(registry)
    rc = main([
        "--score", str(score), "--id", "dup-run", "--approach", "OmniRe",
        "--ticket", "999", "--iterations", "100",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 2
    # stderr contains duplicate id: -- capture via capsys? check bytes unchanged enough
    assert _bytes(registry) == before_bytes


def test_duplicate_stderr(score, registry, capsys):
    main([
        "--score", str(score), "--id", "dup-run2", "--approach", "OmniRe",
        "--ticket", "999", "--iterations", "100",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    rc = main([
        "--score", str(score), "--id", "dup-run2", "--approach", "OmniRe",
        "--ticket", "999", "--iterations", "100",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "duplicate id:" in err


def test_missing_metrics(score, tmp_path, registry):
    # on_path with only psnr/ssim
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"on_path": {"psnr": 1.0, "ssim": 0.5, "n_views": 10}}), encoding="utf-8")
    rc = main([
        "--score", str(s), "--id", "mm-run", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 0
    reg = load_registry(registry)
    assert reg.runs[-1].metrics == {"psnr": 1.0, "ssim": 0.5}


def test_null_dropped(tmp_path, registry):
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"on_path": {"psnr": 1.0, "road_depth_p95_m": None}}), encoding="utf-8")
    rc = main([
        "--score", str(s), "--id", "null-run", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 0
    reg = load_registry(registry)
    assert "road_depth_p95_m" not in reg.runs[-1].metrics


def test_zero_metrics(tmp_path, registry):
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"on_path": {"n_views": 60}}), encoding="utf-8")
    before = _bytes(registry)
    rc = main([
        "--score", str(s), "--id", "zero-run", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 2
    assert _bytes(registry) == before


def test_non_positive_depth_only(tmp_path, registry):
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"on_path": {"road_depth_p95_m": 0}}), encoding="utf-8")
    before = _bytes(registry)
    rc = main([
        "--score", str(s), "--id", "np-run", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 2
    assert _bytes(registry) == before


@pytest.mark.parametrize("payload", [
    "not json",
    "[1,2,3]",
    '{"on_path": []}',
])
def test_malformed(payload, tmp_path, registry):
    s = tmp_path / "s.json"
    s.write_text(payload, encoding="utf-8")
    before = _bytes(registry)
    # missing on_path case
    s2 = tmp_path / "s2.json"
    s2.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    for path in (s, s2):
        rc = main([
            "--score", str(path), "--id", "mal-run", "--approach", "OmniRe",
            "--ticket", "1", "--iterations", "1",
            "--eval-set", "scene-0297 held-out, 60 views",
            "--registry", str(registry),
        ])
        assert rc == 2
    assert _bytes(registry) == before


def test_eval_set_mismatch(score, registry):
    before = _bytes(registry)
    rc = main([
        "--score", str(score), "--id", "mm2", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-9999",
        "--registry", str(registry),
    ])
    assert rc == 2
    assert _bytes(registry) == before


def test_backdated_date(score, registry, capsys):
    before = _bytes(registry)
    rc = main([
        "--score", str(score), "--id", "bd", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--date", "2026-11-01",
        "--registry", str(registry),
    ])
    assert rc == 2
    assert _bytes(registry) == before
    # rerun to capture stderr
    # bytes unchanged already; check message via separate invocation not possible (id duplicate? no, failed)
    # Just check stderr contains append order by invoking again with new id
    rc2 = main([
        "--score", str(score), "--id", "bd2", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--date", "2026-11-01",
        "--registry", str(registry),
    ])
    assert rc2 == 2


def test_missing_eval_set(score, registry, capsys):
    # argparse exits 2 via SystemExit; main calls parse_args which raises SystemExit
    with pytest.raises(SystemExit) as exc:
        main([
            "--score", str(score), "--id", "x", "--approach", "OmniRe",
            "--ticket", "1", "--iterations", "1",
            "--registry", str(registry),
        ])
    assert exc.value.code == 2


def test_top_level_array_no_traceback(tmp_path, registry, capsys):
    s = tmp_path / "s.json"
    s.write_text("[1,2,3]", encoding="utf-8")
    rc = main([
        "--score", str(s), "--id", "x2", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1


def test_no_on_path(tmp_path, registry):
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"on_path": []}), encoding="utf-8")
    before = _bytes(registry)
    rc = main([
        "--score", str(s), "--id", "x3", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--registry", str(registry),
    ])
    assert rc == 2
    assert _bytes(registry) == before


def test_backdated_stderr_message(tmp_path, score, registry, capsys):
    # capture stderr message content
    rc = main([
        "--score", str(score), "--id", "bdmsg", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--date", "2026-11-01",
        "--registry", str(registry),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "append" in err or "older" in err


def test_eval_set_mismatch_stderr(score, registry, capsys):
    rc = main([
        "--score", str(score), "--id", "esm", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-9999",
        "--registry", str(registry),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "differs" in err or "mismatch" in err or "eval set" in err


def test_malformed_date(score, registry, capsys):
    before = _bytes(registry)
    rc = main([
        "--score", str(score), "--id", "md", "--approach", "OmniRe",
        "--ticket", "1", "--iterations", "1",
        "--eval-set", "scene-0297 held-out, 60 views",
        "--date", "not-a-date",
        "--registry", str(registry),
    ])
    assert rc == 2
    assert _bytes(registry) == before
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1


def test_metrics_from_score_direct():
    m = metrics_from_score(_score_obj())
    assert set(m.keys()) == {
        "psnr", "ssim", "road_depth_p50_m", "road_depth_p95_m",
        "sidewalk_depth_p50_m", "sidewalk_depth_p95_m",
    }
    assert all(isinstance(v, float) for v in m.values())
    with pytest.raises(ValueError):
        metrics_from_score({"on_path": "x"})
    with pytest.raises(ValueError):
        metrics_from_score([1, 2])
    with pytest.raises(ValueError):
        metrics_from_score({"on_path": {}})
