# Stage 5: Initial zoom-out (spec)

Target: `docs/design/twin-v1-spec.md`.

## egm-zoom-out — approve with changes (0 Blocker, 6 Major, 6 Nit)

- **M1:** the public views read through the API, so the demo depends on the live production box. Publish chosen runs as static files (Pages, or R2 above 25 MiB). The API is only for the developer panel.
- **M2:** a free-form pipeline editor is beyond what v1 needs, because the stages run in a fixed order. v1 controls should be: choose a method where more than one is registered, turn off stages nothing depends on, and let the runner check dependencies. Drop free reordering, or have the operator confirm it.
- **M3:** the control plane is hand-built. Put the POST routes behind Cloudflare Access instead of a custom token check and rate limiter. Say why MLflow was rejected, or that the run store follows the drone-survey Nodes and Manifests pattern (0002 #8).
- **M4:** the R2 fallback to dataset poses breaks the profile. When that fallback is used, mark the profile and the height-dependent ISD legs "indeterminate" in the UI, not only in the manifest.
- **M5:** the EPSG code is hard-coded to 32619, which is wrong for Singapore scenes (32648). Derive it from the scene's location, or limit stage 0 to Boston.
- **M6:** the cut order (compare-runs is cut 3rd) contradicts the priority rule (controls are cut last).
- **N1:** the occlusion rule is worded backwards. Also, the "with parked vehicles" variant needs stage 3 to output the masked points.
- **N2:** the disk-check wording is backwards.
- **N3:** a re-run should link the parent run's files, not copy them.
- **N4:** stage 0 is missing from the diagram.
- **N5:** R8 is a process note.
- **N6:** the uncited claim "never audited"; GDAL or a single image is enough for tiles; use KISS-ICP's own pipeline.

## egm-inventive-catalyst — 4 Major, 3 Nit

1. **Major: a reorderable linear pipeline gives freedom that has no use and produces invalid runs.** Each method should declare the artifacts it consumes and produces. The runner then works out the order and checks that disabled stages don't break later ones. The panel edits the method, the parameters, and on/off for optional leaf stages. The operator must agree that "structure" means method choice (decision 23).
2. **Major: the production box serves public reads and also runs the pipeline.** Split the API process from the worker. After each run, publish its read-only outputs to Pages or R2, so public views never reach the box. The tunnel then carries only admin POSTs and status.
3. **Major: the ICP fallback produces a result already known to be wrong.** If ICP fails or z-drift exceeds a threshold, mark the profile "indeterminate (pose fallback)". Cheaper option: take z, pitch and roll per sweep from a ground-plane fit.
4. **Major: "no z reference" is not fixed.** Two options:
   - Add internal consistency: ground z where sweeps overlap, and a near-sensor single sweep compared against the aggregate.
   - As a stretch goal, a Boston airborne lidar reference (USGS 3DEP or MassGIS; unverified). This needs datum care (NAVD88 against ellipsoid heights).
5. **Nit:** the EPSG code is hard-coded (same as zoom-out M5).
6. **Nit:** re-runs should hard-link or hash stage outputs, which makes comparing runs a hash diff. The disk-check wording is backwards.
7. **Nit:** the cut order conflicts with the priority rule. Cutting curbs first also removes the curb accuracy row; say so.
