"""Run layout and dataset config: one helper for stage folders, one env reader for the nuScenes paths."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from twin.contracts import STAGE_NAMES, STAGES, stage_dir
from twin.dataset import DEFAULT_ROOT, DEFAULT_VERSION, DatasetConfig
from twin.runner import dataset_version


def test_stage_dir_is_number_then_name():
    run = Path("/run")
    assert stage_dir(run, "load") == Path("/run/1_load")
    assert stage_dir(run, "align") == Path("/run/3_align")
    assert stage_dir(run, "profile") == Path("/run/7_profile")
    assert stage_dir(run, "outputs") == Path("/run/10_outputs")


def test_stage_dir_matches_registered_numbers_for_every_stage():
    for name in STAGE_NAMES:
        assert stage_dir(Path("/run"), name).name == f"{STAGES[name].number}_{name}"


def test_from_env_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("NUSCENES_VERSION", raising=False)
    monkeypatch.delenv("NUSCENES_ROOT", raising=False)
    cfg = DatasetConfig.from_env()
    assert cfg == DatasetConfig(version=DEFAULT_VERSION, root=DEFAULT_ROOT)
    assert (cfg.version, cfg.root) == ("v1.0-mini", "/data/nuscenes")


def test_from_env_reads_both_variables(monkeypatch):
    monkeypatch.setenv("NUSCENES_VERSION", "v1.0-trainval")
    monkeypatch.setenv("NUSCENES_ROOT", "/mnt/nuscenes")
    assert DatasetConfig.from_env() == DatasetConfig(version="v1.0-trainval", root="/mnt/nuscenes")


def test_from_env_empty_variable_takes_default(monkeypatch):
    monkeypatch.setenv("NUSCENES_VERSION", "")
    monkeypatch.setenv("NUSCENES_ROOT", "")
    assert DatasetConfig.from_env() == DatasetConfig(version=DEFAULT_VERSION, root=DEFAULT_ROOT)


def test_config_is_frozen():
    with pytest.raises(FrozenInstanceError):
        DatasetConfig(version="v", root="r").version = "other"


def test_runner_dataset_version_follows_env(monkeypatch):
    monkeypatch.setenv("NUSCENES_VERSION", "v1.0-trainval")
    assert dataset_version() == "v1.0-trainval"
    monkeypatch.delenv("NUSCENES_VERSION")
    assert dataset_version() == DEFAULT_VERSION
