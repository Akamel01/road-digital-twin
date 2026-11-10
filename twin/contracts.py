"""Contracts for stages, parameters, pipelines, runs and the area index.

Source of truth: docs/design/twin-v1-spec.md, section 4.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

StageName = Literal[
    "load",
    "mask",
    "align",
    "ground",
    "features",
    "colour",
    "profile",
    "isd",
    "accuracy",
    "outputs",
]
STAGE_NAMES: tuple[str, ...] = (
    "load",
    "mask",
    "align",
    "ground",
    "features",
    "colour",
    "profile",
    "isd",
    "accuracy",
    "outputs",
)


class StageSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    methods: tuple[str, ...]
    requires: tuple[str, ...]
    outputs: tuple[str, ...]
    optional: bool


STAGES: dict[str, StageSpec] = {
    "load": StageSpec(
        number=1,
        methods=("nuscenes",),
        requires=(),
        outputs=(
            "points.npz",
            "poses.json",
            "boxes.json",
            "reference.geojson",
            "facilities.geojson",
            "cameras.json",
        ),
        optional=False,
    ),
    "mask": StageSpec(
        number=2,
        methods=("boxes",),
        requires=("load",),
        outputs=("points.npz", "parked.npz"),
        optional=False,
    ),
    "align": StageSpec(
        number=3,
        methods=("kiss-icp", "dataset-poses"),
        requires=("mask",),
        outputs=("poses.json", "qa.json"),
        optional=False,
    ),
    "ground": StageSpec(
        number=4,
        methods=("ransac-tiles", "csf"),
        requires=("align",),
        outputs=("ground.laz", "nonground.laz", "surface.npz", "qa.json"),
        optional=False,
    ),
    "features": StageSpec(
        number=5,
        methods=("intensity",),
        requires=("ground",),
        outputs=("markings.geojson", "crosswalks.geojson", "curbs.geojson"),
        optional=False,
    ),
    "colour": StageSpec(
        number=6,
        methods=("zbuffer-topk",),
        requires=("mask", "align", "ground", "features"),
        outputs=("ortho.png", "ortho.pgw", "rgb.npz", "qa.json"),
        optional=True,
    ),
    "profile": StageSpec(
        number=7,
        methods=("centreline",),
        requires=("ground",),
        outputs=("profile.csv", "centrelines.geojson"),
        optional=True,
    ),
    "isd": StageSpec(
        number=8,
        methods=("aashto-b",),
        requires=("ground", "mask"),
        outputs=("isd.json",),
        optional=True,
    ),
    "accuracy": StageSpec(
        number=9,
        methods=("one-way",),
        requires=("features", "load"),
        outputs=("accuracy.json",),
        optional=True,
    ),
    "outputs": StageSpec(
        number=10,
        methods=("dxf-pdf",),
        requires=("features",),
        outputs=(
            "twin.laz",
            "twin.geojson",
            "plan.dxf",
            "plan.pdf",
            "profile.dxf",
            "profile.pdf",
        ),
        optional=False,
    ),
}


# ---------------------------------------------------------------- parameters


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectParams(_Strict):
    min_density_pts_m2: float = Field(50.0, ge=1, le=1000)
    min_contrast: float = Field(1.5, ge=1.0, le=10)


class MaskParams(_Strict):
    box_margin_m: float = Field(0.3, ge=0, le=1)
    workers: int | None = Field(
        None, ge=1, le=64
    )  # None: min(cores - 4, 16); output is the same for any value


class AlignParams(_Strict):
    window_s: float = Field(20.0, ge=2, le=20)
    voxel_m: float = Field(0.5, ge=0.1, le=2)


class GroundParams(_Strict):
    voxel_m: float = Field(0.05, ge=0.02, le=0.5)
    tile_m: float = Field(5.0, ge=1, le=20)
    ransac_dist_m: float = Field(0.05, ge=0.01, le=0.3)
    csf_cloth_m: float = Field(0.5, ge=0.1, le=2)
    qa_cell_m: float = Field(0.5, ge=0.1, le=2)
    qa_max_p95_m: float = Field(0.10, ge=0.01, le=1)


class CurbsParams(_Strict):
    enabled: bool = True
    step_min_m: float = Field(0.08, ge=0.02, le=0.3)
    step_max_m: float = Field(0.25, ge=0.1, le=0.5)


class FeaturesParams(_Strict):
    intensity_pct: float = Field(95.0, ge=50, le=99.9)
    cluster_eps_m: float = Field(0.3, ge=0.05, le=2)
    min_points: int = Field(20, ge=3, le=1000)
    # A marking stays "observed" only if at least this share of its labelled lidarseg points are
    # flat.driveable_surface, and it has at least lidarseg_min_points labelled points.
    lidarseg_flat_share: float = Field(0.8, ge=0, le=1)
    lidarseg_min_points: int = Field(10, ge=1, le=1000)
    curbs: CurbsParams = Field(default_factory=CurbsParams)


class ColourParams(_Strict):
    gsd_m: float = Field(0.05, ge=0.02, le=0.5)
    zbuf_scale: float = Field(0.25, ge=0.1, le=1)
    zbuf_tol_m: float = Field(0.2, ge=0.05, le=1)
    min_depth_m: float = Field(1.0, ge=0.5, le=5)
    top_k: int = Field(5, ge=1, le=12)
    max_range_m: float = Field(12.0, ge=3, le=50)
    # auto: the GPU when cupy is installed and enough GPU memory is free, otherwise the CPU (ADR 0005).
    device: Literal["auto", "cpu"] = "auto"


class ProfileParams(_Strict):
    sample_m: float = Field(1.0, ge=0.1, le=10)


class IsdParams(_Strict):
    case: Literal["B1", "B2", "B3"] = "B1"
    time_gap_s: float = Field(7.5, ge=4, le=12)
    design_speed_kmh: float = Field(50.0, ge=20, le=100)
    eye_height_m: float = Field(1.08, ge=0.5, le=3)
    object_height_m: float = Field(1.08, ge=0.2, le=3)
    eye_setback_m: float = Field(4.4, ge=2, le=10)
    band_m: float = Field(0.3, ge=0.05, le=1)
    coverage_window_m: float = Field(2.0, ge=0.5, le=10)
    coverage_min_pts: int = Field(20, ge=1, le=1000)


class AccuracyParams(_Strict):
    buffer_m: float = Field(1.0, ge=0.1, le=5)
    # Samples within this distance of the reference count as matched (precision); beyond it, false positives.
    match_radius_m: float = Field(1.0, ge=0.1, le=5)


class FacilitiesParams(_Strict):
    min_observed: float = Field(0.5, ge=0, le=1)
    workers: int | None = Field(
        None, ge=1, le=64
    )  # load's per-sweep pool; None: min(cores - 4, 16)


class MergeParams(_Strict):
    # DECISION (coordinator, 2026-11-10): heights are fitted per drive in align, but across drives in the area
    # merge only on request. On the seaport area the fit gave implausible tilts (issue 177).
    heights: bool = False


class Params(_Strict):
    select: SelectParams = Field(default_factory=SelectParams)
    mask: MaskParams = Field(default_factory=MaskParams)
    align: AlignParams = Field(default_factory=AlignParams)
    ground: GroundParams = Field(default_factory=GroundParams)
    features: FeaturesParams = Field(default_factory=FeaturesParams)
    colour: ColourParams = Field(default_factory=ColourParams)
    profile: ProfileParams = Field(default_factory=ProfileParams)
    isd: IsdParams = Field(default_factory=IsdParams)
    accuracy: AccuracyParams = Field(default_factory=AccuracyParams)
    merge: MergeParams = Field(default_factory=MergeParams)
    facilities: FacilitiesParams = Field(default_factory=FacilitiesParams)
    seed: int = 0


# ------------------------------------------------------------------ pipeline


class PipelineStage(_Strict):
    method: str
    enabled: bool = True


class Pipeline(_Strict):
    load: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="nuscenes")
    )
    mask: PipelineStage = Field(default_factory=lambda: PipelineStage(method="boxes"))
    align: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="kiss-icp")
    )
    ground: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="ransac-tiles")
    )
    features: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="intensity")
    )
    colour: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="zbuffer-topk")
    )
    profile: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="centreline")
    )
    isd: PipelineStage = Field(default_factory=lambda: PipelineStage(method="aashto-b"))
    accuracy: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="one-way")
    )
    outputs: PipelineStage = Field(
        default_factory=lambda: PipelineStage(method="dxf-pdf")
    )

    @model_validator(mode="after")
    def _check_stages(self) -> "Pipeline":
        for name in STAGE_NAMES:
            spec = STAGES[name]
            stage: PipelineStage = getattr(self, name)
            if stage.method not in spec.methods:
                raise ValueError(
                    f"stage {name}: method {stage.method!r} not in {list(spec.methods)}"
                )
            if not spec.optional and not stage.enabled:
                raise ValueError(f"stage {name} is required and cannot be disabled")
            if not stage.enabled:
                continue
            for req in spec.requires:
                if not getattr(self, req).enabled:
                    raise ValueError(
                        f"stage {name} is enabled but requires {req}, which is disabled"
                    )
        return self


# --------------------------------------------------------- run status, results


StageStatus = Literal["pending", "running", "ok", "skipped", "failed", "cancelled"]


class StageResult(_Strict):
    status: StageStatus
    files: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


# ----------------------------------------------------------------- manifest


class ManifestParent(_Strict):
    run_id: str = Field(pattern=r"^\d{8}-\d{6}-[0-9a-f]{6}$")
    from_stage: StageName


class ManifestCode(_Strict):
    git_sha: str
    dirty: bool
    lockfile_sha256: str


class OsmNames(_Strict):
    overpass_query_date: date
    licence: str = "ODbL"


class ManifestData(_Strict):
    nuscenes_version: str = "v1.0-mini"
    map_version: str = "1.3"
    scene_token: str
    osm_names: OsmNames | None = None  # null when the load stage got no Overpass query


class ManifestCrs(_Strict):
    epsg: Literal[32619] = 32619
    units: Literal["m"] = "m"
    licence: str = "CC BY-NC-SA 4.0"


class ManifestStage(_Strict):
    name: StageName
    method: str
    status: StageStatus
    started: datetime
    seconds: float = Field(ge=0)
    files: list[str] = Field(default_factory=list)


class Manifest(_Strict):
    run_id: str = Field(pattern=r"^\d{8}-\d{6}-[0-9a-f]{6}$")
    parent: ManifestParent | None = None
    code: ManifestCode
    data: ManifestData
    crs: ManifestCrs = Field(default_factory=ManifestCrs)
    pipeline: Pipeline
    params: Params
    stages: list[ManifestStage] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------- area index


class Drive(_Strict):
    run_id: str = Field(pattern=r"^\d{8}-\d{6}-[0-9a-f]{6}$")
    scene_token: str
    name: str
    # minx, miny, maxx, maxy in EPSG:32619 metres: the extent of the drive's plan rasters
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)


class AreaFacility(_Strict):
    id: str
    type: Literal["intersection", "segment", "access_point"]
    name: str
    best_run: str | None
    runs: list[str] = Field(default_factory=list)
    observed_core: float = Field(ge=0, le=1)
    not_scanned_enough: bool


class AreaIndex(_Strict):
    drives: list[Drive] = Field(default_factory=list)
    facilities: list[AreaFacility] = Field(default_factory=list)


# ------------------------------------------------------------------ re-run

# Which stage each parameter key belongs to. None means the key is setup,
# outside the pipeline, so changing it never forces a re-run.
PARAM_STAGE: dict[str, str | None] = {
    "select": None,
    "facilities": "load",
    "seed": "load",
    "mask": "mask",
    "align": "align",
    "ground": "ground",
    "features": "features",
    "colour": "colour",
    "profile": "profile",
    "isd": "isd",
    "accuracy": "accuracy",
}


def check_rerun(
    parent_pipeline: Pipeline,
    parent_params: Params,
    new_pipeline: Pipeline,
    new_params: Params,
    from_stage: str,
) -> None:
    """Refuse a re-run that changes an earlier stage.

    Raises ValueError("re-run from stage <j>") for the earliest stage j
    before from_stage whose method, enabled flag or parameters changed.
    """
    if from_stage not in STAGES:
        raise ValueError(f"unknown stage {from_stage!r}")
    changed: set[str] = set()
    for name in STAGE_NAMES:
        if getattr(parent_pipeline, name) != getattr(new_pipeline, name):
            changed.add(name)
    for key in Params.model_fields:
        if getattr(parent_params, key) != getattr(new_params, key):
            stage = PARAM_STAGE[key]
            if stage is not None:
                changed.add(stage)
    limit = STAGES[from_stage].number
    for name in STAGE_NAMES:
        if STAGES[name].number < limit and name in changed:
            raise ValueError(
                f"re-run from stage {name}: {name} changed, "
                f"but this re-run starts at stage {from_stage}"
            )
