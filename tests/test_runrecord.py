import json

import pytest

from twin.contracts import STAGE_NAMES, Manifest
from twin.gates import evaluate
from twin.runrecord import (
    LEGACY_FILE,
    RUN_FILE,
    eval_document,
    is_core_record,
    read_manifest,
    read_record,
    record_path,
    write_record,
)


def _manifest(run_id: str = "20261101-000000-aaaaaa") -> Manifest:
    return Manifest.model_validate(
        {
            "run_id": run_id,
            "data": {"scene_token": "s", "nuscenes_version": "v1.0-mini"},
            "code": {"git_sha": "0" * 40, "dirty": False, "lockfile_sha256": "1" * 64},
            "pipeline": {},
            "params": {},
            "stages": [
                {"name": n, "status": "ok", "method": "m", "seconds": 1.0, "started": "2026-11-01T00:00:00Z"}
                for n in STAGE_NAMES
            ],
            "metrics": {"ground": {"z_disagreement_p95_m": 0.05}},
        }
    )


def test_writes_run_json(tmp_path):
    write_record(tmp_path, _manifest())
    assert (tmp_path / RUN_FILE).is_file()
    assert not (tmp_path / LEGACY_FILE).exists()
    got = read_manifest(tmp_path)
    assert got.run_id == "20261101-000000-aaaaaa"


def test_falls_back_to_legacy_manifest(tmp_path):
    (tmp_path / LEGACY_FILE).write_text(json.dumps({"run_id": "r", "metrics": {}, "stages": []}))
    assert record_path(tmp_path).name == LEGACY_FILE
    assert read_record(tmp_path)["run_id"] == "r"


def test_run_json_preferred_over_manifest(tmp_path):
    (tmp_path / LEGACY_FILE).write_text(json.dumps({"run_id": "old", "metrics": {}, "stages": []}))
    (tmp_path / RUN_FILE).write_text(json.dumps({"run_id": "new", "metrics": {}, "stages": []}))
    assert record_path(tmp_path).name == RUN_FILE
    assert read_record(tmp_path)["run_id"] == "new"


def test_core_record_eval_metrics():
    doc = {
        "version": 1,
        "pipeline": "area-twin",
        "manifest_hash": "abc",
        "core_version": "0.1.0",
        "status": "succeeded",
        "nodes": [
            {
                "name": "ground",
                "status": "done",
                "duration_s": 12.0,
                "checks": [{"name": "z_disagreement_p95_m", "value": 0.05, "pass": True}],
            },
            {
                "name": "accuracy",
                "status": "done",
                "duration_s": 3.0,
                "checks": [
                    {"name": "elements.markings.p95_m", "value": 0.2, "pass": True},
                    {"name": "elements.markings.coverage", "value": 0.8, "pass": True},
                ],
            },
        ],
    }
    assert is_core_record(doc)
    ev = eval_document(doc, "area-x")
    assert ev["run_id"] == "area-x"
    assert ev["metrics"]["ground"]["z_disagreement_p95_m"] == 0.05
    assert ev["metrics"]["accuracy"]["elements"]["markings"]["p95_m"] == 0.2
    assert ev["metrics"]["runtime"]["total_min"] == 0.25
    assert ev["stages"] == [{"seconds": 12.0}, {"seconds": 3.0}]


def test_eval_core_record_gates_equal_twin_record():
    core = eval_document(
        {
            "version": 1,
            "pipeline": "p",
            "manifest_hash": "h",
            "core_version": "0.1.0",
            "nodes": [
                {"name": "align", "duration_s": 1.0, "checks": [{"name": "cross_drive_ground_p95_m", "value": 0.03, "pass": True}]},
                {"name": "ground", "duration_s": 2.0, "checks": [{"name": "z_disagreement_p95_m", "value": 0.05, "pass": True}]},
                {
                    "name": "accuracy",
                    "duration_s": 3.0,
                    "checks": [
                        {"name": "elements.markings.p95_m", "value": 0.2, "pass": True},
                        {"name": "elements.markings.matched_p95_m", "value": 0.2, "pass": True},
                        {"name": "elements.markings.false_positive_rate", "value": 0.05, "pass": True},
                        {"name": "elements.markings.p50_m", "value": 0.1, "pass": True},
                        {"name": "elements.markings.coverage", "value": 0.8, "pass": True},
                        {"name": "elements.crosswalks.p95_m", "value": 0.4, "pass": True},
                        {"name": "elements.crosswalks.matched_p95_m", "value": 0.4, "pass": True},
                        {"name": "elements.crosswalks.false_positive_rate", "value": 0.05, "pass": True},
                        {"name": "elements.crosswalks.p50_m", "value": 0.1, "pass": True},
                        {"name": "elements.crosswalks.coverage", "value": 0.8, "pass": True},
                        {"name": "elements.curbs.p95_m", "value": 0.4, "pass": True},
                        {"name": "elements.curbs.matched_p95_m", "value": 0.4, "pass": True},
                        {"name": "elements.curbs.false_positive_rate", "value": 0.05, "pass": True},
                        {"name": "elements.curbs.p50_m", "value": 0.1, "pass": True},
                        {"name": "elements.curbs.coverage", "value": 0.8, "pass": True},
                    ],
                },
            ],
        },
        "r",
    )
    twin = {
        "run_id": "r",
        "stages": [{"seconds": 60.0}, {"seconds": 120.0}, {"seconds": 180.0}],
        "metrics": {
            "ground": {"z_disagreement_p95_m": 0.05},
            "align": {"cross_drive_ground_p95_m": 0.03},
            "accuracy": {
                "elements": {
                    "markings": {"p95_m": 0.2, "matched_p95_m": 0.2, "false_positive_rate": 0.05, "p50_m": 0.1, "coverage": 0.8},
                    "crosswalks": {"p95_m": 0.4, "matched_p95_m": 0.4, "false_positive_rate": 0.05, "p50_m": 0.1, "coverage": 0.8},
                    "curbs": {"p95_m": 0.4, "matched_p95_m": 0.4, "false_positive_rate": 0.05, "p50_m": 0.1, "coverage": 0.8},
                }
            },
        },
    }
    rc = evaluate(core)
    rt = evaluate(twin)
    for gid in ("G2", "G3", "G5"):
        assert rc["gates"][gid]["status"] == rt["gates"][gid]["status"], gid


def test_corrupt_or_missing_record_raises(tmp_path):
    with pytest.raises(OSError):
        read_record(tmp_path)
    (tmp_path / RUN_FILE).write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        read_record(tmp_path)
