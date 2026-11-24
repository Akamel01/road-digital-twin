"""Area store: the one module that owns the area folder layout.

An area lives in an areas folder as three siblings: the definition ``<name>.json`` (polygon, drives with scene
tokens, dataset version), the merged build ``<name>-merged/`` (``merged.npz``, ``drives.json`` with each drive's
correction, ``drives/<scene>/<stage folders>``) and the area twin ``<name>-twin/``. Readers open an ``Area`` and
never strip suffixes or build sibling paths themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from twin.area import drive_correction
from twin.contracts import stage_dir

TWIN_SUFFIX = "-twin"
MERGED_SUFFIX = "-merged"
DRIVES_NAME = "drives.json"
MERGED_NAME = "merged.npz"
FEATURE_FILES = ("markings.geojson", "crosswalks.geojson", "curbs.geojson", "ramps.geojson")


def area_merged_dir(store: Path | str, name: str) -> Path:
    """The merged build folder for a writer holding the plain area name.

    `name` is used verbatim from `<store>/areas/<name>.json` and must not be
    stripped or resolved through `open_area`; that invariant is why this helper
    exists.
    """
    return Path(store) / "areas" / f"{name}{MERGED_SUFFIX}"


def area_twin_dir(store: Path | str, name: str) -> Path:
    """The twin build folder for a writer holding the plain area name.

    `name` is used verbatim from `<store>/areas/<name>.json` and must not be
    stripped or resolved through `open_area`; that invariant is why this helper
    exists.
    """
    return Path(store) / "areas" / f"{name}{TWIN_SUFFIX}"


@dataclass(frozen=True)
class AreaDrive:
    scene: str
    token: str | None  # scene token from the area definition
    dir: Path  # <merged>/drives/<scene>
    correction: dict | None  # as in drives.json

    def transform(self, centre: np.ndarray | None = None) -> np.ndarray:
        return drive_correction(self.correction, centre)


@dataclass(frozen=True)
class Area:
    name: str
    root: Path  # the folder holding <name>.json, <name>-merged/ and <name>-twin/
    merged_dir: Path
    twin_dir: Path
    definition_path: Path | None = None  # where open_area found the definition; None when it is missing
    ref_dir: Path | None = None  # the build folder the ref named, if it named one; its drives.json is the one read

    def definition(self) -> dict:
        """The area definition. Falls back to the only polygon .json in the root; FileNotFoundError when there is
        none, ValueError when several compete."""
        if self.definition_path is not None:
            d = _read_json(self.definition_path)
            if isinstance(d, dict):
                return d
        polys = [d for p in sorted(self.root.glob("*.json")) if isinstance(d := _read_json(p), dict) and "polygon" in d]
        if len(polys) == 1:
            return polys[0]
        if not polys:
            raise FileNotFoundError(f"area definition for {self.name!r} not found")
        raise ValueError(f"ambiguous area definition for {self.name!r}: {len(polys)} polygon JSON files in {self.root}")

    def build_dir(self) -> Path:
        """The twin when it has features (or a merged cloud), else the bare-named folder, else merged."""
        for c in (self.twin_dir, self.root / self.name, self.merged_dir):
            if c.is_dir() and (_has_features(c) or (c / MERGED_NAME).is_file()):
                return c
        raise FileNotFoundError(f"no area build for {self.name!r}")

    def cloud_dir(self) -> Path | None:
        """The build the ref named (else the bare-named folder) when it holds ``merged.npz``, else None."""
        d = self.ref_dir if self.ref_dir is not None else self.root / self.name
        return d if (d / MERGED_NAME).is_file() else None

    def drive_records(self) -> list[dict]:
        """The build's drives.json entries as written. The build is the one the ref named, else merged, else the copy
        in the twin; [] when drives.json is unreadable."""
        builds = (self.ref_dir,) if self.ref_dir is not None else (self.merged_dir, self.twin_dir, self.root / self.name)
        for d in builds:
            used = _read_json(d / DRIVES_NAME)
            if isinstance(used, list):
                return [r for r in used if isinstance(r, dict)]
        return []

    def drives(self, definition: dict | None = None) -> list[AreaDrive]:
        """The build's drives.json order, tokens joined from the definition (``definition`` overrides it). A drive the
        definition lacks has token None; [] when drives.json is unreadable."""
        used = self.drive_records()
        try:
            defined = (definition if definition is not None else self.definition()).get("drives") or []
        except (OSError, ValueError, AttributeError):
            defined = []
        token = {
            d["scene"]: d["scene_token"] for d in defined if isinstance(d, dict) and d.get("scene") and d.get("scene_token")
        }
        return [
            AreaDrive(d["scene"], token.get(d["scene"]), self.merged_dir / "drives" / d["scene"], d.get("correction"))
            for d in used
            if d.get("scene")
        ]

    def drive_tokens(self, definition: dict | None = None) -> list[str]:
        return [d.token for d in self.drives(definition) if d.token]


def twin_ref(name: str) -> str:
    """The ref that names an area's twin build, for callers that hold only the area name."""
    return f"{name}{TWIN_SUFFIX}"


def open_area(store: Path | str, ref: str | Path, *, areas_root: Path | None = None) -> Area:
    """ref: an area name, a build folder (<name>-twin or <name>-merged) or a definition .json path."""
    store = Path(store)
    r = Path(ref)
    if len(r.parts) > 1 and not r.is_absolute() and not r.is_dir() and (store / r).exists():
        r = store / r  # a path relative to the store, like areas/a1
    default_root = Path(areas_root) if areas_root is not None else store / "areas"
    if r.suffix == ".json" or r.is_dir() or len(r.parts) > 1:  # a path, even to a build not made yet
        name, root = _strip(r.stem if r.suffix == ".json" else r.name), r.parent
    else:
        name = _strip(str(ref))
        # the areas folder first, then the store's own areas/ and the store itself (older stores keep builds there)
        roots = (default_root, store / "areas", store)
        root = next((x for x in roots if _holds(x, name, build=True)), next((x for x in roots if _holds(x, name)), default_root))
    defs = (root / f"{name}.json", default_root / f"{name}.json", store / "areas" / f"{name}.json")
    return Area(
        name=name,
        root=root,
        merged_dir=root / f"{name}{MERGED_SUFFIX}",
        twin_dir=root / f"{name}{TWIN_SUFFIX}",
        definition_path=next((p for p in defs if isinstance(_read_json(p), dict)), None),
        # the build the ref named (even if not built yet): <name>-twin, <name>-merged or an existing folder
        ref_dir=None if r.suffix == ".json" else root / r.name if r.name != name else r if r.is_dir() else None,
    )


def _strip(name: str) -> str:
    return name.removesuffix(TWIN_SUFFIX).removesuffix(MERGED_SUFFIX)


def _holds(root: Path, name: str, *, build: bool = False) -> bool:
    files = (name, f"{name}{TWIN_SUFFIX}", f"{name}{MERGED_SUFFIX}") + (() if build else (f"{name}.json",))
    return any((root / f).exists() for f in files)


def _has_features(c: Path) -> bool:
    return stage_dir(c, "features").is_dir() or any((c / f).is_file() for f in FEATURE_FILES)


def _read_json(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None
