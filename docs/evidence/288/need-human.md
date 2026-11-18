# #288 evidence — needs human review (gate failed)

Clean re-measurement at HEAD `ff20468bf8813a8b31ae16cce036727584a0340f` (dirty-tree guard: `git status --porcelain` empty at run start). Live-mirror Seaport fixture (15 drives), Chromium SwiftShader, base ref `1d3951c7fbaba434250e8432aeb9acfa165ca5e9` reused from `/tmp/288-before-1d3951c7fbaba434250e8432aeb9acfa165ca5e9`, mirror reused from `/tmp/288-mirror`.

## Failing pair (frame p95 gate)
- frame p95 (ms): **283.4 (before) -> 783.3 (after)** — gate requires `after.frame_ms.p95 < before.frame_ms.p95`
- frame p50/median (ms): 16.7 -> 16.7
- samples: 518 (before), 312 (after) (both ≥ 100)

## Other measured pairs (real)
- whole image count: 268 -> 54 (improved)
- gesture window image count: 60 -> 34
- during_gesture image count: 60 -> 34
- renderer: SwiftShader ANGLE Vulkan match on both sides
- final scale text: "5 m" -> "5 m" (k_px_per_m 40)
- drag_delta changed: before=true after=true (zoom_changed=true, drag_ok=true)
- heap (JSHeapUsedSize): 19127848 -> 20487416
- 404s: after unexpected tile 404s = 0; after known app 404s = 7 (status.json/favicon/dev/latest)
- page errors: after_non_404 = 0
- tile zoom match (after): ok=true; max requested z lidar=6 (zmax 6), others null; expected_max_z_at_final_k=7

## Provenance/limitations
- `git_head`/`git_status_porcelain` recorded in `metrics.json` (empty)
- `gpu_memory_bytes: null`, note: "not exposed by WEBGL_debug_renderer_info on SwiftShader"
- `limitations.full_res_by_layer` recorded (observed vs expected z at MAX_K)

Real numbers only; no re-run to fish. See `docs/evidence/288/metrics.json`, `README.md`, `summary.md`, screenshots.
