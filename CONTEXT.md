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

**Feature**:
A road element extracted from the twin's points: a lane marking, a crosswalk or a curb.
_Avoid_: object, asset, annotation

**Reference**:
The external geometry that features are scored against: in v1, a nuScenes HD-map layer.
_Avoid_: ground truth (the HD map is itself a model)

**Orthoimage**:
A true-colour, top-down image of the ground surface, made from the camera images.
_Avoid_: BEV, aerial, satellite view

### Pipeline

**Stage**:
One fixed step of the pipeline, which runs one of its registered methods.
_Avoid_: node, step, task

**Run**:
One execution of the pipeline on one scene, with one set of parameters, kept forever.
_Avoid_: job, experiment, build

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
_Avoid_: frame, scan

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
