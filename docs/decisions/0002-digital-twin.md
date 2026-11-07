# 0002 — Digital twin: content, sources and accuracy

Date: 2026-11-07. Operator decisions, grilling round 3.

## Decisions

1. **Layered twin.** The twin has three layers:
   - **Measurable layer:** a georeferenced point cloud or mesh.
   - **Semantic layer:** lanes, curbs, sidewalks, crosswalks, signs, signals and sight lines.
   - **Viewing layer:** 3D Gaussian Splatting, optional.

   v1 covers static infrastructure only; road users are masked out.
2. **3D vectors and the vertical profile.** The road's vertical profile affects sight lines and audit findings, so it is part of the twin, not an extra. The semantic layer stores 3D nodes and polylines (x, y, z). The output includes engineering-style drawings: plan, profile and cross-sections. An interactive 3D viewer is not needed for v1. 3D vector geometry is in v1 if it stays inside the v1 effort (see the open questions).
3. **Source order:**
   1. Cameras + lidar (nuScenes).
   2. Cameras only, on the same scenes, with lidar as ground truth.
   3. Drone (the operator's own data; patterns reused from drone-survey).
   4. Lidar only (City of Vancouver airborne LiDAR 2022, Open Government Licence – Vancouver: 181 tiles, about 49 points/m², vertical accuracy 0.081 m at 95%).

   Lyft and similar datasets remain under consideration.
4. **Accuracy.** Measure position error against the nuScenes HD map (lane and crosswalk geometry). v1 aims for 20 cm or better on lane and curb edges. The audit-grade bar is set later, from what AuditorAI's checklists need.
5. **The audit feature list** comes from AuditorAI's stage questions. Claude drafts it; the operator prunes it.
6. **Choosing the reconstruction method** (driving-scene 3DGS variants, dynamic-object removal, licences) is a research ticket, backed by a literature search whose sources go into Librarian.
7. **Compute.** Builds run on the box, and ollama is unloaded during twin builds. Data downloads straight to the box once the new SSD is installed.
8. **Relation to drone-survey.** drone-survey (Mission Control) stays a separate product. This repo copies its patterns (Nodes, Manifests, quality gates) rather than depending on its code.
