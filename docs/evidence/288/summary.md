# #288 measured before/after

Venue: live-mirror: Seaport (15 drives)
Before source: measured (fresh this run)
After source: measured (fresh this run)
Gate window: capped pan (10s, +0.5ms vsync tolerance) + uncapped render-cost (5s, fps > +5%). zoom_transition reported, not gated.

zoom_transition (not gated):
- median: 16.7 ms -> 16.7 ms
- p95: 16.8 ms -> 16.8 ms (samples 141 -> 115)

pan capped (gated, vsync tolerance +0.5ms):
- median: 16.7 ms -> 16.7 ms
- p95: 16.7 ms -> 16.8 ms (samples 680 -> 680)
- images (pan window): 0/0 -> 0/0
- top long tasks (after): none

uncapped render-cost (gated, no screenshots):
- fps: 54.33 -> 57.33
- mean: 18.41 ms -> 17.44 ms
- p95: 17.8 ms -> 17.8 ms
- samples: 322 -> 320

Context:
- whole image count: 104 -> 20
- gesture (combined) image count: 0 -> 0
- renderer: match (ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver))
- final scale text: "5 m" (before "5 m")
- drag_delta: before=false after=false
- 404s: unexpected_tile=0 known_app=4

Gate: passed.

Screenshots: see docs/evidence/288/README.md (sha256 + variance).
