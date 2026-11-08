# Stage 6: Comprehension test (spec)

## What this proposes

v1 is a demo for recruiters hiring for AV safety roles. It takes one nuScenes mini scene that contains an intersection and rebuilds it as a measurable 3D "twin" through a nine-stage pipeline:

1. load
2. ICP alignment to 6 DoF
3. aggregate
4. ground split
5. lane, crosswalk and curb extraction
6. vertical profile
7. intersection sight distance (AASHTO case B)
8. plan-view accuracy against the nuScenes HD map
9. outputs (LAZ, GeoJSON, DXF, PDF, manifest)

Error is stated openly, not hidden.

Every run is stored as an immutable, reproducible folder on "the box". A FastAPI control API exposes the runs: public GETs and admin-only POSTs, behind a Cloudflare Tunnel. It feeds a static Next.js UI on Cloudflare Pages, with public views and a developer panel for parameters, method choice, re-run and compare.

The work is split into 11 tickets over five days, ending 2026-11-12. Controls are the last thing cut.

## How the existing system works, per this document

There is little existing system. Decision records 0001–0003 are superseded.

- **nuScenes** gives 2D poses (z = 0), an HD map in a local frame with a lat/lon origin per location, and annotated 3D boxes.
- **The box** already holds `/data/nuscenes`, runs ollama on its GPU, and will host the API.
- **Papyrus accounts** exist, with an admin role.
- **drone-survey** has a `web/` app in the Mission Control style.

No pipeline code exists yet.

## Findings

1. **Major:** curb accuracy is partly circular. The search window comes from `drivable_area`, the same layer curbs are scored against. The diagram says "ground edge" instead.
2. **Major:** the EPSG code is hard-coded to Boston even though the scene isn't picked yet.
3. **Major:** what enabling, disabling or reordering stages means is not defined, and neither is whether invalid orders are rejected.
4. **Major:** "T2, T3 and T9 in parallel" contradicts "T9 after T3".
5. **Major:** the cut order conflicts with the acceptance criteria (DXF audit, compare) and with the priority rule.
6. **Major:** the R6 disk-check sentence is garbled.
7. **Major:** "the box" is never defined (machine, hardware, other workloads).
8. **Major:** ISD with and without parked vehicles requires keeping the masked points labelled parked or moving. Neither the stage that keeps them nor the way parked is told from moving is defined.
9. **Major:** R2's window length is not given, the Motional claim has no link, and the effect of the fallback on the profile and ISD is not stated.
10. **Major:** the Papyrus identity and token flow is not defined.
11. **Nits:**
    - "Operator" is not defined.
    - "Decision 22" can't be traced.
    - The origin of the 20 cm target is not given.
    - Mission Control, drone-survey `web/` and "briefing lessons" have no links.
    - R8 is a process note.
    - AuditorAI and Vancouver ALS have no links.
    - "Stage 0" uses the pipeline's numbering but isn't part of it.
    - "Data version", the Cloudflare limit and "TAC" are not defined.
    - Citation keys have no links.
