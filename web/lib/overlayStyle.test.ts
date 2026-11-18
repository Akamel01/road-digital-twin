import { describe, it, expect } from "vitest";
import { withAlpha } from "./colors";
import { overlayStyle } from "./overlayStyle";
import type { Tokens } from "./colors";

const tokens = {
  mark: [242, 242, 238, 255],
  cross: [127, 196, 232, 255],
  curb: [224, 169, 79, 255],
  sight: [201, 182, 242, 255],
  fac: [242, 210, 122, 255],
  danger: [224, 112, 79, 255],
  white: [255, 255, 255, 255],
} as Tokens;

describe("overlayStyle", () => {
  it("widths for markings/crosswalks/curbs", () => {
    expect(overlayStyle("markings", false, false, false, null, tokens).width).toBe(1.2);
    expect(overlayStyle("crosswalks", true, false, false, null, tokens).width).toBe(1.2);
    expect(overlayStyle("curbs", false, false, false, null, tokens).width).toBe(1.4);
  });
  it("accuracy width 2", () => {
    expect(overlayStyle("markings", false, false, false, "#9CC7A4", tokens).width).toBe(2);
  });
  it("selected adds", () => {
    expect(overlayStyle("markings", true, true, false, null, tokens).width).toBe(2.2);
    expect(overlayStyle("markings", false, true, false, null, tokens).width).toBe(2.4);
  });
  it("dimmed stroke alpha 102", () => {
    const s = overlayStyle("markings", false, false, true, null, tokens);
    expect(s.color[3]).toBe(102);
  });
  it("closed fill alpha", () => {
    const sel = overlayStyle("crosswalks", true, true, false, null, tokens);
    const unsel = overlayStyle("crosswalks", true, false, false, null, tokens);
    expect(sel.fill![3]).toBe(89);
    expect(unsel.fill![3]).toBe(46);
  });
  it("curbs open dash", () => {
    expect(overlayStyle("curbs", false, false, false, null, tokens).dash).toEqual([5, 3]);
  });
  it("withAlpha 4-tuple", () => {
    expect(withAlpha([1, 2, 3, 255], 18)).toEqual([1, 2, 3, 18]);
  });
});
