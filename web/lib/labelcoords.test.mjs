import { test } from "node:test";
import assert from "node:assert/strict";
import { screenToUtm } from "./labelcoords.ts";

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
