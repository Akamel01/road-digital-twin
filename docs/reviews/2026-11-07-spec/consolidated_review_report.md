# Consolidated review: twin v1 spec

Date: 2026-11-07.

Target: `docs/design/twin-v1-spec.md`.

Revision 1 went through the full EGM review:
- stage 5, zoom-out;
- stage 6, comprehension;
- stage 7, critic;
- stage 8, intermediate zoom-out.

Revision 2 then went through stage 9:
- implementation readiness;
- codebase details;
- style.

Revision 3 applies every stage 9 finding listed below.

The reports from stages 5–8 are in this folder. The stage 9 findings are summarised here.

## Stage 9 verdict on revision 2: not ready to build

The tickets said what to build but did not define the shared interfaces. Agents building in parallel would each have invented their own.

## Findings and resolution

| # | Sev | Finding | Resolution in revision 3 |
|---|---|---|---|
| 1 | Blocker | No stage input/output contract | §4 stage table, status enum, `StageResult` interface; T0 builds the models |
| 2 | Blocker | No parameter or pipeline schema | §4 parameter table (key, default, range); `pipeline.yaml` shape |
| 3 | Blocker | No API route list; Access not enforced at origin | §4 route table; `/api/r` public, `/api/w` behind Access; FastAPI checks the `Cf-Access-Jwt-Assertion` header |
| 4 | Blocker | No manifest shape; compare metrics undefined | §4 manifest fields and metrics; JSON Schema in `schemas/` |
| 5 | Blocker | Map offsets added directly to UTM ignore grid convergence (~1.3°, ~20 m/km) | §3: local tmerc at the origin, then pyproj to EPSG:32619 |
| 6 | Blocker | Boxes exist only on 2 Hz keyframes; sweeps have none | §6: per-instance interpolation between keyframes; parked flag from the nearest keyframe |
| 7 | Blocker | Access on the whole panel contradicts the read-only public panel | Only write routes are behind Access |
| 8 | Major | CI fixture can't be downloaded (login, licence) | Synthetic fixtures in CI; real data via `make itest` on the box |
| 9 | Major | Dependency errors (T8 vs T6/T7; T10 has no fixture source; T2 before ground; no Dockerfile owner) | `twin fake-run`; T8 is finished after T6/T7; select uses its own road-point rule; Dockerfile in T11 |
| 10 | Major | Operator tickets have no done-when tests | Module paths and named tests on T4–T7 |
| 11 | Major | Orphan requirements (disk check, CPU cap, repeatability, CORS, viewport checks, web CI) | Each is assigned to a ticket |
| 12 | Major | Method IDs incomplete; CSF undecided | §4 method IDs per stage; CSF = `cloth-simulation-filter`, Apache-2.0 |
| 13 | Major | Re-run semantics unspecified | §4 re-run rule; `parent` field in the manifest |
| 14 | Major | KISS-ICP is odometry, not refinement; no deskew data | §6: rigid x/y/yaw anchoring (Umeyama); deskew off; drift reported |
| 15 | Major | CORS preflight versus Access; an edge refusal can be a 302 | CORS set in Access and in FastAPI; criterion accepts 302/401/403 at the edge and 401 at the origin |
| 16 | Major | ISD Case B needs a sub-case and time gap | Parameters `isd.case` and `isd.time_gap_s`; formula stated |
| 17 | Major | TAC 1.05/1.30 values not confirmed | TAC preset moved to v1.1, pending a citation |
| 18 | Major | laspy needs a LAZ backend | `laspy[lazrs]`, `header.add_crs()` |
| 19 | Major | nuscenes-devkit on Python 3.11 is unverified | R9; tested in T1 on day 1, with fallback |
| 20 | Major | Runtime confirmed in T4, which runs only stages 1–3 | Estimated in T4, measured in T11 |
| 21 | Major | "(pose)" label covers only one cause of `height_valid=false` | Label changed to "indeterminate (height)" |
| 22 | Major | Undefined "blocking band" and "coverage proxy" | Replaced with named parameters |
| 23 | Major | "Access decision" undefined | Operator approves the DNS record and Access policy on day 1 |
| 24 | Nit | CLI signatures missing | §4 CLI list with exit codes |
| 25 | Nit | Missing deps (pyyaml, pydantic, uvicorn, filelock, PyJWT) | Added to T1 |
| 26 | Nit | Curb toggle versus `requires` | `features.curbs.enabled`; no stage requires curbs |
| 27 | Nit | `road_divider` is a median, not paint | Marked as a weaker reference |
| 28 | Nit | Pages also limits a build to 20,000 files | Added to §3 |
| 29 | Nit | Repeatability metric unclear; wording drift | Fixed in §8 |

## Reuse adopted

- Open3D `segment_plane` and `voxel_down_sample`.
- KISS-ICP's nuScenes loader.
- `NuScenesMap` for the reference layers.
- shapely for coverage.
- The ezdxf drawing add-on renders the PDF from the DXF.
- `filelock` instead of a hand-rolled lock.

## Open after stage 9

- Issue nuscenes-devkit#721 is cited for the 2D ego pose. Revision 1 had confirmed it by reading the issue; the stage 9 reviewer could not browse to re-check it.
- The default parameter values are starting points for the operator to tune. They are not validated.
