# Stage 5: Initial zoom-out review

Target: `decisions-bundle.md` (lines 1–179). Standard: EGM `zoom-out-standard.md`. Reviewers: egm-zoom-out, egm-inventive-catalyst.

## egm-zoom-out — Verdict: Revise

1. **Major: v1 builds a public UI instead of the audit contract, its first consumer.** The twin-to-AuditorAI contract is never defined, and the audit feature list (#5) has no slot in the schedule. The hosted UI serves showcasing, not auditing, and it pulls against "no interactive 3D viewer in v1". Simpler: v1 delivers files plus a v0 AuditorAI contract; the UI is deferred.
2. **Major: v1 is too big for 2026-11-12 and the budget**, and the reconstruction method is still open. It is also unclear whether the 8 h/week budget covers the twin. Cut v1 to one scene.
3. **Major: v1 needs no 3DGS research.** nuScenes cameras + lidar: stack the lidar sweeps with the ego poses (nuscenes-devkit) and mask road users with the 3D box annotations. 3DGS matters only for the cameras-only comparison (v1.1) and the viewing layer. Take the research off the critical path.
4. **Major: a skeleton for the whole project is speculative structure.** Build the twin only, keep its output contract clean, and add structure when the second source or consumer arrives.
5. **Major: 0003 is too detailed for an unstarted phase.** Performance targets and formulas come before any code. It commits to interfaces too early: the dynamic-scene schema "adapters write now", while the twin is static-only, and signal fields from v0. Reduce it to a direction plus open questions. The "coming soon" replay also adds work.
6. **Major: superseded decisions are not marked.** Examples: source order (README vs #11), cameras-only (#11 vs #17), 3D vectors (#2 vs #17 vs the open questions), UI (#14 vs #18). Keep one current v1 summary.
7. **Nit: other products' details and process notes sit in the architecture records.** Examples: Librarian's token design, branding, the workflow routine, ollama unloading.
8. **Nit: copying drone-survey brings drift.** Name an owner for the copied tokens. 0003 #7 ("Mission Control writes it later") is a coupling the separation decision does not acknowledge.
9. **Nit: check the accuracy reference.** As far as the reviewer knows, the nuScenes map has lanes, dividers, crosswalks, walkways and drivable area, but no curb lines, so curb ground truth needs confirming. Also confirm that CC BY-NC-SA allows public display on a company subdomain.

## egm-inventive-catalyst — 4 Major, 3 Nit

1. **Major: v1 leaves out its first consumer.** Define a twin-contract v0: a manifest plus files (EPSG, 3D polylines, profile and sight distance, accuracy). Both the AuditorAI adapter and the UI read it, so the UI becomes a thin viewer that can slip to v1.1. Risk: freezing the schema before AuditorAI's checklists set the bar.
2. **Major: the accuracy reference can't validate the vertical dimension.** The nuScenes HD map is 2D, has no curb layer, and was itself derived from the same lidar. Hold back lidar sweeps (or use another pass) as the z reference along the profile line. Report plan and vertical errors separately and name the curb proxy (the drivable-area boundary). Vancouver ALS becomes the vertical benchmark in v1.1. Risk: the held-back sweeps aren't fully independent.
3. **Major: the risk engine's real-time target has no consumer and squeezes model fidelity.** Fit the hierarchy in batch; let streaming only filter a small state vector against the precomputed posterior. The p99 target becomes a later requirement owned by whichever consumer runs in real time. Risk: a stale posterior between refits.
4. **Major: the comparison between BADAS and EVT is underdefined.** They have different units: ego video versus every pair. Define a shared event record (ego-involved pair, time window, outcome) and compare only where the two overlap.
5. **Nit: the skeleton versus YAGNI.** Extensibility comes from contracts, not placeholder folders. Build the twin stage plus the one adapter in and the one adapter out that it needs.
6. **Nit: copied drone-survey tokens will drift.** Later, extract a shared versioned package. Before v1, keep the copy and record its provenance.
7. **Nit: inconsistencies.**
   - #2 vs the open questions vs #17.
   - papyrus-ai.net hosting vs the rule against "AI" in headlines.
   - nuScenes CC BY-NC-SA applies to the DXF/PDF and the contract outputs, not only the footer.
   - 1 − Π(1 − p) assumes the pairs are independent; state that.

Credited as working: the read-only UI that reads precomputed files, the adapter boundaries, the separate-product decision, and one CRS per site.
