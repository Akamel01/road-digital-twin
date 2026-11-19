# #288 measured before/after

Venue: live-mirror: Seaport (15 drives)
Before source: measured (fresh this run)
After source: measured (fresh this run)
Gate window: capped pan (10s, strict p95 + median +0.5ms) + whole count + samples + renderer + scale + errors + 404s. uncapped fps is CONTEXT ONLY (SwiftShader ceiling). zoom_transition reported, not gated.

zoom_transition (not gated):
- median: 16.7 ms -> 16.7 ms
- p95: 16.8 ms -> 16.8 ms (samples 143 -> 123)

pan capped (gated, vsync tolerance +0.5ms):
- median: 16.7 ms -> 16.7 ms
- p95: 250 ms -> 200 ms (samples 300 -> 296)
- images (pan window): 6/7995 -> 0/0
- canvas: null -> {"width":254,"height":180,"clientWidth":1018,"clientHeight":720,"dpr":1}
- top long tasks (after): 124ms@16463.6 (self)

uncapped render-cost (gated, no screenshots):
- fps: 54.8 -> 54.58 (CONTEXT ONLY; not worse than 2%; both sides hit SwiftShader ceiling ~55 fps)
- mean: 18.25 ms -> 18.32 ms
- p95: 34.4 ms -> 28.4 ms
- samples: 330 -> 354

Context:
- whole image count: 110 -> 20
- gesture (combined) image count: 6 -> 0
- renderer: match (ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver))
- final scale text: "5 m" (before "5 m")
- drag_delta: before=true after=true
- 404s: unexpected_tile=0 known_app=4

Gate: passed.

Screenshots: see docs/evidence/288/README.md (sha256 + variance).
