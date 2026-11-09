import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
FULL = SCRIPTS_DIR / "get_nuscenes_full.sh"
MINI = SCRIPTS_DIR / "get_nuscenes_mini.sh"
BANNED = re.compile(r"\b(unzip|bzip2|bunzip2)\b")


def code_lines(path: Path):
    """Non-comment lines of a shell script."""
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        yield line


@pytest.mark.parametrize("script", [FULL, MINI], ids=["full", "mini"])
def test_script_does_not_invoke_unzip_or_bzip2(script):
    hits = [line for line in code_lines(script) if BANNED.search(line)]
    assert hits == [], f"{script.name} calls a banned tool: {hits}"


def test_full_script_refuses_to_run_without_url_list(tmp_path):
    root = tmp_path / "root"
    archives = tmp_path / "archives"
    result = subprocess.run(
        ["bash", str(FULL), str(tmp_path / "missing_urls.txt")],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin",
            "NUSC_ROOT": str(root),
            "NUSC_ARCHIVES": str(archives),
        },
    )
    assert result.returncode != 0
    assert "URL list not found" in result.stderr
    assert not root.exists()
    assert not archives.exists()
