"""The run store: one place that decides which runs exist and which count (complete, failed, a baseline).

A run is a folder named by its run id, holding manifest.json. Manifests are read as plain JSON so a
partial or hand-made one still answers; a folder without a readable manifest is not a run.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from twin.contracts import STAGE_NAMES
from twin.dataset import DatasetConfig

RUN_ID_RE = r"\d{8}-\d{6}-[0-9a-f]{6}"
DONE = ("ok", "skipped")  # a stage that finished; skipped is a stage that is off by default


@dataclass(frozen=True)
class Run:
    id: str
    path: Path
    data: dict  # the raw manifest

    @property
    def scene(self) -> str | None:
        return self.data.get("data", {}).get("scene_token")

    @property
    def dataset_version(self) -> str | None:
        return self.data.get("data", {}).get("nuscenes_version")

    @property
    def stages(self) -> list[dict]:
        return self.data.get("stages", [])

    @property
    def status(self) -> str:
        """The worst stage status (failed, cancelled, running, pending), else ok."""
        statuses = {s.get("status") for s in self.stages}
        for name in ("failed", "cancelled", "running", "pending"):
            if name in statuses:
                return name
        return "ok" if statuses else "pending"


class RunStore:
    def __init__(self, store: Path | str):
        self.store = Path(store)

    def get(self, run_id: str) -> Run:
        """One run by id. Raises OSError or ValueError when its manifest is missing or unreadable."""
        path = self.store / run_id
        return Run(run_id, path, json.loads((path / "manifest.json").read_text()))

    def runs(
        self,
        scene: str | None = None,
        full_chain: bool = False,
        no_parent: bool = False,
        dataset_version: str | None = None,
        with_gates: bool = False,
    ) -> list[Run]:
        """Runs newest first. full_chain: every stage present and finished (ok, or skipped when off by
        default); no_parent: not a rerun; with_gates: gates.json exists."""
        out = []
        for d in sorted(self.store.glob("*"), reverse=True):
            if not re.fullmatch(RUN_ID_RE, d.name):
                continue
            try:
                run = self.get(d.name)
            except (OSError, ValueError):
                continue
            if no_parent and run.data.get("parent") is not None:
                continue
            if dataset_version is not None and run.dataset_version != dataset_version:
                continue
            if scene is not None and run.scene != scene:
                continue
            if full_chain and not (
                run.stages and not self.failed(run) and {s.get("name") for s in run.stages} == set(STAGE_NAMES)
            ):
                continue  # a partial chain (e.g. P4 prefetch, stop_after) is not a full run
            if with_gates and not (d / "gates.json").exists():
                continue
            out.append(run)
        return out

    @staticmethod
    def complete(run: Run) -> bool:
        """Every stage is in (finished or not)."""
        return len(run.stages) >= len(STAGE_NAMES)

    @staticmethod
    def failed(run: Run) -> list[dict]:
        """The stages that did not finish ok or skipped (failed, cancelled, running, pending); empty when none."""
        return [s for s in run.stages if s.get("status") not in DONE]

    def newest_baseline(self, scene: str) -> Run | None:
        """The run to compare with: the newest full run of the scene on this process's dataset version,
        not a rerun, with gates. The newest is current main."""
        found = self.runs(
            scene=scene,
            full_chain=True,
            no_parent=True,
            dataset_version=DatasetConfig.from_env().version,
            with_gates=True,
        )
        return found[0] if found else None
