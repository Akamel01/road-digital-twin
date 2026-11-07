# Consolidated EGM review: planning decisions (2026-11-07)

**Target:** `decisions-bundle.md`, which joins the README, decision records 0001–0003 and the open questions.

**Mode:** consolidated, all rubrics. Stages 5–8 ran. Stage 9 (implementation readiness) was skipped because the bundle has no implementation plan; it runs on the v1 spec.

**Stage reports:** [zoom_out_report.md](zoom_out_report.md), [comprehension_report.md](comprehension_report.md), [critic_report.md](critic_report.md), [intermediate_zoom_out_report.md](intermediate_zoom_out_report.md).

## Bottom line

The goal is clear and survives review. The v1 plan does not. It promises more than the 5 days allow, it has no named owner, and its accuracy and vertical-profile claims don't match what nuScenes can check. The fix is **one short v1 spec that supersedes the earlier rounds**. It must answer one question first: *what must v1 prove, and to whom?*

## Action items

### 🔴 Blockers

1. **Decide v1's purpose and owner: the public UI (demo for recruiters) or audit readiness (files for AuditorAI).** Every other scope choice follows from this.
2. **Write `docs/design/twin-v1-spec.md` as the single current statement of v1.** Sections: Problem, Goals and Non-Goals, Architecture (data flow and output files with a manifest), Alternatives (with a reason for each rejection), Risks and Limits, acceptance criteria per deliverable. 0001–0003 stay as history.
3. **Cut v1 to fit 5 days.**
   - Measurable layer: lidar sweeps stacked with ego poses (nuscenes-devkit), with road users masked by the 3D boxes.
   - No 3DGS; one scene first.
   - Name a fallback scope in case the date slips.

### 🟡 Major

4. **Name the semantic-layer method and what the accuracy check then shows.**
   - If the HD-map polygons are draped onto the ground, the accuracy check becomes a consistency check.
   - Curbs come from a proxy (the drivable_area or walkway boundary).
   - State the error statistic (for example P95).
5. **Vertical.**
   - The nuScenes map is 2D, and ego_pose z is reportedly 0 (to be verified).
   - For v1: report the profile as descriptive, with no vertical-accuracy claim.
   - Use intersection sight distance (mostly plan geometry) unless a crest curve is confirmed in the chosen scene.
   - Name the method (AASHTO or TAC, eye and object heights).
   - Report "indeterminate" where geometry is out of coverage.
6. **Output contract.**
   - The files plus a manifest (EPSG, units, accuracy, licence) form the implicit contract.
   - Don't freeze a versioned AuditorAI schema until AuditorAI reads it.
   - The audit feature list gets a slot in the schedule, or is stated as a non-goal for v1.
7. **Licensing (3 lines).** Derived outputs carry nuScenes' CC BY-NC-SA licence, not Apache-2.0, and are never committed. Whether they may be published on papyrus-ai.net, which may count as commercial, is still to be decided.
8. **UI**, only if it stays in v1:
   - plan and profile views, raster or decimated tiles under the 25 MiB Cloudflare file cap;
   - no 3D streaming format.
9. **No skeleton for the whole project.** Build the twin stage with one input and one output; extensibility comes from the file contract.
10. **Trim 0003 (risk engine) to a direction plus open questions.** Targets and formulas become open questions:
    - p99 latency;
    - inference method;
    - the O(n²) cost of pairwise scoring;
    - the independence of the pairs;
    - the 1e-3 threshold;
    - the shared BADAS/EVT event record;
    - the batch fit plus streaming filter.
11. **Mark superseded decisions:**
    - 0002 #2 against the open questions;
    - #9 → #17;
    - #11 → #17;
    - #14 → #18;
    - the README source order.
12. **Calibrate claims:**
    - future tense for things not yet built;
    - "Apache-2.0, gated" for BADAS;
    - cite or soften the claims about screening and complaint-driven spending;
    - "v1 data from AV rigs" instead of "most data from AVs".

### 🟢 Nit

13. Move process notes and other products' internals out of the records (the Librarian token design, ollama, the workflow routine, branding). Then add a glossary of fewer than 10 terms.
14. Link job-hunt #43, benchmark-spike.md, AV_Safety and the PhD papers. Fix the relative links in the bundle.
15. Clarify that the rule against "AI" in headlines doesn't cover product names (AuditorAI, papyrus-ai.net).
16. Use one template for each decision record. Use consistent date lines.
17. Record what "the agreed recommendations" were, or link the planning sessions.
18. State whether the 8 h/week budget covers the twin.

## Traceability

| Action | Source findings |
|---|---|
| 1 | Zoom-out 1; Catalyst 1; Design 8; Stage 8 #1, #2 |
| 2 | Structural 1–5; Design 1, 2, 10; Comprehension 2; Stage 8 #9 |
| 3 | Zoom-out 2, 3; Design 3; Stage 8 #1 |
| 4 | Zoom-out 9; Comprehension 3; Style 7; Design 4; Stage 8 #4 |
| 5 | Catalyst 2; Design 4, 5; Stage 8 #3 |
| 6 | Zoom-out 1; Catalyst 1; Comprehension 6; Design 8; Stage 8 #2 |
| 7 | Zoom-out 9; Catalyst 7; Comprehension 14; Design 6; Stage 8 #7 |
| 8 | Design 7; Stage 8 #6 |
| 9 | Zoom-out 4; Catalyst 5 |
| 10 | Zoom-out 5; Catalyst 3, 4; Design 9; Stage 8 #5 |
| 11 | Zoom-out 6; Comprehension 1, 2; Structural 6, 7; Style 6, 8; Design 10 |
| 12 | Style 1–5 |
| 13 | Zoom-out 7; Comprehension 4, 5, 9, 12; Style 9; Stage 8 #8 |
| 14 | Comprehension 13; Structural 8; Design 13 |
| 15 | Catalyst 7; Comprehension 15; Design 13 |
| 16 | Structural 9–12 |
| 17 | Design 1; Style nits |
| 18 | Zoom-out 2; Comprehension 8 |
