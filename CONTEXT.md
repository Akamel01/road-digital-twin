# Road digital twin

This repo turns sensor logs into a measurable digital twin of road infrastructure, in 2D and 3D, with a stated error. Road safety checks such as sight distance are uses of the twin.

## Language

### The twin

**Twin**:
A measurable reconstruction of a road site: point cloud, ground surface, extracted features, and true-colour imagery, all in one CRS.
_Avoid_: model, scene, map (a map is the external HD map)

**Reconstruction**:
The making of the twin from sensor data. This is the main product.
_Avoid_: rendering, visualisation

**Static layer**:
The photorealistic, metric model of everything at a site that does not move (road surface, curbs, buildings, poles), built from camera images and supervised by LiDAR. Features are extracted from it. Photorealism is a property of the static layer, not a separate product.
_Avoid_: rendering, splat (a splat is one way to hold it), visualisation

**Actor layer**:
A separate model of one moving object (a vehicle, cyclist or pedestrian) over its track in a drive. Kept so moving objects never pollute the static layer.
_Avoid_: dynamic object, agent

**Fused area model**:
A static layer built from several drives of the same site, aligned into one model.
_Avoid_: merged splat, multi-traversal model

**Feature**:
A road element extracted from the twin: a lane marking, a crosswalk, a curb or a curb ramp.
_Avoid_: object, asset, annotation

**Reference**:
The external geometry that features are scored against: the audit set first, a nuScenes HD-map layer as a second check.
_Avoid_: ground truth (the HD map is itself a model)

**Audit set**:
Hand-checked features at a few varied intersections, drafted from the twin and approved by the operator. It is frozen and versioned, and used only to score, never to tune or train.
_Avoid_: ground truth, training data, test set

**Inventory grade**:
The standard a facility's features meet when each element type is found, typed and placed within its stated targets against the audit set, scored per element and never summed.
_Avoid_: production quality, good enough

**Area vote**:
Fusing the evidence from every frame of every drive over an area into one grid, so features are extracted once per area. Inside changed regions only the newest drives vote.
_Avoid_: per-drive merge, stacking

**Orthoimage**:
A true-colour, top-down image of the ground surface, made from the camera images.
_Avoid_: BEV, aerial, satellite view

### Pipeline

**Stage**:
One fixed step of the pipeline, which runs one of its registered methods.
_Avoid_: node, step, task

**Node**:
One step of a recon-core Manifest: a command with declared typed inputs/outputs and its own checks. A twin pipeline step is still a Stage.
_Avoid_: node for a twin stage

**Run**:
One execution of the pipeline on one scene, with one set of parameters, kept forever.
_Avoid_: job, experiment, build

**Run Record**:
The file `run.json` a run writes: inputs, versions, stages, and metrics. A pre-change run's `manifest.json` is read as a fallback.
_Avoid_: manifest for a run's output

**Showcase run**:
The single run published as static files for the public views.
_Avoid_: demo run, release

**Scene**:
One nuScenes recording, about 20 s long, at one site.
_Avoid_: log, sequence, site (a site is the place; a scene is one recording of it)

**Keyframe**:
A nuScenes sample at 2 Hz that has annotated boxes.

**Sweep**:
One lidar scan, at about 20 Hz. Only keyframes have boxes.
_Avoid_: frame, scan, and never for a parameter search

**Parameter search**:
Rounds of runs that vary a method's parameters around a base run, looking for a better score.
_Avoid_: sweep (a sweep is one lidar scan)

**Noise**:
The score difference between two rebuilds of the same code and data. A change smaller than the noise is a tie.

**Plateau**:
A search or a training run that has stopped improving: three rounds or epochs with no gain beyond the noise. A plateau stops the search and asks for a new direction instead of more rounds.
_Avoid_: stall, convergence

### Honesty labels

**Height valid**:
The run-level flag saying the twin's heights are consistent between sweeps. It is not a claim of absolute accuracy.

**Indeterminate**:
A result the data cannot support, which is shown instead of a number.
_Avoid_: unknown, N/A, error

**Map-conditioned**:
A label on a feature's accuracy when its reference depends on the HD map's own drawing choices (curbs scored against the drivable-area edge).

**Unobserved**:
Part of the ground or a point that no camera saw cleanly. It is left without colour, never filled.
_Avoid_: missing, no data, hole

**Origin**:
Whether a labelled feature came from the twin or from the operator: `drafted` means machine-drafted from twin outputs, `operator` means human-corrected or approved.
_Avoid_: source, provenance

### People

**Facility**:
A unit of road the twin reports on: an Intersection, a Segment or an Access point. Every check result belongs to one facility.
_Avoid_: site, location, asset

**Intersection**:
A facility made of the HD map's intersection area plus each leg out to its required sight distance.

**Leg**:
One road arm of an intersection, the approach a driver waits on. Sight distance is checked per leg.
_Avoid_: approach (when you mean the whole arm), branch

**Segment**:
A facility for the road between two intersections, taken as one unit.
_Avoid_: link, road piece

**Access point**:
A facility where a driveway or lot entrance meets the road.
_Avoid_: driveway (too narrow), entrance

**Not scanned enough**:
A facility whose core is less than half observed. It is listed so the gap shows, but it has no metrics.

**Operator**:
The project owner and only admin. They set the methodology.
_Avoid_: user, admin, developer

**Viewer**:
Anyone else using the UI. Viewers can see everything but act on nothing.
_Avoid_: guest, public user
