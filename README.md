# road-digital-twin

**Status: planning.** No code yet. Decisions are recorded in [`docs/decisions/`](docs/decisions/).

Turn camera, lidar and drone data into a measurable 3D digital twin of a road's infrastructure, so that a road safety audit can cover every facility in a network instead of a screened sample. A collision-risk engine is planned on top of the twin.

## Where this sits

This repo covers the first two stages of a road-safety pipeline:

1. **Digital twin** (this repo, first focus). Reconstruct the static road environment in 3D: lanes, curbs, sidewalks, crosswalks, signs, signals, the vertical profile and sight lines. The twin is georeferenced and measurable.
2. **Collision risk** (this repo, later). Dynamic features (road-user positions, signal state, traffic-law compliance) feed risk measures that run in real time:
   - **Event-based:** each event is scored with the open-source BADAS model.
   - **Accumulated:** risk over time from traffic conflicts, with a dynamic Bayesian hierarchical extreme value theory model.
3. **Safety audit.** [AuditorAI](https://github.com/Akamel01/AuditorAI) audits the twin through a versioned contract.

[Librarian](https://github.com/Akamel01/librarian) supplies the evidence base: papers, standards and manuals used to calibrate each stage.

## Why

- **Coverage, not a sample.** A full audit on every facility removes the screening steps that exist only to ration audit time.
- **Equity and value for money.** Spending can follow measured risk, not complaints.
- **Static plus dynamic.** Infrastructure geometry combined with how road users actually behave on it.
- **Defensible decisions.** Every finding traces back to measurements and cited standards.

## Inputs (planned order)

1. Cameras + lidar (nuScenes; Lyft and similar datasets are under consideration).
2. Cameras only, on the same scenes, with lidar as ground truth to measure the accuracy cost.
3. Drone imagery.
4. Lidar only (for example, City of Vancouver airborne LiDAR 2022).

Datasets are never committed. The repo ships download scripts only and follows each dataset's licence.

## Data on the box

Run on the box (`ssh akamel-linux`), not on the Mac:

1. `scripts/get_nuscenes_mini.sh` (installs to `/data/nuscenes` by default; re-running is a no-op once installed).
2. When asked, paste the two signed download links from nuscenes.org: v1.0-mini and map expansion v1.3. The script never logs in and never stores the links.
3. `make itest`. The integration test loads nuScenes mini and checks for 10 scenes. It skips with a message when the data is absent, so it is safe on the Mac.

## Dependencies and licences

Runtime dependencies are pinned in `pyproject.toml` and locked in `uv.lock`. Licences come from each package's PyPI metadata, or its LICENSE file where the metadata is unclear.

| Package | Pinned version | Licence |
|---|---|---|
| numpy | 2.4.6 | BSD-3-Clause (with bundled components under other permissive licences) |
| pyyaml | 6.0.3 | MIT |
| pydantic | 2.14.3 | MIT |
| filelock | 4.2.9 | MIT |
| open3d | 0.20.0 | MIT |
| kiss-icp | 1.3.0 | MIT |
| cloth-simulation-filter | 1.1.7 | Apache-2.0 |
| laspy (with lazrs) | 2.7.0 | BSD-2-Clause |
| pyproj | 3.7.2 | MIT |
| shapely | 2.2.0 | BSD-3-Clause |
| ezdxf | 1.4.5 | MIT |
| matplotlib | 3.11.2 | PSF-based licence (matplotlib licence agreement) |
| nuscenes-devkit | 1.1.9 | Apache-2.0 (code, per `LICENSE.txt`). PyPI metadata field reads `cc-by-nc-sa-4.0`, which is the nuScenes dataset licence. The devkit does not ship data. |
| fastapi | 0.162.2 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| PyJWT | 2.15.1 | MIT |

Dev tools (not shipped): pytest, ruff.

No nuScenes data is stored in this repo or used in CI. Datasets follow their own licences.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
