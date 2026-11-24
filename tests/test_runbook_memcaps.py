from pathlib import Path


def test_runbook_documents_memory_caps_and_headroom():
    text = Path("docs/runbooks/box-job-queue.md").read_text()
    assert "MemAvailable" in text
    assert "MemTotal - MemAvailable" not in text
    for env in (
        "TWIN_MEM_CAP_AREA_MERGE_GB",
        "TWIN_MEM_CAP_STAGE_GB",
        "TWIN_MEM_CAP_STAGE_<NAME>_GB",
        "TWIN_MEM_CAP_EVAL_GB",
        "TWIN_MEM_CAP_PUBLISH_GB",
        "TWIN_MEM_CAP_PRGATE_GB",
    ):
        assert env in text, env
    assert "MemorySwapMax=0" in text
    assert "oom-cap" in text
    assert "twin worker --stream" in text
    assert "systemd-run --user --scope --quiet -p MemoryMax=8G -p MemorySwapMax=0 -- uv run twin area build" in text
    assert "shell=" in text
    assert "child-cgroups=" in text
    assert "pkill -f \"twin worker\"" in text
    assert "pgrep -f \"twin worker\"" in text
    assert "Not capped" in text
    for bad in ("TWIN_MEM_CAP_AREA_BUILD_GB", "TWIN_MEM_CAP_RUN_GB", "TWIN_MEM_CAP_RERUN_GB"):
        assert bad not in text, bad
    # headroom sentence keeps MemAvailable with the cap + 10 GB rule
    assert "must be at least the cap + 10 GB" in text
