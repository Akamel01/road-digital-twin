import copy
import json

from twin.cli import main
from twin.gates import GO, NO_GO, NOT_MEASURED, evaluate, load_gates, render_markdown

GOOD = {
    "run_id": "20261109-000000-aaaaaa",
    "stages": [{"seconds": 120.0}, {"seconds": 60.0}],
    "metrics": {
        "ground": {"z_disagreement_p95_m": 0.05},
        "align": {"cross_drive_ground_p95_m": 0.03},
        "repeatability": {"markings_p95_m": 0.05, "curbs_p95_m": 0.1},
        "accuracy": {
            "elements": {
                "markings": {"p95_m": 0.2, "p50_m": 0.1, "coverage": 0.8},
                "crosswalks": {"p95_m": 0.4, "p50_m": 0.1, "coverage": 0.8},
                "curbs": {"p95_m": 0.4, "p50_m": 0.1, "coverage": 0.8},
            }
        },
    },
}


def test_pass_with_rerun():
    rep = evaluate(GOOD, rerun=copy.deepcopy(GOOD))
    assert rep["verdict"] == GO
    assert {g["status"] for g in rep["gates"].values()} == {GO}


def test_fail():
    bad = copy.deepcopy(GOOD)
    bad["metrics"]["ground"]["z_disagreement_p95_m"] = 0.58
    rep = evaluate(bad, rerun=bad)
    assert rep["verdict"] == NO_GO
    assert rep["gates"]["G3"]["status"] == NO_GO


def test_not_measured_blocks_go():
    thin = copy.deepcopy(GOOD)
    del thin["metrics"]["align"], thin["metrics"]["repeatability"]
    rep = evaluate(thin, rerun=thin)
    assert rep["gates"]["G2"]["status"] == NOT_MEASURED
    assert rep["gates"]["G4"]["status"] == NOT_MEASURED
    assert rep["verdict"] == NOT_MEASURED
    assert "not measured" in render_markdown(rep)


def test_no_rerun_g1_not_measured():
    assert evaluate(GOOD)["gates"]["G1"]["status"] == NOT_MEASURED


def test_nondeterministic_rerun():
    other = copy.deepcopy(GOOD)
    other["metrics"]["ground"]["z_disagreement_p95_m"] = 0.06
    rep = evaluate(GOOD, rerun=other)
    assert rep["gates"]["G1"]["status"] == NO_GO
    assert rep["gates"]["G1"]["differing_metrics"] == ["ground.z_disagreement_p95_m"]


def test_regression_against_baseline():
    base = copy.deepcopy(GOOD)
    run = copy.deepcopy(GOOD)
    run["metrics"]["accuracy"]["elements"]["curbs"]["p95_m"] = (
        0.45  # +0.05, still < 0.5
    )
    rep = evaluate(run, baseline=base, rerun=run)
    assert rep["verdict"] == NO_GO
    assert [r["metric"] for r in rep["regressions"]] == [
        "accuracy.elements.curbs.p95_m"
    ]
    run["metrics"]["accuracy"]["elements"]["curbs"]["p95_m"] = 0.41  # within noise
    assert evaluate(run, baseline=base, rerun=run)["verdict"] == GO


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
    assert main(["eval", "a", "--store", str(tmp_path)]) == 1  # G1 not measured
