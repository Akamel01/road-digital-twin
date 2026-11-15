"""The nuScenes dataset this process reads: its version and root, read from the environment in one place."""

import os
from dataclasses import dataclass

# DECISION: dataset version is fixed to v1.0-mini, matching the manifest default (contracts ManifestData).
DEFAULT_VERSION = "v1.0-mini"
# DECISION: nuScenes reads data from NUSCENES_ROOT, default /data/nuscenes (as tests/itest does).
DEFAULT_ROOT = "/data/nuscenes"


@dataclass(frozen=True)
class DatasetConfig:
    version: str
    root: str

    @classmethod
    def from_env(cls) -> "DatasetConfig":
        """NUSCENES_VERSION and NUSCENES_ROOT; an unset or empty variable takes the default."""
        return cls(
            version=os.environ.get("NUSCENES_VERSION") or DEFAULT_VERSION,
            root=os.environ.get("NUSCENES_ROOT") or DEFAULT_ROOT,
        )
