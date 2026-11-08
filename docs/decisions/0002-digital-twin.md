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

## Round 4 (2026-11-07, operator agreed with all recommendations)

9. **Sight distance is computed in v1**, for crest curves and intersections only.
10. **Drawings are DXF and PDF.**
11. **v1 sources:** nuScenes cameras + lidar, plus the cameras-only comparison. Vancouver lidar-only is v1.1. Drone is v2.
12. **Coordinates:** one projected CRS per site, with the EPSG code stored in every output.
13. **v1 date: 2026-11-12** (operator).
14. **UI:** the twin gets a web UI in the Mission Control design (drone-survey `web/`, design spec `docs/ui-theme/spec.md`, UI-12 "Option A" glass). Scope is still open.
15. **Librarian access:** personal access tokens (hashed, scoped read/write to the user's Library, revocable), plus a CLI with `add`, `add-manifest` and `ask --json`. This is a Librarian ticket.
16. **The old `AV_Safety` repo** is archived with a pointer to this repo.

## Round 5 (2026-11-07, operator agreed with all recommendations): v1 for 2026-11-12

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

## Round 6 (2026-11-07): v1 purpose, after the EGM review

21. **v1 purpose: a demo for recruiters.** AuditorAI integration is not a v1 goal; the output files plus a manifest are the implicit contract for later.
22. **The UI doubles as a developer dashboard and controller.** From it the operator tweaks, tests, calibrates and evaluates, and adjusts the framework and the pipeline. Other users see the developer panel read-only. This replaces "static and read-only" in #18–#19. The details are open; see the open questions.
23. **v1 controls (operator, 2026-11-07):** everything named for the developer panel is in v1: parameters, pipeline and framework structure, run, re-run and compare. Controls take priority: when time runs short, they are cut last.
24. **The v1 spec** in `docs/design/twin-v1-spec.md` is now the current statement of v1.

## Round 7 (2026-11-07, operator agreed with all recommendations): after the EGM review of spec revision 1

25. **Pipeline structure control:** stages run in a fixed order, and each declares `requires`. The operator chooses each stage's method from a registered set, edits every parameter, and switches optional stages on or off. Free reordering is not in v1. This narrows "pipeline and framework structure" in #23.
26. **Access:** the control API sits behind Cloudflare Access, limited to the operator's Google account. Signed-out viewers see the developer panel with its controls disabled. The public views are a pinned showcase run served as static files, so the demo stays up when the box is down.
27. **One Boston scene, EPSG:32619.** This replaces "2–3 scenes" in #17.

## Round 8 (2026-11-07)

28. **The operator confirmed three review choices:**
    - Access covers write routes only.
    - The TAC preset moves to v1.1.
    - ISD Case B sub-cases are set as parameters.

    These checks are finalised in v1.1.
29. **The main product is the digital reconstruction of reality, in 2D and 3D** (operator, 2026-11-07). The point cloud, ground surface and extracted features come first. Profile, ISD and drawings are uses of the reconstruction.
30. **Wayfinder destination:** every T0–T11 ticket is ready for an agent, with no decision left open, and the map closes on day 1. Building happens outside the map.
31. **Cut order** (replaces R5):
    1. the profile sheet;
    2. DXF (the PDF stays);
    3. the colour stage;
    4. ISD.

    Never cut: reconstruction (point cloud, ground, markings, crosswalks, curbs), the controls, and the three honesty items.
32. **"2D" means a true-colour orthoimage**, plus RGB on the 3D points. Both come from an optional `colour` stage after ground, which projects the nuScenes camera images. Its method is settled on the wayfinder map.
33. **Operator review:** about 1 h a day. If T4–T7 can't wait, Claude merges after its own review and leaves a rollback note. The three honesty items always wait for the operator.
34. **The UI follows the approved mockup** (`prototypes/plan-view/index.html`, map ticket #9):
    - area → facility → element navigation;
    - a map panel with layers and analysis views;
    - one right column, holding the pipeline summary card and the facility/inspector card.
35. **v1 shows a city area** (operator agreed with the recommendation). Each Boston drive in nuScenes mini is built on its own, and the drives are shown together in EPSG:32619. Merging overlapping drives into one point cloud is v1.1 (#14). This replaces "one scene" in #27.
36. **Colour stage (#8), Q9–Q11 agreed:**
    - Blend with the per-channel median of the 5 views with the smallest footprint within 12 m.
    - Edge-offset QA goes in `colour/qa.json`. With `height_valid=false` the orthoimage is still made, labelled "indeterminate (height)".
    - Colour is stage 6. It requires mask, align, ground and features, and nothing requires it.

    Q8 (occlusion) waits for the multi-sensor research (#13).
37. **Multi-sensor work needs a dedicated state-of-the-art search** before its method is fixed (operator, 2026-11-07; #13).
38. **Colour-stage occlusion (Q8): option (a)**, chosen by the operator. A depth buffer per image from all points plus the annotated boxes at the image time. Full colour-stage method: map ticket #8. The multi-sensor research (#13) can reopen it only with a clearly better method.
39. **Control API access** (map ticket #10):
    - The API is at `twin-api.papyrus-ai.net`, behind its own `twin` tunnel.
    - Zero Trust team `papyrus`; sessions last 24 h.
    - The panel has a sign-in button.
    - The operator enables Zero Trust and creates the `cloudflare-zt-token`; Claude configures the rest, showing each change first.
