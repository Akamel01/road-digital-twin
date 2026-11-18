# #288 evidence

- Venue: live-mirror: Seaport (15 drives)
- Command: `rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`
- Base ref: 1d3951c (1d3951c7fbaba434250e8432aeb9acfa165ca5e9)
- After commit (at run): 396a00a56076c11286b1c3cb0d6627c71335dba6

## Before/after pairs
- frame p95 (ms): 400 -> 983.3
- whole image count: 258 -> 54
- gesture window image count: 50 -> 34
- during_gesture image count: 50 -> 34
- renderer: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) -> ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) (match=true)
- final scale text: "5 m" -> "5 m"
- drag_delta: before=true after=true
- 404s: after_unexpected=0 after_known_app_404s=5

## Screenshots (after-only)
- docs/evidence/288/after-lidar-area.png sha256=5924c7f5ac727e04547a1b4aae44932f8a3f3614e6d72d59220e54060ab5a7e4 variance=6931.145100549635
- docs/evidence/288/after-ortho-area.png sha256=22f5c73fd4683189116c94f12d65a591b0e2cc95b6d47f503e072e093a87537c variance=6953.396598318908
- docs/evidence/288/after-height-area.png sha256=64dbcfb6c600cc74d738109355cccef63ebf90cb0d06b5a451d24c8d37badcd5 variance=7133.695675565119
- docs/evidence/288/after-lidar-full.png sha256=9480ebadee6d87f57daac93d0f916027ac7dffdbea99bb52aed3332ef07334fc variance=6369.701228321953
- docs/evidence/288/after-ortho-full.png sha256=a571a871547a9a6eae2765ea59bc9070dfa69a9e5cea83c9c593dd77dfff1d39 variance=5150.127486722946
- docs/evidence/288/after-height-full.png sha256=3a3b0fda1ad929fafe8753ca7e8a940dcc8c73eeec3f9896eb70c0b6c049c473 variance=6821.891216040995
- docs/evidence/288/after-lidar-phone.png sha256=00be23aea7d28516faf2eced9a40c941aa519714ebbca292e22f063a5dabf42c variance=5765.004502161924

Gate: failed
Reasons:
- frame p95 not improved: 400 -> 983.3
