# Stage 6: Comprehension test

Target: `decisions-bundle.md`, lines 1–179. Reviewer: egm-comprehension. The reviewer read the document only, with no standard applied.

## What this proposes

The project will build a georeferenced, measurable 3D "digital twin" of a road's static infrastructure from sensor data. It has three layers: a point cloud or mesh, semantic 3D lines (lanes, curbs, crosswalks, signs, signals), and an optional Gaussian Splatting view. The first consumer is AuditorAI, so that road safety audits can cover every facility in a network instead of a sample.

v1 is due on 2026-11-12 and contains:
- 2–3 nuScenes mini scenes, built from cameras + lidar;
- 3D lane edges, curbs and crosswalks;
- a vertical profile and sight distance at one crest curve or intersection;
- DXF and PDF drawings;
- accuracy measured against the nuScenes HD map (target 20 cm on lane and curb edges);
- a public, read-only static web UI on Cloudflare.

Later releases add cameras-only and Vancouver lidar-only (v1.1), then drone (v2). After that comes a collision-risk engine. It reports two measures side by side: per-event BADAS-Open scores on dashcam video, and accumulated risk from a dynamic Bayesian hierarchical EVT model on traffic conflicts. The engine runs per frame and causally, adds severity mapping and per-pair and per-user risk, and reads a canonical dynamic-scene schema.

## How the existing system works, per this document

There is no code yet; the repo is in planning. It sits among sibling products:
- AuditorAI audits the twin through a "versioned contract".
- Librarian is the operator's literature library, queried through a CLI and tokens that are still to be built.
- drone-survey, also called "Mission Control", is a separate drone product. Its patterns and UI tokens are copied, but not its code.

Work runs on one compute machine, "the box", which also runs ollama. The process: the operator makes decisions in grilling rounds; then come a wayfinder session, ticketing, and delegation to opencode, with Claude drafting the artifacts. The project replaces an earlier AV_Safety repo and benchmark idea, and extends the operator's offline PhD risk work.

## Findings

1. **Major: dangling cross-reference.** Line 91 says 3D vectors are in v1 "if it stays inside the v1 effort (see the open questions)". The open questions say "None open for v1", and decision 17 includes 3D lane edges. It is unclear which statement holds.
2. **Major: superseded decisions are not marked.** Decision 11 is replaced by 17 (cameras-only moves to v1.1). Decision 14 ("still open") is replaced by 18. The README Inputs list has no version labels. The document never states the rule that later rounds override earlier ones.
3. **Major: the accuracy reference doesn't match the target.** The reference covers lanes and crosswalks, but the target names lanes and curbs. What are curbs measured against? Do crosswalks have a target? There is no accuracy method for Vancouver lidar-only, which falls outside nuScenes coverage.
4. **Major: process vocabulary is undefined.** "Operator", "grilling", "wayfinder session/map", "triage and to-tickets", "opencode" and Claude's role are never defined. The method choices are deferred to a map the reader cannot reach.
5. **Major: terms borrowed from drone-survey are undefined and unlinked.** drone-survey itself has no link. "Nodes, Manifests, quality gates", "UI-12 Option A glass", the "Crown living-mark" and `docs/ui-theme/spec.md` are all unexplained. The document never explains how "Mission Control writes [the dynamic-scene schema] later" would happen.
6. **Major: the AuditorAI interface is never described.** "Versioned contract", "stage questions" and "checklists" are not defined or linked. The audit-grade bar and the feature list depend on them.
7. **Major: the safety case has no place in the pipeline.** The AV safety case, readiness criteria, ODD and GSN appear without being placed: is the safety case a fourth stage, part of the risk engine, or a separate product?
8. **Major: the budget's scope is ambiguous.** "About 8 operator hours a week" sits under the risk engine. The reader cannot judge whether the 5-day v1 is plausible without knowing the effort and who does the work.
9. **Major: compute terms are undefined.** "The box", "the new SSD" and "ollama unloaded" are never explained: no GPU or disk figures, and no reason ollama competes with builds.
10. **Nit:** "the synthetic sim" is written as if it already exists.
11. **Nit:** "Indicators" is not specified (TTC? PET?).
12. **Nit:** ODD, GSN, MAIS3+, WOMD, inD/rounD and BADAS are not expanded or linked. BADAS is called "open-source" but is gated.
13. **Nit:** job-hunt #43, benchmark-spike.md, AV_Safety and the PhD are unlinked or uncited.
14. **Nit:** the public UI's licence implications (nuScenes NC/SA) are not addressed beyond attribution.
15. **Nit:** the rule against "AI" in headlines sits awkwardly with the names AuditorAI and papyrus-ai.net; the boundary is not stated.
16. **Nit:** the intro says "the sources are in docs/decisions/", but the README is at the repo root.
17. **Nit:** the skeleton is described only in words; no directory layout is given.

**Verdict:** complete. The whole document could be paraphrased, so there are no blockers. 9 Major, 8 Nit.
