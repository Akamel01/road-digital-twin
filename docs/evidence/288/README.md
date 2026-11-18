# #288 evidence

- Venue: live-mirror: Seaport (15 drives)
- Command: `rm -rf web/out && bash web/scripts/fake-showcase.sh && npm --prefix web run build && node web/scripts/measure-288.mjs --before 1d3951c --out docs/evidence/288`
- Base ref: 1d3951c (1d3951c7fbaba434250e8432aeb9acfa165ca5e9)
- After commit (at run): a303e704365bb42202ee755babb5394df4ef2cb3

## Before/after pairs
- frame p95 (ms): 300 -> 733.4
- whole image count: 246 -> 54
- gesture window image count: 38 -> 34
- during_gesture image count: 38 -> 34
- renderer: ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) -> ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver) (match=true)
- final scale text: "5 m" -> "5 m"
- drag_delta: before=true after=true
- 404s: after_unexpected=0 after_known_app_404s=7

## Screenshots (after-only)
- docs/evidence/288/after-lidar-area.png sha256=2eba8e84a5e521ec34c36f4a0d116568e3089d4f1af3b5fb348d4cabbe9f7753 variance=6930.155819788962
- docs/evidence/288/after-ortho-area.png sha256=381b9bbc53277b05344a2e878b77eeac0109e6e600d07f63886feea9f4f3dcd7 variance=6952.125249281232
- docs/evidence/288/after-height-area.png sha256=f112d649b57e45002b0aaf551cfc4ac653e6285a3fb8512f710cae0d81292e7d variance=7131.897234463152
- docs/evidence/288/after-lidar-full.png sha256=d5f0aec688652211539cd712fc40a63614fbcaf635ca5a12a536e8f18eb71f29 variance=6394.8309856856795
- docs/evidence/288/after-ortho-full.png sha256=f9bbe4225ddda34b50b452fd90bbbaaa94798269d2e159f919a996784958ebfa variance=5162.252731512726
- docs/evidence/288/after-height-full.png sha256=f375d89c48d1ff5b98e00f6c4077fbbc0ac2ffe2a686043dca3e27425552baf9 variance=6819.710120968813
- docs/evidence/288/after-lidar-phone.png sha256=7d9b2f1fd245edfa7abfb4721a68accf463599e215e0c68b2c8b772065d02532 variance=5771.347222016384

Gate: failed
Reasons:
- frame p95 not improved: 300 -> 733.4
