import copy
import json

from twin.cli import main
from twin.gates import (
    G2_RUN,
    G2_STEPS,
    GO,
    NO_GO,
    NOT_MEASURED,
    GateReport,
    evaluate,
    g2_state,
    load_gates,
    margin_score,
    read_g2_history,
    record_g2_result,
    regressions,
    render_markdown,
)

GOOD = {
    "run_id": "20261109-000000-aaaaaa",
    "stages": [{"seconds": 120.0}, {"seconds": 60.0}],
    "metrics": {
        "ground": {"z_disagreement_p95_m": 0.05},
        "align": {"cross_drive_ground_p95_m": 0.03},
        "repeatability": {"markings_p95_m": 0.05, "curbs_p95_m": 0.1},
        "accuracy": {
            "elements": {
                "markings": {
                    "p95_m": 0.2,
                    "matched_p95_m": 0.2,
                    "false_positive_rate": 0.05,
                    "p50_m": 0.1,
                    "coverage": 0.8,
                },
                "crosswalks": {
                    "p95_m": 0.4,
                    "matched_p95_m": 0.4,
                    "false_positive_rate": 0.05,
                    "p50_m": 0.1,
                    "coverage": 0.8,
                },
                "curbs": {
                    "p95_m": 0.4,
                    "matched_p95_m": 0.4,
                    "false_positive_rate": 0.05,
                    "p50_m": 0.1,
                    "coverage": 0.8,
                },
            }
        },
    },
}


def report_obj(manifest=GOOD, **kw):
    return GateReport.from_dict(evaluate(manifest, **kw))


def test_pass_with_rerun():
    rep = evaluate(GOOD, rerun=copy.deepcopy(GOOD))
    gr = GateReport.from_dict(rep)
    assert rep["verdict"] == GO
    assert gr.verdict == GO
    assert {g["status"] for g in rep["gates"].values()} == {GO}


def test_fail():
    bad = copy.deepcopy(GOOD)
    bad["metrics"]["ground"]["z_disagreement_p95_m"] = 0.58
    rep = GateReport.from_dict(evaluate(bad, rerun=bad))
    assert rep.verdict == NO_GO
    assert rep.gates["G3"]["status"] == NO_GO


def test_not_measured_blocks_go():
    thin = copy.deepcopy(GOOD)
    del thin["metrics"]["align"], thin["metrics"]["repeatability"]
    rep = evaluate(thin, rerun=thin)
    gr = GateReport.from_dict(rep)
    assert rep["gates"]["G2"]["status"] == NOT_MEASURED
    assert rep["gates"]["G4"]["status"] == NOT_MEASURED
    assert gr.verdict == NOT_MEASURED
    assert gr.total > gr.passed
    assert "not measured" in render_markdown(rep)


def test_no_rerun_g1_not_measured():
    gr = report_obj()
    assert gr.gates["G1"]["status"] == NOT_MEASURED


def test_nondeterministic_rerun():
    other = copy.deepcopy(GOOD)
    other["metrics"]["ground"]["z_disagreement_p95_m"] = 0.06
    gr = report_obj(GOOD, rerun=other)
    assert gr.gates["G1"]["status"] == NO_GO
    assert gr.gates["G1"]["differing_metrics"] == ["ground.z_disagreement_p95_m"]


def test_regression_against_baseline():
    base = copy.deepcopy(GOOD)
    run = copy.deepcopy(GOOD)
    run["metrics"]["accuracy"]["elements"]["curbs"]["matched_p95_m"] = 0.45
    rep = evaluate(run, baseline=base, rerun=run)
    assert rep["verdict"] == NO_GO
    assert [r["metric"] for r in rep["regressions"]] == [
        "accuracy.elements.curbs.matched_p95_m"
    ]
    run["metrics"]["accuracy"]["elements"]["curbs"]["matched_p95_m"] = 0.41
    rep2 = evaluate(run, baseline=base, rerun=run)
    assert rep2["verdict"] == GO
    gr = GateReport.from_dict(rep2)
    assert gr.regressions_vs(run["metrics"], base["metrics"], gates=load_gates()) == []
    # real regression detected via GateReport API
    run_bad = copy.deepcopy(GOOD)
    run_bad["metrics"]["accuracy"]["elements"]["curbs"]["matched_p95_m"] = 0.45
    gr_bad = GateReport.from_dict(evaluate(run_bad, rerun=run_bad))
    regs = gr_bad.regressions_vs(run_bad["metrics"], base["metrics"], gates=load_gates())
    assert any(r["metric"] == "accuracy.elements.curbs.matched_p95_m" for r in regs)


def test_regressions_lost_metric_higher_is_better_and_tolerance():
    gates = {
        "noise_tolerance_m": 0.02,
        "gates": {
            "G9": {
                "name": "x",
                "checks": [
                    {"metric": "accuracy.coverage", "op": ">=", "value": 0.7},
                    {"metric": "runtime.total_min", "op": "<=", "value": 30},
                ],
            }
        },
    }
    base = {"accuracy": {"coverage": 0.8}, "runtime": {"total_min": 10}}
    run = {"accuracy": {}, "runtime": {"total_min": 10}}
    lost = regressions(run, base, 0.02, gates)
    assert {"metric": "accuracy.coverage", "baseline": 0.8, "value": None} in lost
    worse_cov = {"accuracy": {"coverage": 0.77}, "runtime": {"total_min": 10}}
    assert regressions(worse_cov, base, 0.02, gates) == [
        {"metric": "accuracy.coverage", "baseline": 0.8, "value": 0.77}
    ]
    assert regressions({"accuracy": {"coverage": 0.79}}, base, 0.02, gates) == []


def test_thresholds_come_from_gates_file():
    gates = load_gates()
    gates["gates"]["G3"]["checks"][0]["value"] = 0.01
    assert evaluate(GOOD, rerun=GOOD, gates=gates)["gates"]["G3"]["status"] == NO_GO


def test_cli_exit_codes_and_files(tmp_path, capsys):
    for name, doc in (("a", GOOD),):
        d = tmp_path / name
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps(doc))
    assert main(["eval", str(tmp_path / "a"), "--rerun", str(tmp_path / "a")]) == 0
    assert (tmp_path / "a" / "gates.json").exists()
    assert (tmp_path / "a" / "gates.md").exists()
    gr = GateReport.load(tmp_path / "a")
    assert gr.verdict == GO and gr.passed == gr.total
    assert main(["eval", "a", "--store", str(tmp_path)]) == 1  # G1 not measured


def test_gate_report_checks_fields_margins_and_round_trip(tmp_path):
    gr = report_obj(GOOD, rerun=copy.deepcopy(GOOD))
    assert gr.checks
    c = gr.checks[0]
    assert c.name == c.metric == c["metric"]
    assert {"name", "value", "threshold", "op", "status"} <= set(vars(type(c)))
    assert c.metric in gr.margins()
    assert "runtime.total_min" in gr.margins()
    raw = gr.to_dict()
    assert GateReport.from_dict(raw).to_dict() == raw
    assert GateReport.from_dict(raw).verdict == gr.verdict
    d = tmp_path / "b"
    d.mkdir()
    (d / "gates.json").write_text(json.dumps(raw))
    assert GateReport.load(d).to_dict() == raw


def test_margin_score_parity_and_zero_threshold():
    gr = report_obj(GOOD, rerun=copy.deepcopy(GOOD))
    assert gr.score() == margin_score(gr.to_dict())
    rep = {
        "gates": {
            "G": {
                "checks": [
                    {"metric": "a", "op": "<=", "threshold": 0.1, "value": 0.05, "status": GO},
                    {"metric": "b", "op": ">=", "threshold": 2.0, "value": 1.0, "status": NO_GO},
                    {"metric": "c", "op": "<=", "threshold": 0, "value": 0, "status": GO},
                    {"metric": "d", "op": "<=", "threshold": 0, "value": 1, "status": NO_GO},
                    {"metric": "e", "op": "<=", "threshold": 1, "value": None, "status": NOT_MEASURED},
                ]
            }
        }
    }
    assert margin_score(rep) == round(0.5 - 0.5 + 0.0 - 1.0, 6)


def test_margin_sum_and_improves_on_history_compat():
    def rep(g2_val, verdict=GO):
        return {
            "run_id": f"r-{g2_val}",
            "verdict": verdict,
            "gates": {
                "G2": {
                    "name": "g",
                    "status": verdict,
                    "checks": [{"metric": "align.p95", "op": "<=", "threshold": 0.2, "value": g2_val, "status": verdict}],
                }
            },
        }

    better = GateReport.from_dict(rep(0.1))
    worse = GateReport.from_dict(rep(0.15))
    assert better.margin_sum() > worse.margin_sum()
    assert better.improves_on({"go_count": 1, "margin_sum": worse.margin_sum()})
    assert not worse.improves_on({"go_count": 1, "margin_sum": better.margin_sum()})
    assert better.improves_on(None)
    assert better.improves_on({"go_count": None, "margin_sum": None})
    assert better.improves_on({"garbage": 1})
    tied = GateReport.from_dict(rep(0.1))
    assert not tied.improves_on({"go_count": 1, "margin_sum": tied._improves_margin_sum()})


def test_g2_record_dedupe_due_streak_and_state(tmp_path):
    def rep(run_id, value, threshold=0.2, status=GO):
        return {
            "run_id": run_id,
            "gates": {
                "G2": {
                    "name": "Cross-drive ground agreement after registration",
                    "status": status,
                    "checks": [{"metric": "align.cross_drive_ground_p95_m", "op": "<=", "threshold": threshold, "value": value, "status": status}],
                }
            },
        }

    entry, due = record_g2_result(tmp_path, rep("r1", 0.15))
    assert entry and due is None
    entry2, _ = record_g2_result(tmp_path, rep("r1", 0.15))  # dedupe
    assert entry2 is None and len(read_g2_history(tmp_path)) == 1
    record_g2_result(tmp_path, rep("r2", 0.30, status=NO_GO))
    record_g2_result(tmp_path, rep("r3", 0.12))
    record_g2_result(tmp_path, rep("r4", 0.11))
    assert g2_state(tmp_path) == {"threshold": 0.2, "passing_in_a_row": 2}
    _, due = record_g2_result(tmp_path, rep("r5", 0.10))
    assert due == G2_STEPS[0.2]
    assert g2_state(tmp_path)["passing_in_a_row"] == G2_RUN


def test_g2_robust_selection_and_silent_absent_malformed(tmp_path):
    rep = {
        "run_id": "r9",
        "gates": {
            "G9": {"checks": [{"metric": "other", "value": 1, "threshold": 1, "status": GO}]},
            "G2": {
                "checks": [
                    {"metric": "align.cross_drive_ground_p95_m", "op": "<=", "threshold": 0.1, "value": 0.05, "status": GO}
                ]
            },
        },
    }
    entry, _ = record_g2_result(tmp_path, rep)
    assert entry and entry["threshold"] == 0.1
    assert record_g2_result(tmp_path, {"run_id": "x", "gates": {}}) == (None, None)
    assert record_g2_result(tmp_path, {}) == (None, None)
    assert g2_state(tmp_path) == {"threshold": 0.1, "passing_in_a_row": 1}
    (tmp_path / "autopilot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "autopilot" / "g2_history.json").write_text("not json")
    assert read_g2_history(tmp_path) == []
    assert g2_state(tmp_path) is None or isinstance(g2_state(tmp_path), dict)
