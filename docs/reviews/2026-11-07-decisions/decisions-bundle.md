# Review bundle: planning decisions as of 2026-11-07

This file joins the repo README and the decision records 0001–0003, plus the open questions, into one document for review. No design spec exists yet. The sources are in docs/decisions/.

---

<!-- source: README.md -->
## road-digital-twin

**Status: planning.** No code yet. Decisions are recorded in [`docs/decisions/`](docs/decisions/).

Turn camera, lidar and drone data into a measurable 3D digital twin of a road's infrastructure, so that a road safety audit can cover every facility in a network instead of a screened sample. A collision-risk engine is planned on top of the twin.

### Where this sits

This repo covers the first two stages of a road-safety pipeline:

1. **Digital twin** (this repo, first focus). Reconstruct the static road environment in 3D: lanes, curbs, sidewalks, crosswalks, signs, signals, the vertical profile and sight lines. The twin is georeferenced and measurable.
2. **Collision risk** (this repo, later). Dynamic features (road-user positions, signal state, traffic-law compliance) feed risk measures that run in real time:
   - **Event-based:** each event is scored with the open-source BADAS model.
   - **Accumulated:** risk over time from traffic conflicts, with a dynamic Bayesian hierarchical extreme value theory model.
3. **Safety audit.** [AuditorAI](https://github.com/Akamel01/AuditorAI) audits the twin through a versioned contract.

[Librarian](https://github.com/Akamel01/librarian) supplies the evidence base: papers, standards and manuals used to calibrate each stage.

### Why

- **Coverage, not a sample.** A full audit on every facility removes the screening steps that exist only to ration audit time.
- **Equity and value for money.** Spending can follow measured risk, not complaints.
- **Static plus dynamic.** Infrastructure geometry combined with how road users actually behave on it.
- **Defensible decisions.** Every finding traces back to measurements and cited standards.

### Inputs (planned order)

1. Cameras + lidar (nuScenes; Lyft and similar datasets are under consideration).
2. Cameras only, on the same scenes, with lidar as ground truth to measure the accuracy cost.
3. Drone imagery.
4. Lidar only (for example, City of Vancouver airborne LiDAR 2022).

Datasets are never committed. The repo ships download scripts only and follows each dataset's licence.

### Licence

Apache-2.0. See [LICENSE](LICENSE).

---

<!-- source: docs/decisions/0001-scope-and-order.md -->
## 0001 — Scope, order and the two stages

Date: 2026-11-07. Decided by the operator in planning sessions (2026-11-02 to 2026-11-07).

### Context

The project started as a real-time crash-risk system for autonomous vehicles. It replaces the earlier "AV Safety Evaluation Benchmark" idea (job-hunt #43, `docs/research/benchmark-spike.md`). On 2026-11-06 the operator placed it inside a wider road-safety pipeline: digital twin, then collision risk, then safety audit (AuditorAI), with Librarian as the evidence base.

### Decisions

1. **Name and licence.** The repo is `road-digital-twin`, public from day one, Apache-2.0.
2. **The twin comes first.** The real work begins with the digital twin. The repo holds a skeleton for the whole project, so that later stages plug in without restructuring.
3. **The audit is the first consumer.** The twin's first use is road safety audits of existing infrastructure, through AuditorAI. The AV safety case, readiness criteria and the ODD come after the risk engine.
4. **Scope wording.** Most of the data comes from AVs, but the project is never described as AV-only. The case for it is network-wide, complete safety audits.
5. **Branding.** Definitions and headline statements don't use the word "AI". The products stand on evidence and engineering.
6. **Growth.** The pipeline grows in two directions:
   - horizontally: new road types, jurisdictions and sensor setups;
   - vertically: new stages and products.

   The layout separates inputs (one adapter per source), stages, and outputs (one per consumer).
7. **Librarian is the retrieval engine** for development. Papers, standards and similar work are added to the operator's Librarian library and queried from there. The repo never stores them.

### Consequences

- Grilling continues for the later phases (risk, safety case) while the twin builds and renders run.
- Phase planning follows a set protocol: grill until the phase is settled; the operator triggers a wayfinder session; then triage and to-tickets; then delegation to opencode.

---

<!-- source: docs/decisions/0002-digital-twin.md -->
## 0002 — Digital twin: content, sources and accuracy

Date: 2026-11-07. Operator decisions, grilling round 3.

### Decisions

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

### Round 4 (2026-11-07, operator agreed with all recommendations)

9. **Sight distance is computed in v1**, for crest curves and intersections only.
10. **Drawings are DXF and PDF.**
11. **v1 sources:** nuScenes cameras + lidar, plus the cameras-only comparison. Vancouver lidar-only is v1.1. Drone is v2.
12. **Coordinates:** one projected CRS per site, with the EPSG code stored in every output.
13. **v1 date: 2026-11-12** (operator).
14. **UI:** the twin gets a web UI in the Mission Control design (drone-survey `web/`, design spec `docs/ui-theme/spec.md`, UI-12 "Option A" glass). Scope is still open.
15. **Librarian access:** personal access tokens (hashed, scoped read/write to the user's Library, revocable), plus a CLI with `add`, `add-manifest` and `ask --json`. This is a Librarian ticket.
16. **The old `AV_Safety` repo** is archived with a pointer to this repo.

### Round 5 (2026-11-07, operator agreed with all recommendations): v1 for 2026-11-12

17. **v1 scope:**
    - 2–3 scenes from nuScenes mini (about 4 GB; fits on the box before the SSD arrives).
    - Cameras + lidar twin: a point cloud plus 3D lane edges, curbs and crosswalks.
    - Vertical profile and sight distance at one crest curve or intersection.
    - DXF and PDF drawings.
    - Accuracy measured against the nuScenes HD map.
    - The UI.

    The cameras-only comparison moves to v1.1.
18. **UI scope:** read-only, from files the pipeline computed beforehand:
    - a site list;
    - a plan-view map with layers (point cloud, lane and curb lines, crosswalks);
    - a profile view with the sight-distance result;
    - an accuracy panel;
    - DXF and PDF downloads.

    It uses the Mission Control style (dark photo, glass panels, Manrope) and the Crown living-mark for status.
19. **Hosting:** a static site at `twin.papyrus-ai.net` on Cloudflare. The code lives in this repo, with design tokens copied from drone-survey.
20. **The UI is public**, with nuScenes attribution (CC BY-NC-SA 4.0) in the footer.

---

<!-- source: docs/decisions/0003-risk-engine.md -->
## 0003 — Collision-risk engine (later phase): agreed direction

Date: 2026-11-07. Operator agreed with grilling rounds 1 and 2. The engine is built after the digital twin.

1. **Two measures, side by side.**
   - **Event-based:** BADAS-Open (Hugging Face `nexar-ai/BADAS-Open`, Apache-2.0, gated; input is ego dashcam video).
   - **Accumulated:** dynamic Bayesian hierarchical EVT on traffic conflicts.

   Both are reported, plus an analysis of where they agree and disagree. Fusing them is a later decision.
2. **Who specifies the EVT model.** Claude drafts two cited formulations: a hierarchy of site and road-user-pair class, and dynamic parameters through a state-space model with online updates. The operator chooses one and reviews it line by line.
3. **How it differs from the operator's PhD.** The PhD estimated risk per site and per interval, offline. This engine estimates risk per frame and per road-user pair, uses only past data (causal), updates online, adds severity and an event layer, and its outputs serve as evidence for safety claims.
4. **"Now" means a short horizon.** Indicators are predicted over a short horizon (3 s proposed), and EVT supplies the tail probability.
5. **Severity.** Predicted delta-v is mapped to MAIS3+ through published curves, with separate pedestrian and cyclist impact-speed curves. Severity is triggered when P(crash) ≥ 1e-3; the operator tunes this threshold.
6. **Every road user.** Pairwise risk, plus each user's total risk: 1 − Π(1 − p_pair).
7. **Input contract.** A canonical dynamic-scene schema v0 (road users, kinematics, class, optional signal state and compliance flags). Dataset adapters write it now; Mission Control writes it later.
8. **Signals and compliance** come in v2, through WOMD or the synthetic sim. The field exists from schema v0.
9. **Modes.** Streaming per frame (causal, at least 10 Hz, p99 under 100 ms for EVT scoring) and batch over many logs.
10. **Data.** nuScenes, plus a synthetic 2D sim (ground truth for calibration), plus Nexar collision clips (real crashes; BADAS side only). Later: inD/rounD and WOMD. Lyft and similar datasets stay under consideration.
11. **Demo.** README with a GIF, plus a static replay on papyrus-ai.net inside the pipeline section, marked "coming soon".
12. **Budget.** About 8 operator hours a week.

---

<!-- source: docs/decisions/open-questions.md -->
## Open questions

The operator answers these; nothing here is assumed.

### Digital twin
- None open for v1. The wayfinder map holds the method choices.

### Risk engine (later)
- Prediction horizon: is 3 s right?
- How the twin feeds the risk engine (geometry as covariates? conflict zones?).

### Safety case (later)
- Which claims the first GSN skeleton should carry.
- Check UL 4600, ISO 21448, ISO 34502, ISO 34503 / SAE J3259 and the NHTSA AV framework against primary sources.
