import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "get_nuscenes_mini.sh"

MINI_JSON = [
    "scene",
    "sample",
    "sample_data",
    "ego_pose",
    "calibrated_sensor",
    "log",
    "map",
]


def make_tree(root: Path) -> None:
    """Build a synthetic nuScenes mini layout with one file per required path."""
    for name in MINI_JSON:
        p = root / "v1.0-mini" / f"{name}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[]")
    for d in ["samples/LIDAR_TOP", "sweeps/LIDAR_TOP"]:
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / "fake.pcd.bin").write_bytes(b"\0")
    exp = root / "maps" / "expansion"
    exp.mkdir(parents=True, exist_ok=True)
    (exp / "boston-seaport.json").write_text("{}")


def run(args, **kwargs):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        **kwargs,
    )


def test_verify_only_passes_on_complete_tree(tmp_path):
    make_tree(tmp_path)
    assert run(["--verify-only", str(tmp_path)]).returncode == 0


@pytest.mark.parametrize(
    "missing",
    [
        "v1.0-mini/map.json",
        "samples/LIDAR_TOP",
        "sweeps/LIDAR_TOP",
        "maps/expansion/boston-seaport.json",
    ],
)
def test_verify_only_fails_when_a_required_path_is_missing(tmp_path, missing):
    make_tree(tmp_path)
    target = tmp_path / missing
    if target.is_dir():
        for f in target.iterdir():
            f.unlink()
        target.rmdir()
    else:
        target.unlink()
    assert run(["--verify-only", str(tmp_path)]).returncode == 1


def test_install_is_idempotent_and_never_prompts(tmp_path):
    make_tree(tmp_path)
    # stdin is DEVNULL, so any prompt would fail; "already installed" must come first.
    result = run([str(tmp_path)])
    assert result.returncode == 0
    assert "already installed" in result.stdout
