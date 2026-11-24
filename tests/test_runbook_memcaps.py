from pathlib import Path

from twin import memcap


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
    # startup tokens (exact literal forms the code prints)
    for token in (
        "shell=systemd-run",
        "shell=UNCAPPED",
        "child-cgroups=<root>",
        "child-cgroups=none",
    ):
        assert token in text, token
    assert "pgrep -f \"twin worker\"" in text
    assert "Not capped" in text
    for bad in ("TWIN_MEM_CAP_AREA_BUILD_GB", "TWIN_MEM_CAP_RUN_GB", "TWIN_MEM_CAP_RERUN_GB"):
        assert bad not in text, bad
    # contiguous MemAvailable headroom sentence
    assert "`MemAvailable` must be at least the cap + 10 GB" in text
    # P2b retry instruction
    assert 'clearing `p2b["gates"]`' in text
    # default cap rows against twin.memcap.CAPS_GB
    assert f"{memcap.CAPS_GB['area-merge']:.0f} GB" in text
    assert f"{memcap.CAPS_GB['stage']:.0f} GB" in text
    # held-pass scoping
    assert "the held commit is not pulled, started, queued or published" in text
    # invalid override fallthrough
    assert "falls through to the\nnext override, then the default" in text or "falls through to the next override, then the default" in text
    # streaming child enter caveat
    assert "child-cgroups=none` means not enforced" in text or "child-cgroups=none` means not enforced" in text
    # manual area build not code-gated
    assert "manual check (`free -g`), not an enforced gate" in text
