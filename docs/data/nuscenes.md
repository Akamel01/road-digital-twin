# nuScenes on the box

This page lists what the full nuScenes release holds, how it is laid out on the box, and which parts the twin uses. Counts were measured on the box in `/data/nuscenes`.

Licence: CC BY-NC-SA 4.0, non-commercial. Registration at nuscenes.org is required to get the download links. The links are signed and private, so they are never committed.

## Archives

The script `scripts/get_nuscenes_full.sh` fetches each archive from a URL list. The list holds these 18 archives. The map expansion zip is a separate line when it is listed.

| Archive | Contents | Extracts to |
|---|---|---|
| `v1.0-trainval_meta.tgz` | Tables for the trainval split: scene, log, sample, sample_data, ego_pose, sample_annotation, instance, calibrated_sensor, category, attribute, visibility, map, sensor | `v1.0-trainval/` |
| `v1.0-test_meta.tgz` | Tables for the test split. No annotations. | `v1.0-test/` |
| `v1.0-trainval01_blobs.tgz` to `v1.0-trainval10_blobs.tgz` | Camera images, lidar sweeps, radar sweeps for the trainval split | `samples/`, `sweeps/` |
| `v1.0-test_blobs.tgz` | Camera images, lidar sweeps, radar sweeps for the test split | `samples/`, `sweeps/` |
| `can_bus.zip` | CAN bus and IMU data, one set of files per scene | `can_bus/` |
| `nuScenes-map-expansion-v1.3.zip` | Semantic map layers and the basemap images for four locations | `maps/` |
| `nuScenes-lidarseg-all-v1.0.tar.bz2` | Per-point lidar labels, all splits | `lidarseg/<version>/`, `lidarseg.json` in each split folder |
| `nuScenes-lidarseg-mini-v1.0.tar.bz2` | Per-point lidar labels, mini split | `lidarseg/v1.0-mini/` |
| `nuScenes-panoptic-v1.0-all.tar.gz` | Panoptic labels, all splits | `panoptic/<version>/`, `panoptic.json` in each split folder |
| `nuScenes-panoptic-v1.0-mini.tar.gz` | Panoptic labels, mini split. A subset of the all archive. | `panoptic/v1.0-mini/` |

The mini split (`v1.0-mini.tgz`, with its 10 scenes) is installed by `scripts/get_nuscenes_mini.sh`, not by the full script.

Archives are extracted one at a time. Each archive is deleted after extraction, and a marker in `done/` records that it finished.

## Directory layout

After extraction, `/data/nuscenes` holds:

```
/data/nuscenes/
  v1.0-trainval/   tables for the trainval split (incl. lidarseg.json, panoptic.json)
  v1.0-test/       tables for the test split (incl. lidarseg.json, panoptic.json)
  v1.0-mini/       tables for the mini split (incl. lidarseg.json, panoptic.json)
  samples/         keyframe sensor files (camera images, LIDAR_TOP, radar)
  sweeps/         non-keyframe sensor files
  can_bus/         per-scene CAN bus files
  maps/            semantic-prior PNGs, basemap/, expansion/, prediction/
  lidarseg/        <version>/ per-point label files
  panoptic/        <version>/ panoptic label files
```

`can_bus/` holds 8 files for each of the 979 scenes: `meta`, `ms_imu`, `pose`, `route`, `steeranglefeedback`, `vehicle_monitor`, `zoesensors` and `zoe_veh_info`. The file name starts with the scene name, for example `scene-0001_pose.json`.

`maps/` holds four semantic-prior PNGs, one per location. It also holds `basemap/` (4 PNG files), `expansion/` (4 JSON files, one per location) and `prediction/` (`prediction_scenes.json`).

`category.json` has 32 rows once lidarseg and panoptic are merged. The 23 detection categories come from the original release. The lidarseg merge adds `noise`, `flat.driveable_surface`, `flat.other`, `flat.sidewalk`, `flat.terrain`, `static.manmade`, `static.other`, `static.vegetation` and `vehicle.ego`.

## Table row counts

Measured on the box, `v1.0-trainval`:

| Table | Rows |
|---|---|
| scene | 850 |
| log | 68 |
| sample | 34,149 |
| sample_data | 2,631,083 |
| ego_pose | 2,631,083 |
| sample_annotation | 1,166,187 |
| instance | 64,386 |
| calibrated_sensor | 10,200 |
| category | 23 (32 after lidarseg) |
| attribute | 8 |
| map | 4 |

Logs by location: boston-seaport 30, singapore-onenorth 23, singapore-queenstown 10, singapore-hollandvillage 5.

`v1.0-test` has 150 scenes and 6,008 samples. It has no annotations.

## Sensors

The rig has 12 sensor channels:

- Cameras: CAM_FRONT, CAM_FRONT_LEFT, CAM_FRONT_RIGHT, CAM_BACK, CAM_BACK_LEFT, CAM_BACK_RIGHT.
- Lidar: LIDAR_TOP.
- Radar: RADAR_FRONT, RADAR_FRONT_LEFT, RADAR_FRONT_RIGHT, RADAR_BACK_LEFT, RADAR_BACK_RIGHT.

Each channel has a row in `sensor.json`. Each sensor's pose on the vehicle is in `calibrated_sensor.json`.

## Ego data

The ego vehicle's pose at each sensor timestamp is in `ego_pose.json`, one row per `sample_data` row.

CAN bus data gives wheel speed, steering, IMU and vehicle state at a finer rate. The per-scene files in `can_bus/` hold it, including `pose` and `ms_imu`.

## Road-user data

Annotated objects are in `sample_annotation.json`. Each row is one 3D box on one keyframe. The box belongs to an `instance`, which is one physical object tracked across the scene, and to a `category`.

The 23 detection categories are: animal; seven human.pedestrian classes; four movable_object classes; static_object.bicycle_rack; ten vehicle classes (including vehicle.car, vehicle.truck, vehicle.bus.rigid, vehicle.bus.bendy, vehicle.bicycle and vehicle.motorcycle).

The 8 attributes are: vehicle.moving, vehicle.stopped, vehicle.parked, cycle.with_rider, cycle.without_rider, pedestrian.sitting_lying_down, pedestrian.standing and pedestrian.moving.

`visibility.json` has 4 bins, giving the fraction of the box visible in the camera images.

Road users are masked out of the twin's point cloud by this data (see the mask stage in the README).

## Road infrastructure

The map expansion v1.3 gives per-location JSON layers in `maps/expansion/`. The layers used for the twin are lanes, crosswalks, stop lines and traffic lights. The basemap PNGs in `maps/basemap/` are the drawing the layers sit on.

The lidarseg and panoptic labels mark the ground classes: `flat.driveable_surface`, `flat.sidewalk`, `flat.terrain`, `flat.other`, plus the static classes `static.manmade`, `static.vegetation` and `static.other`. These labels cover the road surface and its edges per lidar point. The labels are a second source, not the HD map.

## Files

- Download script: `scripts/get_nuscenes_full.sh URL_LIST`
- Mini install: `scripts/get_nuscenes_mini.sh`
- Test: `tests/test_get_nuscenes_scripts.py`
