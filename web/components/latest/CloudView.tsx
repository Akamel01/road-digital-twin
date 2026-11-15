"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Cloud, Scorecard } from "@/lib/latest";
import styles from "./latest.module.css";

export function driveColor(i: number): [number, number, number] {
  // golden-angle hues: neighbouring drives stay distinguishable
  const h = ((i * 137.508) % 360) / 60;
  const f = h - Math.floor(h);
  const [l, c] = [0.72, 0.55];
  const q = Math.floor(h) % 6;
  const rgb = [
    [1, f, 0],
    [1 - f, 1, 0],
    [0, 1, f],
    [0, 1 - f, 1],
    [f, 0, 1],
    [1, 0, 1 - f],
  ][q];
  return rgb.map((v) => Math.round(255 * (l + (v - 0.5) * c * 1.2))) as [number, number, number];
}

function heightColor(t: number): [number, number, number] {
  // dark teal to pale gold
  return [Math.round(30 + 210 * t), Math.round(90 + 130 * t), Math.round(110 + 20 * t)];
}

type Mode = "drive" | "height";

interface View {
  scale: number; // px per metre
  cx: number; // metres from origin at the screen centre
  cy: number;
}

export default function CloudView({ cloud, card }: { cloud: Cloud; card: Scorecard }) {
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [mode, setMode] = useState<Mode>("drive");
  const view = useRef<View>({ scale: 1, cx: 0, cy: 0 });
  const [tick, setTick] = useState(0);
  const [on, setOn] = useState<Set<number> | null>(null); // null = all drives
  const { span } = card.cloud;

  const draw = useCallback(() => {
    const canvas = cv.current;
    const box = wrap.current;
    if (!canvas || !box) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.max(1, Math.floor(box.clientWidth * dpr));
    const h = Math.max(1, Math.floor(box.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(w, h);
    const buf = new Uint32Array(img.data.buffer);
    const { scale, cx, cy } = view.current;
    const s = scale * dpr;
    const px = (span[0] / 65535) * s;
    const py = (span[1] / 65535) * s;
    const ox = w / 2 - cx * s;
    const oy = h / 2 + cy * s;
    const dot = Math.max(1, Math.min(4, Math.round(card.cloud.voxel_m * s)));
    const colours = new Uint32Array(256);
    for (let d = 0; d < 256; d++) {
      const [r, g, b] = driveColor(d);
      colours[d] = (255 << 24) | (b << 16) | (g << 8) | r;
    }
    const ramp = new Uint32Array(256);
    for (let t = 0; t < 256; t++) {
      const [r, g, b] = heightColor(t / 255);
      ramp[t] = (255 << 24) | (b << 16) | (g << 8) | r;
    }
    for (let i = 0; i < cloud.n; i++) {
      const d = cloud.drive[i];
      if (on && !on.has(d)) continue;
      const x = Math.round(ox + cloud.x[i] * px);
      const y = Math.round(oy - cloud.y[i] * py);
      if (x < 0 || y < 0 || x >= w - dot || y >= h - dot) continue;
      const c = mode === "drive" ? colours[d] : ramp[cloud.z[i] >> 8];
      for (let dy = 0; dy < dot; dy++) for (let dx = 0; dx < dot; dx++) buf[(y + dy) * w + x + dx] = c;
    }
    ctx.putImageData(img, 0, 0);
  }, [cloud, card, span, mode, on]);

  const fit = useCallback(() => {
    const box = wrap.current;
    if (!box) return;
    const sc = Math.min(box.clientWidth / span[0], box.clientHeight / span[1]) * 0.92;
    view.current = { scale: sc, cx: span[0] / 2, cy: span[1] / 2 };
    setTick((t) => t + 1);
  }, [span]);

  useEffect(() => {
    fit();
    const box = wrap.current;
    if (!box) return;
    const ro = new ResizeObserver(fit);
    ro.observe(box);
    return () => ro.disconnect();
  }, [fit]);

  useEffect(() => {
    const id = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(id);
  }, [draw, tick]);

  // Pan with one pointer, pinch with two, wheel to zoom about the cursor.
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef(0);
  const zoomAt = (f: number, sx: number, sy: number) => {
    const box = wrap.current;
    if (!box) return;
    const v = view.current;
    const dx = sx - box.clientWidth / 2;
    const dy = sy - box.clientHeight / 2;
    const ns = Math.min(Math.max(v.scale * f, 0.05), 400);
    const k = ns / v.scale;
    view.current = { scale: ns, cx: v.cx + (dx / v.scale) * (1 - 1 / k), cy: v.cy - (dy / v.scale) * (1 - 1 / k) };
    setTick((t) => t + 1);
  };
  const rel = (e: React.PointerEvent | React.WheelEvent) => {
    const r = wrap.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const toggle = (d: number) => {
    const all = card.drives.map((x) => x.index);
    const cur = on ?? new Set(all);
    const next = new Set(cur);
    if (next.has(d)) next.delete(d);
    else next.add(d);
    setOn(next.size === all.length ? null : next);
  };

  return (
    <div className={styles.viewer}>
      <div
        ref={wrap}
        className={styles.canvasWrap}
        onPointerDown={(e) => {
          wrap.current?.setPointerCapture(e.pointerId);
          pts.current.set(e.pointerId, rel(e));
          pinch.current = 0;
        }}
        onPointerMove={(e) => {
          const old = pts.current.get(e.pointerId);
          if (!old) return;
          const now = rel(e);
          pts.current.set(e.pointerId, now);
          if (pts.current.size === 1) {
            const v = view.current;
            view.current = { ...v, cx: v.cx - (now.x - old.x) / v.scale, cy: v.cy + (now.y - old.y) / v.scale };
            setTick((t) => t + 1);
          } else if (pts.current.size === 2) {
            const [a, b] = [...pts.current.values()];
            const dist = Math.hypot(a.x - b.x, a.y - b.y);
            if (pinch.current) zoomAt(dist / pinch.current, (a.x + b.x) / 2, (a.y + b.y) / 2);
            pinch.current = dist;
          }
        }}
        onPointerUp={(e) => {
          pts.current.delete(e.pointerId);
          pinch.current = 0;
        }}
        onPointerCancel={(e) => pts.current.delete(e.pointerId)}
        onWheel={(e) => {
          const p = rel(e);
          zoomAt(Math.exp(-e.deltaY * 0.0015), p.x, p.y);
        }}
      >
        <canvas ref={cv} role="img" aria-label="Top-down view of the merged point cloud" />
        <div className={`${styles.ctl} glass`}>
          <button type="button" aria-label="Zoom in" onClick={() => zoomAt(1.5, wrap.current!.clientWidth / 2, wrap.current!.clientHeight / 2)}>
            +
          </button>
          <button type="button" aria-label="Zoom out" onClick={() => zoomAt(1 / 1.5, wrap.current!.clientWidth / 2, wrap.current!.clientHeight / 2)}>
            −
          </button>
          <button type="button" aria-label="Fit to view" onClick={fit}>
            ⌂
          </button>
        </div>
      </div>
      <div className={styles.legend}>
        <div className={styles.seg} role="group" aria-label="Colour points by">
          <button type="button" aria-pressed={mode === "drive"} onClick={() => setMode("drive")}>
            By drive
          </button>
          <button type="button" aria-pressed={mode === "height"} onClick={() => setMode("height")}>
            By height
          </button>
        </div>
        <ul>
          {card.drives.map((d) => {
            const [r, g, b] = driveColor(d.index);
            const shown = !on || on.has(d.index);
            return (
              <li key={d.index}>
                <button type="button" aria-pressed={shown} onClick={() => toggle(d.index)} title={`${d.scene}, ${d.date}`}>
                  <i style={{ background: mode === "drive" ? `rgb(${r} ${g} ${b})` : "var(--ink-2)", opacity: shown ? 1 : 0.25 }} />
                  {d.scene}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
