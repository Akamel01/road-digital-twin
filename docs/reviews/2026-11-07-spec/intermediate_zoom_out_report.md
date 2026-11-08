# Stage 8: Intermediate zoom-out (spec)

Verdict: approve with changes. As a bundle, the mitigations add 1.5–2 days. Taken selectively they come out about even, because static publishing and Cloudflare Access remove planned work.

## Conflicts
- **B1 (Blocker):** the drift metric needs ground points (stage 4), so stage 2 can't use it. Compute it in stage 4 as a QA output. Set a manifest flag `height_valid=false` when it is over a threshold or when ICP fell back. The UI then shows the profile and curbs as "indeterminate (pose)". Drop the stage-2 ratio.
- **M1:** Cloudflare Access on the API's own hostname makes UI calls cross-origin: CORS with credentials, and the admin must sign in there first. Decide on day 1. Access replaces the custom token check, JWKS and rate limiting, which is less T9 work.
- **M2:** public views read **one pinned run** published as static files in the Pages build, via a manual `twin publish <run-id>`. The developer panel reads the API. Ship a downsampled LAZ. This removes GET rate limits and the box as a single point of failure. The API/worker split is deferred.

## Adopt
- **M3:** fixed stage order with static `requires` lists. Only leaf stages can be switched off. No free reordering, no artifact DAG. **This changes goal 6 and needs the operator's sign-off.**
- **M4:** stage-0 go/no-go on ground density and paint/asphalt contrast, with the no-go branch decided in advance (markings reported as "not extractable"; crosswalks and curbs only). Restrict to Boston scenes (EPSG 32619) or use a lookup from location to EPSG.
- **M5:** corrected ISD blocking band (above ground, below the line of sight, near the ray). Unscanned space is caught by a 2D proxy (a gap in ground density along the ray), which gives "indeterminate". 3D ray-casting moves to v1.1. Stage 3 writes the masked points; the nuScenes `vehicle.parked` attribute separates parked vehicles.
- **M6:** mask road users before ICP. Reword to "relative z/attitude". Add one sentence: the absolute georeference error is unknown.
- **N1:** use the stage-4 ground edge as the curb search window, or keep `drivable_area` and label the result "map-conditioned". Prior-free curbs are deferred.
- **N2:** manifest records the lockfile hash, a dirty-tree flag and seeds. New criterion: running the same parameters twice gives P50/P95 within tolerance.
- **N3:** hard links, not copies. The disk check is the v1 quota. Compare covers metrics and parameters only.
- **N4:** `yaml.safe_load`, schema validation, rejection of `..` paths, and an unauthenticated POST returns 401/403.

## Defer
Boston 3DEP z reference; ground-plane pose method; API/worker split; R2; artifact DAG; 3D occupancy; prior-free curbs; retention and quotas; hash-diff compare; MLflow (one-line rejection).

## Schedule
- **M7:** the honesty items (`height_valid`, ISD "indeterminate", the "map-conditioned" label) are **never cut**. Compare is a control, so it comes off the cut list. Fix the T2/T3/T9 parallelism statement. Day 1 gains the density check and the Access decision.
