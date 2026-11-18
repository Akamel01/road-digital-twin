# #288 evidence

- Venue: live-mirror: Seaport (15 drives)
- Command: `rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`
- Base ref: 1d3951c (1d3951c7fbaba434250e8432aeb9acfa165ca5e9)
- After commit (at run): f82c69c0338885b097999ec720badfe5724db303

## Before/after pairs
- frame p95 (ms): 499.9 -> 500
- whole image count: 325 -> 24
- gesture window image count: 117 -> 12
- during_gesture image count: 117 -> 4
- renderer: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) -> ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) (match=true)
- final scale text: "5 m" -> "5 m"

## Screenshots (after-only)
- docs/evidence/288/after-lidar-area.png sha256=5924c7f5ac727e04547a1b4aae44932f8a3f3614e6d72d59220e54060ab5a7e4 variance=6931.145100549635
- docs/evidence/288/after-ortho-area.png sha256=22f5c73fd4683189116c94f12d65a591b0e2cc95b6d47f503e072e093a87537c variance=6953.396598318908
- docs/evidence/288/after-height-area.png sha256=64dbcfb6c600cc74d738109355cccef63ebf90cb0d06b5a451d24c8d37badcd5 variance=7133.695675565119
- docs/evidence/288/after-lidar-full.png sha256=9480ebadee6d87f57daac93d0f916027ac7dffdbea99bb52aed3332ef07334fc variance=6369.701228321953
- docs/evidence/288/after-ortho-full.png sha256=7babf9656456d11959832adb2c32d9288997c7e23a3e797ae583b398165ede83 variance=6552.065485056479
- docs/evidence/288/after-height-full.png sha256=2b700be7a388284c4544e0cfa13f53bfc4a7b776f60408b6b2bf1b8ca1d45adb variance=6554.691951554735
- docs/evidence/288/after-lidar-phone.png sha256=9ef58952a1f4ae82ec9883fcf96720b92f17e508ef53530c57c72f0603a10982 variance=5679.775694544446

Gate: failed
Reasons:
- frame p95 not improved: 499.9 -> 500
- after has deck/TypeError/Error entries: deck: `getLineDashArray` has been removed. Use `PathStyleExtension` instead
- unexpected 404s: http://127.0.0.1:36077/showcase/status.json | http://127.0.0.1:36077/favicon.ico | http://127.0.0.1:36077/showcase/status.json | http://127.0.0.1:36077/dev | http://127.0.0.1:36077/latest
