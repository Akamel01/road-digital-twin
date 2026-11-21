import type { RGBA, Tokens } from "./colors";
import { withAlpha, hexToRgba } from "./colors";

export interface OverlayStyle {
  color: RGBA;
  width: number;
  fill: RGBA | null;
  dash?: number[];
}

export function overlayStyle(
  el: "markings" | "crosswalks" | "curbs",
  closed: boolean,
  sel: boolean,
  dimmed: boolean,
  accuracyColor: string | RGBA | null | undefined,
  tokens: Tokens,
): OverlayStyle {
  const baseWidth = accuracyColor ? 2 : el === "curbs" ? 1.4 : 1.2;
  let width = baseWidth;
  if (sel) width += closed ? 1 : 1.2;

  let color: RGBA;
  if (accuracyColor) {
    color = typeof accuracyColor === "string" ? hexToRgba(accuracyColor) : accuracyColor;
  } else {
    color = el === "markings" ? tokens.mark : el === "crosswalks" ? tokens.cross : tokens.curb;
  }
  if (dimmed) color = withAlpha(color, 102);

  const fill = closed ? withAlpha(color, sel ? 89 : 18) : null;

  const dash = el === "curbs" && !closed ? [5, 3] : [1, 0];

  return { color, width, fill, dash };
}
