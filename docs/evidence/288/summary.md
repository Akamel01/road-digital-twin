# #288 measured before/after

Venue: live-mirror: Seaport (15 drives)
Before source: measured (fresh this run)
After source: measured (fresh this run)

Pairs:
- frame p95: 499.9 ms -> 500 ms
- whole image count: 325 -> 24
- gesture window image count: 117 -> 12
- renderer: match (ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver))
- final scale text: "5 m" (before "5 m")

Gate: failed.
- frame p95 not improved: 499.9 -> 500
- after has deck/TypeError/Error entries: deck: `getLineDashArray` has been removed. Use `PathStyleExtension` instead
- unexpected 404s: http://127.0.0.1:36077/showcase/status.json | http://127.0.0.1:36077/favicon.ico | http://127.0.0.1:36077/showcase/status.json | http://127.0.0.1:36077/dev | http://127.0.0.1:36077/latest

Screenshots: see docs/evidence/288/README.md (sha256 + variance).
