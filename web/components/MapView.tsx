"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import MapPanel, { type Analysis, type Layer, type Layers } from "@/components/MapPanel";
import {
  errCol,
  isElement,
  loadDrive,
  loadRasterMeta,
  RASTERS,
  type DriveData,
  type ElementKey,
  type Raster,
  type RasterMeta,
} from "@/lib/mapdata";
import type { AreaFacility, AreaIndex } from "@/lib/showcase";
import {
  fitView,
  frameOf,
  localRect,
  tileLevel,
  visibleTiles,
  type Rect,
  type Size,
  type Tile,
  type View,
} from "@/lib/tiles";

const MAX_K = 40; // screen px per metre
const DEFAULT_LAYERS: Layers = { lidar: true, ortho: false, markings: true, crosswalks: true, curbs: true };

interface LoadedDrive {
  run: string;
  data: DriveData;
  meta: Record<Raster, RasterMeta>;
}

interface StoredView extends View {
  key: string; // the fit key the view was set under; a new fit key drops it
}

async function loadAll(run: string): Promise<LoadedDrive> {
  const [data, metas] = await Promise.all([
    loadDrive(run),
    Promise.all(RASTERS.map((r) => loadRasterMeta(run, r))),
  ]);
  const meta = Object.fromEntries(RASTERS.map((r, i) => [r, metas[i]])) as Record<Raster, RasterMeta>;
  return { run, data, meta };
}

interface Props {
  area: AreaIndex;
  facility: AreaFacility | null;
  element: string | null;
  onElement: (e: string) => void;
}

export default function MapView({ area, facility, element, onElement }: Props) {
  const [loaded, setLoaded] = useState<LoadedDrive[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  const [view, setView] = useState<StoredView | null>(null);
  const [fly, setFly] = useState(false);
  const [dragging, setDragging] = useState(false);
  const panRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; view: View; moved: number } | null>(null);

  const frame = useMemo(
    () => frameOf(area.drives.flatMap((d) => (d.bbox ? [d.bbox] : []))),
    [area],
  );

  useEffect(() => {
    let live = true;
    Promise.all(area.drives.map((d) => loadAll(d.run_id))).then(
      (drives) => {
        if (live) setLoaded(drives);
      },
      (e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : String(e));
      },
    );
    return () => {
      live = false;
    };
  }, [area]);

  useEffect(() => {
    const el = panRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height }),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The view is refit whenever the facility or the viewport size changes. A user pan or zoom
  // stores a view under the current key, so it survives until the next refit.
  const areaRect: Rect | null = frame && { x0: 0, y0: 0, x1: frame.w, y1: frame.h };
  const runRect = (run: string | null): Rect | null => {
    const b = area.drives.find((d) => d.run_id === run)?.bbox;
    return frame && b ? localRect(b, frame) : null;
  };
  // The facility's own bbox is not in area.json yet, so a facility fits its best drive's extent.
  const target = (facility && runRect(facility.best_run)) || areaRect;
  const fitKey = `${facility?.id ?? ""}|${size.w}x${size.h}`;
  const fitted = target && size.w && size.h ? fitView(target, size, facility ? 1.5 : 1.02) : null;
  const cur = view && view.key === fitKey ? view : fitted;
  const minK = areaRect && size.w && size.h ? fitView(areaRect, size, 1.02).k * 0.8 : 0;

  function commit(next: View, animate = false) {
    setFly(animate);
    setView({ ...next, key: fitKey });
    if (animate) window.setTimeout(() => setFly(false), 320);
  }

  // Wheel needs passive:false to stop the page scrolling. No deps: it re-binds with the latest view.
  useEffect(() => {
    const el = panRef.current;
    if (!el || !cur) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const r = el!.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      const k = Math.min(MAX_K, Math.max(minK, cur!.k * Math.exp(-e.deltaY * 0.0015)));
      commit({ k, tx: mx - ((mx - cur!.tx) * k) / cur!.k, ty: my - ((my - cur!.ty) * k) / cur!.k });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  function zoomBy(m: number) {
    if (!cur) return;
    const cx = size.w / 2;
    const cy = size.h / 2;
    const k = Math.min(MAX_K, Math.max(minK, cur.k * m));
    commit({ k, tx: cx - ((cx - cur.tx) * k) / cur.k, ty: cy - ((cy - cur.ty) * k) / cur.k }, true);
  }

  function fitAll() {
    if (target && size.w && size.h) commit(fitView(target, size, facility ? 1.5 : 1.02), true);
  }

  function onPointerDown(e: ReactPointerEvent) {
    if (!cur) return;
    drag.current = { x: e.clientX, y: e.clientY, view: cur, moved: 0 };
    setDragging(true);
  }

  function onPointerMove(e: ReactPointerEvent) {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    d.moved = Math.max(d.moved, Math.hypot(dx, dy));
    commit({ k: d.view.k, tx: d.view.tx + dx, ty: d.view.ty + dy });
  }

  // A press that did not move is a click: it selects the element under the pointer.
  function onPointerUp(e: ReactPointerEvent) {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (!d || d.moved > 4 || !(e.target instanceof Element)) return;
    const hit = e.target.closest("[data-el]")?.getAttribute("data-el");
    if (hit && facility && isElement(hit)) {
      setAnalysis("accuracy"); // the map shows the analysis behind the number
      onElement(hit);
    }
  }

  function toggleLayer(k: Layer) {
    setLayers((v) => ({ ...v, [k]: !v[k] }));
  }

  function pickAnalysis(a: Analysis) {
    setAnalysis((prev) => (prev === a ? null : a));
    if (a === "safety") setLayers((v) => ({ ...v, ortho: true, lidar: false }));
  }

  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio;

  const tiles: { tile: Tile; opacity: number }[] = [];
  if (cur && frame && loaded) {
    const rasters: Raster[] = [];
    if (layers.lidar) rasters.push("lidar");
    if (layers.ortho) rasters.push("ortho");
    if (analysis === "coverage") rasters.push("coverage");
    for (const r of rasters) {
      for (const d of loaded) {
        const meta = d.meta[r];
        const rect = localRect(meta.bbox, frame);
        const z = tileLevel(cur.k, dpr, rect.x1 - rect.x0, meta.zmax);
        for (const tile of visibleTiles(r, d.run, rect, z, cur, size)) {
          tiles.push({ tile, opacity: r === "lidar" && layers.ortho ? 0.3 : 1 });
        }
      }
    }
  }

  // Vector overlays: at area level every drive, at facility level only the drives that cover it.
  // Coordinates go to the frame here, so the SVG's user units are metres from the frame's corner.
  const shown = loaded?.filter((d) => !facility || facility.runs.includes(d.run)) ?? [];
  const lines =
    frame &&
    shown.flatMap((d) =>
      d.data.lines
        .filter((l) => layers[l.element])
        .map((l, i) => ({
          key: `${d.run}-${i}`,
          el: l.element,
          p95: d.data.p95[l.element],
          pts: l.points.map(([x, y]) => `${x - frame.ox},${frame.top - y}`).join(" "),
        })),
    );

  function lineStyle(el: ElementKey, p95: number | undefined) {
    let stroke = el === "markings" ? "var(--feat-mark)" : el === "curbs" ? "var(--feat-curb)" : "var(--feat-cross)";
    let width = el === "markings" ? 1.2 : 1.4;
    if (analysis === "accuracy" && p95 !== undefined) {
      stroke = errCol(p95);
      width = 2;
    }
    const sel = element === el;
    return {
      stroke,
      width: sel ? width + 1.2 : width,
      dash: el === "curbs" ? "5 3" : undefined,
      opacity: !element || sel ? 1 : 0.4,
    };
  }

  const scaleM = cur ? [5, 10, 20, 50, 100, 200].find((v) => v * cur.k >= 60) ?? 200 : 0;

  return (
    <>
      <div
        ref={panRef}
        className={`pan${dragging ? " drag" : ""}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          drag.current = null;
          setDragging(false);
        }}
      >
        <div
          className={`world${fly ? " fly" : ""}`}
          style={cur ? { transform: `translate(${cur.tx}px, ${cur.ty}px) scale(${cur.k})` } : { display: "none" }}
        >
          {tiles.map(({ tile, opacity }) => (
            // Static tile files; next/image has no loader for a static export.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={tile.url}
              src={tile.url}
              alt=""
              draggable={false}
              style={{ left: tile.left, top: tile.top, width: tile.w, height: tile.h, opacity }}
            />
          ))}
          {frame && lines && (
            <svg width={frame.w} height={frame.h} viewBox={`0 0 ${frame.w} ${frame.h}`} aria-label="Plan overlays">
              {lines.map((l) => {
                const s = lineStyle(l.el, l.p95);
                return (
                  <polyline
                    key={l.key}
                    points={l.pts}
                    fill="none"
                    stroke={s.stroke}
                    strokeWidth={s.width}
                    strokeDasharray={s.dash}
                    opacity={s.opacity}
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
              {facility &&
                lines.map((l) => (
                  <polyline
                    key={`hit-${l.key}`}
                    className="hit"
                    data-el={l.el}
                    points={l.pts}
                    strokeWidth={10}
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
            </svg>
          )}
        </div>
      </div>

      {frame && (
        <MapPanel layers={layers} onLayer={toggleLayer} analysis={analysis} onAnalysis={pickAnalysis} />
      )}
      {frame && (
        <div className="zoom glass">
          <button type="button" onClick={() => zoomBy(1.6)} aria-label="Zoom in">+</button>
          <button type="button" onClick={() => zoomBy(1 / 1.6)} aria-label="Zoom out">−</button>
          <button type="button" onClick={fitAll} aria-label="Fit" style={{ fontSize: 13 }}>⤢</button>
        </div>
      )}
      {cur && (
        <div className="scale">
          {scaleM} m<i style={{ width: scaleM * cur.k }} />
        </div>
      )}
      {error && <p className="msg" role="alert">{error}</p>}
      {!error && !loaded && <p className="msg">Loading tiles…</p>}
      {!frame && !error && <p className="msg">No drives in the showcase.</p>}
    </>
  );
}
