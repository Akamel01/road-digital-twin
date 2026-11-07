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

## Licence

Apache-2.0. See [LICENSE](LICENSE).
