# Stage 7: Critic review (spec, lines 1–151)

## egm-structural: all five required areas present; does not yet meet the standard

1. **Major:** the "fully static site" rejection is a preference, not a trade-off, and decision 22 can't be traced. Give the real reason: a static site can't run, re-run or compare.
2. **Major:** Lyft is "not checked". Give a concrete reason for rejecting it, or move it to the open questions.
3. **Major:** R2 credits a maintainer with no link. Link nuscenes-devkit#721.
4. **Major:** no scalability limits are stated: one scene, serial queue, a shared CPU, a run store that only grows. Add a row.
5. **Major:** EPSG 32619 is hard-coded, but the scene choice could fall in Singapore.
6. **Major/Nit:** the methods and control-plane choices (ICP, AASHTO, FastAPI, Tunnel, token) have no alternatives entries.
7. **Nits:**
   - citation keys aren't links;
   - the link text on line 4 doesn't match its target;
   - the R6 wording is backwards;
   - R8 is a process note;
   - the code block has no language tag;
   - cross-references are written two different ways.

## egm-style

1. **Major:**
   - The R6 wording is backwards.
   - "Decision 22" can't be traced.
   - The 20 cm target has no source.
   - The screenshot self-review has no criteria.
   - R2 is hearsay, and "<20 s" isn't a value; set a default such as 10 s.
   - R8 is a process note.
   - "Honest" is subjective.
2. **Nits:**
   - The problem statement makes absolute claims.
   - "Much of the checking" is vague.
   - "Where the scan can't decide" should be reworded.
   - "Polish" is undefined.
   - "The box" is undefined.
   - "Implicit contract" is jargon.
   - "Simpler to explain" is subjective.
   - "Mostly flat" is a generalisation.
   - "Initial z drift" is undefined when z = 0.
   - The TAC preset values aren't given.
   - "Masked parked vehicles" vs "annotated road users" is inconsistent.
   - The Vancouver figure has no citation.
   - "Optionally confirm with Motional" has no decision attached.
   - The profile sheet has no acceptance criterion.

## egm-design: not ready (core claim undermined in three places)

1. **Major:** curb accuracy is circular (the search window and the reference are both `drivable_area`). Detect curbs without the map prior, or label the curb accuracy "map-conditioned".
2. **Major:** the ISD blocking rule is wrong. Tree canopy and wires count as blockers, and unscanned space counts as clear. Fix: a blocker is a point within a band around the ray, below the ray and above the ground. Cells with no scan coverage (ray-cast from the sensor origins) give "indeterminate".
3. **Major:** ICP overclaims.
   - KISS-ICP is relative, so the claim should read "removes relative z and attitude inconsistency between sweeps".
   - Mask dynamic boxes **before** ICP.
   - Define the drift metric (ground z disagreement where sweeps overlap).
   - On fallback, mark the profile and curbs invalid.
4. **Major:** EPSG is hard-coded, and the absolute georeference error (approximate map origin) is unknown. State it separately from the plan accuracy.
5. **Major:** marking extraction may not work on 32-beam lidar with uncalibrated intensity, and the cited paper was read at title level only. Add a stage-0 go/no-go check on ground density. Define the metric: extracted-to-reference, a matching buffer, and coverage at that buffer. `lane_divider` is a map polyline, not paint.
6. **Major:** the box is a single point of failure for the demo. Publish a pinned showcase run as static files.
7. **Major:** the run store grows without bound. Use hard links, plus retention or a quota. Fix the R6 wording.
8. **Major:** reproducibility isn't designed. Record a lockfile hash, a dirty-tree flag and seeds. Add a criterion that a re-run reproduces within tolerance.
9. **Major:** security details are missing: JWT/JWKS verification, CORS, path traversal, GET rate limits, `yaml.safe_load`. Add criteria for 401/403 and for rejecting `..` paths.
10. **Major:** the unsourced Motional claim (and scenes are about 20 s anyway). Lyft "not checked" is a deferral.
11. **Major:** acceptance criteria are missing for the profile, ICP quality, reproducibility, the licence label and security. "Screenshot self-review" is subjective. The 30-minute budget has no estimate behind it.
12. **Nits:**
    - Sidewalks and cross-sections were dropped without being listed as non-goals.
    - The data flow doesn't show where the unmasked cloud is kept for the "with parked vehicles" pass.
    - Stale locks and cancelling mid-stage are not handled.
    - The tile and per-file hosting statement is inconsistent.
    - The CSF licence is not stated.
    - R8 is a process note.
    - The demo has no success signal (e.g. trace one number from sweep to drawing).
    - No alternatives are listed for the pose method or the accuracy metric.
