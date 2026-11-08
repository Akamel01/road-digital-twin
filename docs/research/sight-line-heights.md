# Sight-line target heights by situation (research only)

Research note for issue #15. No code or contract change: v1 defaults (`isd.eye_height_m` 1.08 m, `isd.object_height_m` 1.08 m) stay unchanged. Rows other than ISD Case B passenger car are documented for completeness (v1.1+).

Vocabulary per CONTEXT.md: **Access point** (not "driveway"), **Leg**, **no standard value** (not "unknown"/"N/A"). Cells with no supportable target are **no standard value**.

## Matrix: check × target

Columns: target. Cells: eye height (m) / object height (m); source [id] + section.

| Check / situation | car | headlights / taillights | pedestrian adult | pedestrian child | cyclist |
|---|---|---|---|---|---|
| ISD Case A (no control) | 1.08 / 1.08 [nchrp-383]; [aashto-green-book-2018] ch.9 | no standard value (no headlight target for ISD) | no standard value (no single target; clearance zone along curb) | no standard value (no single target; clearance zone along curb) | no standard value (not a v1 vehicle target) |
| ISD Case B (stop control): B1 left turn, B2 right turn, B3 crossing | 1.08 / 1.08 [nchrp-383]; [fhwa-idrm-2003] (h1=h2=1080 mm); [aashto-green-book-2018] ch.9 | no standard value | no standard value | no standard value | no standard value |
| ISD Case B combination truck | 2.33 / 1.08 [aashto-green-book-2018]; [ohio-dot-ldm] (truck eye 7.6 ft) | no standard value | no standard value | no standard value | no standard value |
| ISD Case C (yield control) | 1.08 / 1.08 [nchrp-383]; [aashto-green-book-2018] ch.9 | no standard value | no standard value | no standard value | no standard value |
| ISD Case D (signal control) | 1.08 / 1.08 [nchrp-383]; [aashto-green-book-2018] ch.9 | no standard value | no standard value | no standard value | no standard value |
| ISD Case E (all-way stop) | 1.08 / 1.08 [nchrp-383]; [aashto-green-book-2018] ch.9 | no standard value | no standard value | no standard value | no standard value |
| ISD Case F (left turn from major road) | 1.08 / 1.08 [nchrp-383]; [aashto-green-book-2018] ch.9 | no standard value | no standard value | no standard value | no standard value |
| SSD (stopping sight distance) | 1.08 / 0.60 (taillight) [aashto-green-book-2018] ch.3; [ohio-dot-ldm] §201.2.2 | no standard value (no headlight target; sag-curve headlights 0.5–0.6 m, 1° spread is not an SSD target) | no standard value | no standard value | no standard value |
| Decision sight distance (DSD) | 1.08 / 0.60 [aashto-green-book-2018] ch.3; [ohio-dot-ldm] §201.5 | no standard value | no standard value | no standard value | no standard value |
| PSD (passing sight distance) | 1.08 / 1.08 [aashto-green-book-2018] ch.3; [ohio-dot-ldm] §201.4 | no standard value | no standard value | no standard value | no standard value |
| Access point exit: exit ISD left/right | 1.08 / 1.08 [nchrp-383]; [aashto-green-book-2018] ch.9 | no standard value | no standard value | no standard value | no standard value |
| Cyclist (bicycle facilities, SSD basis) | no standard value (not a car target) | no standard value | no standard value | no standard value | 1.40 / 0.00 [aashto-bike-guide] |
| Pedestrian (adult/child) | no single target; clearance zone along curb (no standard value) | no target (not applicable) | clearance zone along curb (no standard value) | clearance zone along curb (no standard value) | no target (not applicable) |
| Night / headlights (sag curves) | 0.5–0.6 m headlights, 1° beam; not an ISD target (no standard value for ISD) | 0.5–0.6 m / 0.00 [ohio-dot-ldm] §201.2.2 | no standard value | no standard value | no standard value |

Notes:
- ISD Cases A–F per NCHRP 383 [nchrp-383]; AASHTO Green Book 2018 ch.9 [aashto-green-book-2018].
- SSD object height 0.60 m (2.0 ft) is the taillight height; eye height 1.08 m (3.5 ft) [aashto-green-book-2018] ch.3; [ohio-dot-ldm].
- PSD uses 1.08 / 1.08 [aashto-green-book-2018] ch.3.
- Cyclist: eye 1.40 m (4.5 ft), object 0.00 m (pavement defects) [aashto-bike-guide].
- Headlights 0.5–0.6 m, 1° upward divergence, sag-curve design only [ohio-dot-ldm] §201.2.2; not an ISD target.
- Pedestrian: no single target height in guides; treat as clearance zone along curb (no standard value) [iowa-sudas]; [ohio-dot-ldm].
- Combination (articulated) truck eye 2.33 m (7.6 ft) where cited [aashto-green-book-2018]; [ohio-dot-ldm].
- NCHRP 15-75 proposes 3.75 ft (1.14 m) eye height for SSD/ISD but is not adopted [nchrp-15-75]; not used for v1.
- UK/TAC pedestrian-child targets: DMRB CD 109 §3.1 defines an SSD envelope (eye 1.05–2.00 m, object 0.26–2.00 m) with no pedestrian- or child-specific height [dmrb-cd-109]; Manual for Streets uses eye 1.05–2.00 m to object 0.6–2.00 m with no pedestrian- or child-specific height [manual-for-streets]; TAC GDG §2.5.2.1 defines vehicle object heights only, no pedestrian- or child-specific height [tac-gdg-2017]. None found.
- No standard checks ISD at night using a headlight target: headlight sag-curve values (0.5–0.6 m, 1° upward divergence) are for vertical (sag) curve design only, not an ISD target.

## Proposed `isd.*` preset set (research only)

v1-now (no new params; existing keys only):
- `isd.case`: B1/B2/B3
- `isd.time_gap_s`: 7.5
- `isd.eye_height_m`: 1.08
- `isd.object_height_m`: 1.08
- Situation: ISD passenger car (Case B).

Future (documentation/constants only; no new params until v1.1):
- ISD passenger car: (1.08, 1.08) [nchrp-383]
- ISD combination truck: (2.33, 1.08) [aashto-green-book-2018]
- SSD: (1.08, 0.60) [aashto-green-book-2018]
- DSD: (1.08, 0.60) [aashto-green-book-2018]
- PSD: (1.08, 1.08) [aashto-green-book-2018]
- Cyclist: (1.40, 0.00) [aashto-bike-guide]
- Pedestrian: no standard value (clearance zone) [iowa-sudas]
- Night headlight: no standard value for ISD [ohio-dot-ldm]

Spec non-goals remain in force: crest-curve stopping sight distance and a TAC preset are v1.1.

## Recommendation

Keep v1 default at 1.08 m / 1.08 m for ISD Case B (passenger car); no code change in this PR. Pedestrian and night-headlight targets remain gaps for v1.1 (no standard value). Future preset values above are cited for v1.1 reuse; NCHRP 15-75 (3.75 ft eye height) is not adopted for v1 [nchrp-15-75].
