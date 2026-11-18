# #288 evidence

- Venue: live-mirror: Seaport (15 drives)
- Command: `rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`
- Base ref: 1d3951c (1d3951c7fbaba434250e8432aeb9acfa165ca5e9)
- After commit (at run): ff20468bf8813a8b31ae16cce036727584a0340f

## Before/after pairs
- frame p95 (ms): 283.4 -> 783.3
- whole image count: 268 -> 54
- gesture window image count: 60 -> 34
- during_gesture image count: 60 -> 34
- renderer: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) -> ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) (match=true)
- final scale text: "5 m" -> "5 m"
- drag_delta: before=true after=true
- 404s: after_unexpected=0 after_known_app_404s=7

## Screenshots (after-only)
- docs/evidence/288/after-lidar-area.png sha256=5924c7f5ac727e04547a1b4aae44932f8a3f3614e6d72d59220e54060ab5a7e4 variance=6931.145100549635
- docs/evidence/288/after-ortho-area.png sha256=22f5c73fd4683189116c94f12d65a591b0e2cc95b6d47f503e072e093a87537c variance=6953.396598318908
- docs/evidence/288/after-height-area.png sha256=64dbcfb6c600cc74d738109355cccef63ebf90cb0d06b5a451d24c8d37badcd5 variance=7133.695675565119
- docs/evidence/288/after-lidar-full.png sha256=e4f09c94b021467ef8386f652d1765585aefb23602dbca02b9cc72affc93c1e4 variance=6394.841547407744
- docs/evidence/288/after-ortho-full.png sha256=0c9a0afe9d5cb5a36dafbce12cf0fde70cf72b1cf93b4b93aedeac8d7d6dff3d variance=5162.254192599752
- docs/evidence/288/after-height-full.png sha256=fdafbb2266a7ed080fc46d3a6bcd9ddab9deab41ca577cfa80aa5f91a0376ef1 variance=6819.6866668973225
- docs/evidence/288/after-lidar-phone.png sha256=2351f163eada94430f087e98ef92085bf09dd12b3d59aa8c8217dc1cf67f6285 variance=5551.617985150361

Gate: failed
Reasons:
- frame p95 not improved: 283.4 -> 783.3
