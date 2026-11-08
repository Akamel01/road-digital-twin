"use client";

import { useRef } from "react";
import type { Fig } from "@/lib/summary";

export type Sheet = "peek" | "half" | "full";

export const PEEK_PX = 72; // visible height of the sheet in peek; the CSS uses the same number
const NEXT: Record<Sheet, Sheet> = { peek: "half", half: "full", full: "peek" };
const SNAPS: Sheet[] = ["peek", "half", "full"];

// Translate offset of the sheet (its height is 88dvh) for each state. Zero shows the whole sheet.
function offsetOf(s: Sheet, sheetH: number): number {
  if (s === "full") return 0;
  if (s === "half") return sheetH - window.innerHeight * 0.5;
  return sheetH - PEEK_PX;
}

interface Props {
  title: string;
  figure: Fig;
  sheet: Sheet;
  onSheet: (s: Sheet) => void;
}

/**
 * The sheet's grip and peek line: name and one key figure, always visible. A tap steps peek, half, full, peek.
 * A drag moves the sheet by hand and snaps to the nearest state on release. Transform only.
 */
export default function SheetHead({ title, figure, sheet, onSheet }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ y: number; base: number; moved: number; sheetH: number } | null>(null);
  const suppressClick = useRef(false);

  function sheetEl(): HTMLElement | null {
    return ref.current?.parentElement ?? null; // the .rail element
  }

  function onPointerDown(e: React.PointerEvent<HTMLButtonElement>) {
    const rail = sheetEl();
    if (!rail) return;
    drag.current = { y: e.clientY, base: offsetOf(sheet, rail.offsetHeight), moved: 0, sheetH: rail.offsetHeight };
  }

  function onPointerMove(e: React.PointerEvent<HTMLButtonElement>) {
    const d = drag.current;
    const rail = sheetEl();
    if (!d || !rail) return;
    const dy = e.clientY - d.y;
    d.moved = Math.max(d.moved, Math.abs(dy));
    if (d.moved <= 4) return;
    const off = Math.min(d.sheetH - PEEK_PX, Math.max(0, d.base + dy));
    rail.style.transition = "none";
    rail.style.transform = `translateY(${off}px)`;
  }

  function onPointerUp(e: React.PointerEvent<HTMLButtonElement>) {
    const d = drag.current;
    drag.current = null;
    const rail = sheetEl();
    if (!d || !rail || d.moved <= 4) return; // a tap: the click handler steps the state
    suppressClick.current = true;
    const off = Math.min(d.sheetH - PEEK_PX, Math.max(0, d.base + (e.clientY - d.y)));
    // Snap to the nearest state.
    const best = SNAPS.reduce((a, s) => (Math.abs(offsetOf(s, d.sheetH) - off) < Math.abs(offsetOf(a, d.sheetH) - off) ? s : a));
    rail.style.transition = "";
    rail.style.transform = "";
    onSheet(best);
  }

  function onClick() {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    onSheet(NEXT[sheet]);
  }

  return (
    <button
      ref={ref}
      type="button"
      className="sheetgrip glass"
      aria-label={`${title}. Sheet ${sheet}. Tap to change height, or drag.`}
      onClick={onClick}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => {
        drag.current = null;
        const rail = sheetEl();
        if (rail) {
          rail.style.transition = "";
          rail.style.transform = "";
        }
      }}
    >
      <span className="grab" aria-hidden="true" />
      <span className="peekline">
        <b>{title}</b>
        <span className="num">
          {figure.value}
          <small>{figure.label}</small>
        </span>
      </span>
    </button>
  );
}
