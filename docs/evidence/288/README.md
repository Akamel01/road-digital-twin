# #288 evidence

- Venue: live-mirror: Seaport (15 drives)
- Command: `rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`
- Base ref: 1d3951c (1d3951c7fbaba434250e8432aeb9acfa165ca5e9)
- After commit (at run): e334272ccb22f6f3df4dac2f9caa7be6411d3e2e

## zoom_transition (not gated, setup)
- median: 16.7 ms -> 16.7 ms
- p95: 16.8 ms -> 16.8 ms
- samples: 141 -> 115

## pan capped (gated with vsync tolerance, 10s after settle)
- median: 16.7 ms -> 16.7 ms (tolerance +0.5ms)
- p95: 16.7 ms -> 16.8 ms (tolerance +0.5ms)
- samples: 680 -> 680
- pan image count/bytes: 0/0 -> 0/0
- top pan long tasks (before): none
- top pan long tasks (after): none

## uncapped render-cost (not vsync-capped, 5s pan after 20 clicks + 5s settle, no screenshots)
- Browser flags: --disable-frame-rate-limit --disable-gpu-vsync (alternate order fallback if primary launch fails). 3s retry once on instability.
- fps: 54.33 -> 57.33 (gate: after > before * 1.05)
- mean: 18.41 ms -> 17.44 ms
- p95: 17.8 ms -> 17.8 ms
- samples/duration: 322/5.927s -> 320/5.582s

## Context
- whole image count (navigation): 104 -> 20
- gesture (combined zoom+pan) image count: 0 -> 0
- renderer: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) -> ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) (match=true)
- final scale text: "5 m" -> "5 m"
- drag_delta: before=false after=false
- 404s: after_unexpected=0 after_known_app_404s=4

## Screenshots (after-only)
- docs/evidence/288/after-lidar-area.png sha256=2eba8e84a5e521ec34c36f4a0d116568e3089d4f1af3b5fb348d4cabbe9f7753 variance=6930.155819788962
- docs/evidence/288/after-ortho-area.png sha256=381b9bbc53277b05344a2e878b77eeac0109e6e600d07f63886feea9f4f3dcd7 variance=6952.125249281232
- docs/evidence/288/after-height-area.png sha256=f112d649b57e45002b0aaf551cfc4ac653e6285a3fb8512f710cae0d81292e7d variance=7131.897234463152
- docs/evidence/288/after-lidar-full.png sha256=d5f0aec688652211539cd712fc40a63614fbcaf635ca5a12a536e8f18eb71f29 variance=6394.8309856856795
- docs/evidence/288/after-ortho-full.png sha256=1d6ada00d4092e7f4316e0f73008348556f5556f0b5800b1740e89c0330f57ea variance=5162.253043202573
- docs/evidence/288/after-height-full.png sha256=c898d6acceb2895cb21bd5976b8d94840b5b34188751da3b8a76253efff141a2 variance=6819.7105318987515
- docs/evidence/288/after-lidar-phone.png sha256=65ff14f118e68735d2a29b473a6f9d994a28d0fbee72664c87848654eb7cd2b9 variance=5551.684821630638

Gate: passed
- Tolerance/rationale: capped pan is vsync-bound (~60fps) so median/p95 must be <= before + 0.5ms; uncapped fps must improve >5% to show real render-cost win; whole count reduced; pan samples>=100; renderers/scale match; no deck/TypeError; no unexpected tile 404s.
