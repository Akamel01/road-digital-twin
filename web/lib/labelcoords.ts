import type { Frame, View } from "@/lib/tiles";

/** Local frame metres: x east from ox, y south from top (screen-down). */
export function utmToLocal(frame: Frame, utm: [number, number]): [number, number] {
  return [utm[0] - frame.ox, frame.top - utm[1]];
}

/** Inverse of utmToLocal: screen/local metres -> UTM. */
export function localToUtm(frame: Frame, lx: number, ly: number): [number, number] {
  return [frame.ox + lx, frame.top - ly];
}

/** Convert a screen pixel to a UTM coordinate under the given view/frame. */
export function screenToUtm(view: View, frame: Frame, sx: number, sy: number): [number, number] {
  const lx = (sx - view.tx) / view.k;
  const ly = (sy - view.ty) / view.k;
  return [frame.ox + lx, frame.top - ly];
}
