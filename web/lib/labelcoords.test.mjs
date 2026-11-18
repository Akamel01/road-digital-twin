import { test } from "node:test";
import assert from "node:assert/strict";
import { screenToUtm, utmToLocal } from "./labelcoords.ts";
import { frameOf, localRect, visibleTiles } from "./tiles.ts";

test("screenToUtm round-trips a known point", () => {
  const frame = { ox: 100, top: 200, w: 50, h: 60 };
  const view = { k: 2, tx: 10, ty: 20 };
  // screen (30,40): local = ((30-10)/2, (40-20)/2) = (10,10); utm = (110, 190)
  const [x, y] = screenToUtm(view, frame, 30, 40);
  assert.equal(x, 110);
  assert.equal(y, 190);
});

test("screenToUtm at origin view", () => {
  const frame = { ox: 0, top: 0, w: 10, h: 10 };
  const view = { k: 1, tx: 0, ty: 0 };
  const [x, y] = screenToUtm(view, frame, 5, 5);
  assert.equal(x, 5);
  assert.equal(y, -5);
});


test("feature at tile UTM corner renders at tile corner (z=0)", () => {
  const frame = { ox: 330000, top: 4692000, w: 100, h: 100 };
  // ensure frameOf matches
  const f = frameOf([[330000, 4691900, 330100, 4692000]]);
  assert.deepEqual(f, frame);
  const bbox = [330000, 4691900, 330100, 4692000];
  const rect = localRect(bbox, frame);
  const view = { k: 1, tx: 0, ty: 0 };
  const size = { w: 1000, h: 1000 };
  const tiles = visibleTiles("lidar", "run", rect, 0, view, size);
  assert.ok(tiles.length >= 1);
  const tile = tiles[0];
  assert.deepEqual(utmToLocal(frame, [330000, 4692000]), [tile.left, tile.top]);
});

test("feature at second tile UTM corner renders at that tile corner (z=1)", () => {
  const frame = { ox: 330000, top: 4692000, w: 100, h: 100 };
  const bbox = [330000, 4691900, 330100, 4692000];
  const rect = localRect(bbox, frame);
  const view = { k: 1, tx: 0, ty: 0 };
  const size = { w: 1000, h: 1000 };
  const tiles = visibleTiles("lidar", "run", rect, 1, view, size);
  const tile = tiles.find((t) => t.left === 50 && t.top === 0);
  assert.ok(tile, "second tile not found");
  assert.deepEqual(utmToLocal(frame, [330050, 4692000]), [tile.left, tile.top]);
});
