# #288 measured before/after

Venue: live-mirror: Seaport (15 drives)
Before source: measured (fresh this run)
After source: measured (fresh this run)

Pairs:
- frame p95: 283.4 ms -> 783.3 ms
- whole image count: 268 -> 54
- gesture window image count: 60 -> 34
- renderer: match (ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver))
- final scale text: "5 m" (before "5 m")
- drag_delta: before=true after=true
- 404s: unexpected_tile=0 known_app=7

Gate: failed.
- frame p95 not improved: 283.4 -> 783.3

Screenshots: see docs/evidence/288/README.md (sha256 + variance).
