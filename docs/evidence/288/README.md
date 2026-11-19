# #288 evidence

- Venue: live-mirror: Seaport (15 drives)
- Command: `rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`
- Base ref: 1d3951c (1d3951c7fbaba434250e8432aeb9acfa165ca5e9)
- After commit (at run): 6a3343ed44e58a37cd980a204bbef76e21cb95d5

## zoom_transition (not gated, setup)
- median: 16.7 ms -> 16.7 ms
- p95: 16.8 ms -> 16.8 ms
- samples: 143 -> 123

## pan capped (gated: strict p95 + median +0.5ms vsync, 10s after settle)
- median: 16.7 ms -> 16.7 ms (gate: <= before + 0.5ms)
- p95: 250 ms -> 200 ms (gate: strict < before)
- samples: 300 -> 296
- pan image count/bytes: 6/7995 -> 0/0
- pan canvas size: null -> {"width":254,"height":180,"clientWidth":1018,"clientHeight":720,"dpr":1}
- top pan long tasks (before): none
- top pan long tasks (after): 124ms@16463.6 (self)

## uncapped render-cost (not vsync-capped, 5s pan after 20 clicks + 5s settle, no screenshots)
- Browser flags: --disable-frame-rate-limit --disable-gpu-vsync (alternate order fallback if primary launch fails). 3s retry once on instability.
- fps: 54.8 -> 54.58 (CONTEXT ONLY, not gated; not worse than 2%: 54.58 vs 54.8; both sides hit SwiftShader ceiling ~55 fps, so capped pan is primary frame-time metric)
- mean: 18.25 ms -> 18.32 ms
- p95: 34.4 ms -> 28.4 ms
- samples/duration: 330/6.022s -> 354/6.486s

## Context
- whole image count (navigation): 110 -> 20
- gesture (combined zoom+pan) image count: 6 -> 0
- renderer: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) -> ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) (match=true)
- final scale text: "5 m" -> "5 m"
- drag_delta: before=true after=true
- 404s: after_unexpected=0 after_known_app_404s=4

## Screenshots (after-only)
- docs/evidence/288/after-lidar-area.png sha256=9959e402f33cf49aa0bfa07ac115174038af7e7c0a459547aa7d493609bef248 variance=6705.871665023418
- docs/evidence/288/after-ortho-area.png sha256=d3d6735208c7cc8b25500034401db441de9798606cd7cb12fdab6e23d786c370 variance=6695.300758958076
- docs/evidence/288/after-height-area.png sha256=90b32b790af30d77bb1f2a69a959243519735d6856cb9380bbde6467d743de73 variance=6695.379820851793
- docs/evidence/288/after-lidar-full.png sha256=bf429c88a65e5d8d09ad0c0502c1f3a0d240947b29596275666b2367d0e9d7ac variance=5770.307540199443
- docs/evidence/288/after-ortho-full.png sha256=0f8fd45eb0287f814223481267a4dfc3be54cf36f60c5e3876c39769d5526fad variance=5770.763115443764
- docs/evidence/288/after-height-full.png sha256=65f1d5f08b407c5d5673e649a34e738fad0ba0d75546dfd6f43d192d9b468945 variance=6722.500840646734
- docs/evidence/288/after-lidar-phone.png sha256=0fad40b1fb4edcc4a3f95f99d54dd4ca02710d93ec433d52d9feba0656d5a4aa variance=5142.307167236286

Gate: passed
- Tolerance/rationale: capped pan is vsync-bound (~60fps): strict p95 improvement (200<250) + median <= before+0.5ms; whole count reduced (110->20); pan samples>=100; renderers/scale match; no deck/TypeError; no unexpected tile 404s. Uncapped fps is context only (SwiftShader ceiling ~55 fps).
