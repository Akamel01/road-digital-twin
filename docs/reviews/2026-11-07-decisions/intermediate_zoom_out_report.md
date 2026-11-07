# Stage 8: Intermediate zoom-out

Reviewer: egm-zoom-out, over the bundle plus the Stage 5–7 reports. **Verdict: Revise.**

1. **Blocker: together, the mitigations make v1 bigger with 5 days left.** They are: a spec, a glossary, contract v0, vertical validation, a web format, licensing, acceptance criteria, a risk-engine redesign, and an event record. The root question was never asked: **what must v1 prove, and to whom?** (A public demo, or a check that the twin is good enough for audits?) Write one short v1 spec that states this purpose and supersedes the earlier rounds. Each addition must serve that purpose.
2. **Major: the reports disagree about v1's consumer** (files + contract with the UI deferred, versus a contract read by both, versus AuditorAI as a non-goal). A frozen contract with no reader is speculative. The implicit contract is the files plus a manifest (EPSG, units, accuracy). Pick one owner for v1.
3. **Major: separate vertical validation is circular, or impossible.**
   - If ego_pose z = 0, held-back sweeps share the same pose chain, so they can't check it.
   - Vancouver doesn't overlap the Boston or Singapore scenes.
   - There may be no crest curve in the data.

   For v1: intersection sight distance (mostly plan geometry), the profile reported as descriptive only, and no vertical-accuracy claim.
4. **Major: the method for the semantic layer is still open.** Draping the HD-map polygons on the ground turns the accuracy check into the map compared with itself, so call that a "consistency check". Lidar intensity or learned segmentation would be research again. The spec must name the method and say what the accuracy check actually shows. Curb results are a proxy (the drivable-area boundary).
5. **Major: the risk-engine mitigations contradict "trim 0003".** Each becomes one line under open questions. Apply the feature-spec standard to the v1 twin only.
6. **Major: the point-cloud web format exists only for the UI.** If the UI stays, use a plan-view raster or decimated tiles under the 25 MiB cap. If it is deferred, the question goes away.
7. **Nit:** licensing in three lines: derived outputs are CC BY-NC-SA, never committed, and publish yes or no. The NC question is a reason to defer the public UI.
8. **Nit:** remove the process and other-product notes first; the glossary then shrinks to fewer than 10 terms.
9. **Nit:** the v1 spec *replaces* the bundle as the current statement; 0001–0003 stay as history.

Credited as working: the lidar-stacking baseline, 3DGS off the critical path, building the twin only, marking superseded items, and AuditorAI as a non-goal if the UI owns v1.
