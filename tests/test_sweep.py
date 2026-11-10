import json

import pytest
import yaml

from twin import jobqueue, registry
from twin.cli import main
from twin.contracts import STAGE_NAMES, STAGES, Params, StageResult
from twin.gates import evaluate, load_gates, margin_score
from twin.sweep import build_variants, leaderboard, queue_sweep

BASE = Params().model_dump(mode="json")


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    for name in STAGE_NAMES:

        def run(ctx, params, name=name):
            (ctx.stage_dir(name) / "out.txt").write_text(name)
            metrics = {}
            if (
                name == "ground"
            ):  # the fake pipeline: a smaller ransac distance is better
                metrics = {"z_disagreement_p95_m": params.ransac_dist_m}
            return StageResult(status="ok", metrics=metrics)

        registry.register(name, STAGES[name].methods[0])(run)


def test_random_is_seeded_and_in_range():
    space = {
        "n": 6,
        "seed": 3,
        "params": {"ground.ransac_dist_m": {"min": 0.02, "max": 0.2}},
    }
    a = build_variants(space, BASE)
    assert a == build_variants(space, BASE)
    assert all(0.01 <= v["params"]["ground"]["ransac_dist_m"] <= 0.3 for v in a)
    assert {v["from_stage"] for v in a} == {"ground"}


def test_grid_and_earliest_stage():
    space = {
        "mode": "grid",
        "params": {
            "ground.ransac_dist_m": {"values": [0.03, 0.08]},
            "features.min_points": {"min": 10, "max": 30, "steps": 3},
        },
    }
    out = build_variants(space, BASE)
    assert len(out) == 6
    assert all(
        v["from_stage"] == "ground" for v in out
    )  # ground is earlier than features
    only = build_variants(
        {"mode": "grid", "params": {"features.min_points": {"values": [10, 30]}}}, BASE
    )
    assert {v["from_stage"] for v in only} == {"features"}
    assert all(isinstance(v["overrides"]["features.min_points"], int) for v in only)


def test_out_of_range_and_unknown_refused():
    with pytest.raises(ValueError):
        build_variants(
            {"params": {"ground.ransac_dist_m": {"min": 0.5, "max": 0.9}}}, BASE
        )
    with pytest.raises(ValueError):
        build_variants({"params": {"ground.nope": {"values": [1]}}}, BASE)


def _gates_report(value):
    manifest = {
        "run_id": "20261109-000000-aaaaaa",
        "metrics": {"ground": {"z_disagreement_p95_m": value}},
    }
    return evaluate(manifest, gates=load_gates())


def test_margin_score_formula():
    # G3 threshold 0.10: value 0.05 -> +0.5; value 0.30 -> -2 clipped to -1; G6 runtime 0 min -> +1
    assert margin_score(_gates_report(0.05)) == 1.5
    assert margin_score(_gates_report(0.30)) == 0.0


def test_sweep_end_to_end(tmp_path, stubs):
    base = jobqueue.add(tmp_path, {"type": "run", "scene": "s1"})
    jobqueue.process_one(tmp_path, lambda: None)
    base_run = jobqueue.list_jobs(tmp_path)[0]["run_id"]
    space = tmp_path / "space.yaml"
    space.write_text(
        yaml.safe_dump(
            {
                "mode": "grid",
                "params": {"ground.ransac_dist_m": {"values": [0.02, 0.2]}},
            }
        )
    )
    assert (
        main(["sweep", base_run, "--space", str(space), "--store", str(tmp_path)]) == 0
    )
    jobs = [j for j in jobqueue.list_jobs(tmp_path) if j["state"] == "pending"]
    assert len(jobs) == 2 and all(
        j["type"] == "rerun" and j["from_stage"] == "ground" for j in jobs
    )
    jobqueue.worker(tmp_path, jobs=2, poll=0, hold=lambda: None)
    sweep_id = next((tmp_path / "sweeps").iterdir()).name
    assert main(["sweep", "--report", sweep_id, "--store", str(tmp_path)]) == 0
    board = json.loads(
        (tmp_path / "sweeps" / sweep_id / "leaderboard.json").read_text()
    )
    assert [r["overrides"]["ground.ransac_dist_m"] for r in board["rows"]] == [
        0.02,
        0.2,
    ]
    assert base  # the base job id is not a variant


def test_ranking_verdict_first_and_proposal(tmp_path):
    def fake_run(run_id, verdict, score_metric):
        d = tmp_path / run_id
        d.mkdir()
        report = {
            "verdict": verdict,
            "gates": {
                "G3": {
                    "checks": [
                        {
                            "metric": "m",
                            "op": "<=",
                            "threshold": 1.0,
                            "value": score_metric,
                            "status": "go",
                        }
                    ]
                }
            },
        }
        (d / "gates.json").write_text(json.dumps(report))
        (d / "manifest.json").write_text(json.dumps({"params": BASE}))

    # run a: no-go with a great score; run b: go with a poor score. The verdict wins.
    fake_run("20261109-000000-aaaaaa", "no-go", 0.0)
    fake_run("20261109-000000-bbbbbb", "go", 0.9)
    jobs = []
    for i, run in enumerate(("aaaaaa", "bbbbbb")):
        jid = jobqueue.add(
            tmp_path, {"type": "eval", "run_id": f"20261109-000000-{run}"}
        )
        job = jobqueue.take(tmp_path)
        jobqueue.finish(tmp_path, {**job, "run_id": f"20261109-000000-{run}"})
        jobs.append({"job_id": jid, "overrides": {"x": i}, "from_stage": "ground"})
    folder = tmp_path / "sweeps" / "s1"
    folder.mkdir(parents=True)
    (folder / "sweep.json").write_text(
        json.dumps({"id": "s1", "target": "t", "variants": jobs})
    )
    board = leaderboard(tmp_path, "s1")
    assert [r["verdict"] for r in board["rows"]] == ["go", "no-go"]
    assert yaml.safe_load((folder / "proposed_baseline.yaml").read_text())[
        "run_id"
    ].endswith("bbbbbb")


def test_no_proposal_without_a_pass(tmp_path):
    folder = tmp_path / "sweeps" / "s2"
    folder.mkdir(parents=True)
    (folder / "sweep.json").write_text(
        json.dumps({"id": "s2", "target": "t", "variants": []})
    )
    leaderboard(tmp_path, "s2")
    assert not (folder / "proposed_baseline.yaml").exists()


def test_scene_target_queues_full_runs(tmp_path):
    queue_sweep(
        tmp_path,
        "scene-0757",
        {"n": 2, "params": {"ground.ransac_dist_m": {"min": 0.02, "max": 0.2}}},
    )
    assert {j["type"] for j in jobqueue.list_jobs(tmp_path)} == {"run"}
