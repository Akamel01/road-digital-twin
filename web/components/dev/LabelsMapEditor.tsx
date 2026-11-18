"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "@/components/dev/dev.module.css";
import {
  approve,
  loadLabels,
  newVersion,
  saveLabels,
  type GeoJsonFeature,
  type GeoJsonFeatureCollection,
  type LabelFeature,
  type SiteMeta,
} from "@/lib/labels";
import { loadArea } from "@/lib/showcase";
import { MODE_BUTTONS, LAYER_BUTTONS } from "@/lib/labeltoolbar";
import {
  frameOf,
  localRect,
  tileLevel,
  visibleTiles,
  type Frame,
  type Rect,
  type Size,
  type Tile,
  type View,
} from "@/lib/tiles";
import { loadRasterMeta, RASTERS, type Raster, type RasterMeta } from "@/lib/mapdata";
import { screenToUtm, utmToLocal } from "@/lib/labelcoords";

interface Props {
  site: string;
  meta: SiteMeta | null;
  onMeta: (m: SiteMeta) => void;
  runs: string[];
}

type Mode = "select" | "point" | "line" | "polygon";

function emptyCollection(): GeoJsonFeatureCollection<LabelFeature> {
  return { type: "FeatureCollection", features: [] };
}

function makeFeature(mode: Mode, pts: [number, number][]): GeoJsonFeature<LabelFeature> {
  if (mode === "point") {
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: pts[0] },
      properties: { id: `op-${Date.now()}`, element: "marking", type: "text", origin: "operator" },
    };
  }
  if (mode === "line") {
    return {
      type: "Feature",
      geometry: { type: "LineString", coordinates: pts },
      properties: { id: `op-${Date.now()}`, element: "marking", type: "solid_line", origin: "operator" },
    };
  }
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [pts.concat([pts[0]])] },
    properties: { id: `op-${Date.now()}`, element: "crosswalk", type: "zebra", origin: "operator" },
  };
}

function featureColor(f: LabelFeature): string {
  if (f.element === "crosswalk") return "#f59e0b";
  if (f.element === "curb") return "#22c55e";
  if (f.element === "curb_ramp") return "#a855f7";
  return "#22d3ee";
}

function vertexList(f: GeoJsonFeature<LabelFeature>): [number, number][] {
  const c = f.geometry?.coordinates;
  if (!c) return [];
  if (f.geometry?.type === "Point") return [c as [number, number]];
  if (f.geometry?.type === "Polygon") return ((c as [number, number][][])[0] ?? []).slice(0, -1);
  return (c as [number, number][]) ?? [];
}

const MAX_K = 50;
const DEFAULT_LAYERS = { height: false, lidar: true, ortho: false };

export default function LabelsMapEditor({ site, meta, onMeta, runs }: Props) {
  const [labels, setLabels] = useState<GeoJsonFeatureCollection<LabelFeature>>(emptyCollection());
  const [mode, setMode] = useState<Mode>("select");
  const [draft, setDraft] = useState<[number, number][]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [history, setHistory] = useState<GeoJsonFeatureCollection<LabelFeature>[]>([]);
  const [approvedBy, setApprovedBy] = useState("operator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [metaMaps, setMetaMaps] = useState<Record<string, Record<Raster, RasterMeta>> | null>(null);
  const [layers, setLayers] = useState({ ...DEFAULT_LAYERS });
  const [size, setSize] = useState<Size>({ w: 0, h: 0 });
  const [storedView, setStoredView] = useState<View | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragVertexRef = useRef<{ feature: number; index: number } | null>(null);
  const panState = useRef<{ x: number; y: number; view: View } | null>(null);

  useEffect(() => {
    let live = true;
    loadArea()
      .then((a) => {
        if (live) {
          const f = frameOf(a.drives.flatMap((d) => (d.bbox ? [d.bbox] : [])));
          setFrame(f);
        }
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!runs || runs.length === 0) return;
    let live = true;
    Promise.all(
      runs.map((r) =>
        Promise.all(RASTERS.map((rr) => loadRasterMeta(r, rr))).then((metas) => ({
          run: r,
          meta: Object.fromEntries(RASTERS.map((rr, i) => [rr, metas[i]])) as Record<Raster, RasterMeta>,
        })),
      ),
    )
      .then((results) => {
        if (live) setMetaMaps(Object.fromEntries(results.map((x) => [x.run, x.meta])));
      })
      .catch(() => {});
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.join("|")]);

  useEffect(() => {
    if (!site) return;
    let cancelled = false;
    loadLabels(site)
      .then((l) => {
        if (!cancelled) setLabels(l);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [site]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitted: View | null =
    frame && size.w && size.h
      ? (() => {
          const rect: Rect = { x0: 0, y0: 0, x1: frame.w, y1: frame.h };
          const k = Math.min(MAX_K, size.w / (rect.x1 - rect.x0), size.h / (rect.y1 - rect.y0));
          return { k, tx: size.w / 2 - k * (rect.x0 + rect.x1) / 2, ty: size.h / 2 - k * (rect.y0 + rect.y1) / 2 };
        })()
      : null;
  const view: View | null = storedView ?? fitted;

  const finishDraft = useCallback(() => {
    if (draft.length === 0) return;
    if (mode === "point" && draft.length < 1) return;
    if (mode === "line" && draft.length < 2) return;
    if (mode === "polygon" && draft.length < 3) return;
    setHistory((h) => [...h, labels]);
    const f = makeFeature(mode, draft);
    setLabels((prev) => ({ ...prev, features: [...prev.features, f] }));
    setDraft([]);
  }, [draft, labels, mode]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Enter") finishDraft();
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selected !== null) {
          setHistory((h) => [...h, labels]);
          setLabels((prev) => ({ ...prev, features: prev.features.filter((_, i) => i !== selected) }));
          setSelected(null);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [finishDraft, labels, selected]);

  function pushHistory() {
    setHistory((h) => [...h, labels]);
  }

  function updateFeature(i: number, patch: Partial<LabelFeature>) {
    setLabels((prev) => {
      const features = prev.features.map((f, idx) =>
        idx === i ? { ...f, properties: { ...f.properties, ...patch } } : f,
      );
      return { ...prev, features };
    });
  }

  function updateGeometry(i: number, coords: unknown) {
    setLabels((prev) => {
      const features = prev.features.map((f, idx) =>
        idx === i ? { ...f, geometry: { ...f.geometry, coordinates: coords } as GeoJsonFeature["geometry"] } : f,
      );
      return { ...prev, features };
    });
  }

  function deleteSelected() {
    if (selected === null) return;
    pushHistory();
    setLabels((prev) => ({ ...prev, features: prev.features.filter((_, i) => i !== selected) }));
    setSelected(null);
  }

  function undo() {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setLabels(prev);
      return h.slice(0, -1);
    });
  }

  async function handleSave() {
    if (!site || !meta) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const m = await saveLabels(site, meta.version, labels);
      onMeta(m);
      setInfo("Saved.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove() {
    if (!site) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const m = await approve(site, approvedBy || "operator");
      onMeta(m);
      setInfo("Approved.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleNewVersion() {
    if (!site) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const m = await newVersion(site);
      onMeta(m);
      const l = await loadLabels(site);
      setLabels(l);
      setInfo("New version created.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function toUtmFromScreen(clientX: number, clientY: number): [number, number] {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || !view || !frame) return [0, 0];
    return screenToUtm(view, frame, clientX - rect.left, clientY - rect.top);
  }

  function onContainerPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (mode !== "select") {
      const pt = toUtmFromScreen(e.clientX, e.clientY);
      setDraft((d) => [...d, pt]);
      return;
    }
    // vertex drag handled separately
    if ((e.target as Element).closest?.("[data-vertex]")) return;
    // feature select
    const hit = (e.target as Element).closest?.("[data-feature]");
    if (hit) {
      const idx = Number(hit.getAttribute("data-feature"));
      if (!Number.isNaN(idx)) setSelected(idx);
      return;
    }
    // pan
    if (view) panState.current = { x: e.clientX, y: e.clientY, view };
  }

  function onContainerPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (dragVertexRef.current && view && frame) {
      const { feature, index } = dragVertexRef.current;
      const pt = toUtmFromScreen(e.clientX, e.clientY);
      const f = labels.features[feature];
      if (!f?.geometry) return;
      const coords = f.geometry.coordinates;
      if (f.geometry.type === "Point") {
        updateGeometry(feature, pt);
      } else if (Array.isArray(coords)) {
        const copy = JSON.parse(JSON.stringify(coords));
        if (f.geometry.type === "Polygon") {
          const ring = (copy as [number, number][][])[0];
          ring[index] = pt;
          if (index === 0) ring[ring.length - 1] = pt;
          updateGeometry(feature, copy);
        } else {
          (copy as [number, number][])[index] = pt;
          updateGeometry(feature, copy);
        }
      }
      return;
    }
    if (panState.current && view) {
      const dx = e.clientX - panState.current.x;
      const dy = e.clientY - panState.current.y;
      const v = panState.current.view;
      setStoredView({ k: v.k, tx: v.tx + dx, ty: v.ty + dy });
    }
  }

  function onContainerPointerUp() {
    panState.current = null;
    dragVertexRef.current = null;
  }

  function onWheel(e: React.WheelEvent<HTMLDivElement>) {
    if (!view) return;
    e.preventDefault();
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const k = Math.min(MAX_K, Math.max(0.5, view.k * Math.exp(-e.deltaY * 0.0015)));
    setStoredView({ k, tx: mx - ((mx - view.tx) * k) / view.k, ty: my - ((my - view.ty) * k) / view.k });
  }

  function addVertexToFeature(i: number, pt: [number, number]) {
    pushHistory();
    const f = labels.features[i];
    const coords = f.geometry?.coordinates;
    if (f.geometry?.type === "LineString") {
      const arr = [...(coords as [number, number][]) , pt];
      updateGeometry(i, arr);
    } else if (f.geometry?.type === "Polygon") {
      const ring = [...((coords as [number, number][][])[0] ?? [])];
      // insert before closing duplicate
      ring.splice(ring.length - 1, 0, pt);
      updateGeometry(i, [ring]);
    }
  }

  function removeVertex(i: number, vi: number) {
    pushHistory();
    const f = labels.features[i];
    const coords = f.geometry?.coordinates;
    if (f.geometry?.type === "LineString") {
      const arr = (coords as [number, number][]).filter((_, idx) => idx !== vi);
      updateGeometry(i, arr);
    } else if (f.geometry?.type === "Polygon") {
      const ring = ((coords as [number, number][][])[0] ?? []).slice(0, -1).filter((_, idx) => idx !== vi);
      updateGeometry(i, [ring.concat([ring[0]])]);
    }
  }

  const tiles: Tile[] = [];
  if (view && frame && metaMaps) {
    const rasters: Raster[] = [];
    if (layers.height) rasters.push("height");
    if (layers.ortho) rasters.push("ortho");
    if (layers.lidar) rasters.push("lidar");
    for (const runId of runs) {
      const mm = metaMaps[runId];
      if (!mm) continue;
      for (const r of rasters) {
        const m = mm[r];
        if (!m) continue;
        const rect = localRect(m.bbox, frame);
        const z = tileLevel(view.k, typeof window === "undefined" ? 1 : window.devicePixelRatio, rect.x1 - rect.x0, m.zmax);
        for (const tile of visibleTiles(r, runId, rect, z, view, size)) tiles.push(tile);
      }
    }
  }

  const selectedFeature = selected !== null ? labels.features[selected] : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 12 }}>
      <div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          {MODE_BUTTONS.map((b) => (
            <button
              key={b.id}
              type="button"
              className={styles.button}
              aria-label={b.label}
              aria-pressed={mode === b.id}
              style={mode === b.id ? { outline: "2px solid #60a5fa", background: "var(--glass-clear-strong)" } : undefined}
              onClick={() => { setMode(b.id as Mode); setDraft([]); }}
              disabled={busy}
            >
              {b.label}
            </button>
          ))}
          <button type="button" className={styles.button} onClick={finishDraft} disabled={busy || draft.length === 0}>Finish</button>
          <button type="button" className={styles.button} onClick={deleteSelected} disabled={busy || selected === null}>Delete</button>
          <button type="button" className={styles.button} onClick={undo} disabled={busy || history.length === 0}>Undo</button>
          <button type="button" className={styles.button} onClick={handleSave} disabled={busy || !meta || meta.frozen}>Save</button>
          <button type="button" className={styles.button} onClick={handleApprove} disabled={busy || !meta || meta.frozen}>Approve</button>
          <button type="button" className={styles.button} onClick={handleNewVersion} disabled={busy || !meta}>New version</button>
          {LAYER_BUTTONS.map((b) => {
            const l = b.id as "height" | "lidar" | "ortho";
            return (
            <button
              key={b.id}
              type="button"
              className={styles.button}
              aria-label={b.label}
              aria-pressed={layers[l]}
              style={layers[l] ? { outline: "2px solid #60a5fa", background: "var(--glass-clear-strong)" } : undefined}
              onClick={() => setLayers(() => ({ height: l === "height", lidar: l === "lidar", ortho: l === "ortho" }))}
              disabled={busy}
            >
              {b.label}{layers[l] ? " ✓" : ""}
            </button>
            );
          })}
        </div>
        {error ? <p role="alert">{error}</p> : null}
        {info ? <p role="status">{info}</p> : null}
        <div
          ref={containerRef}
          style={{ width: "100%", height: 480, border: "1px solid #ccc", background: "#0d1213", position: "relative", overflow: "hidden", touchAction: "none" }}
          onPointerDown={onContainerPointerDown}
          onPointerMove={onContainerPointerMove}
          onPointerUp={onContainerPointerUp}
          onPointerLeave={onContainerPointerUp}
          onWheel={onWheel}
        >
          <svg ref={svgRef} width={size.w} height={size.h} style={{ display: "block" }}>
            {view && frame && (
              <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}>
                {tiles.map((tile) => (
                  <image key={tile.url} href={tile.url} x={tile.left} y={tile.top} width={tile.w} height={tile.h} preserveAspectRatio="none" />
                ))}
                {labels.features.map((f, i) => {
                  const drafted = f.properties.origin === "drafted";
                  const color = featureColor(f.properties);
                  const selectedFeat = selected === i;
                  const base = selectedFeat ? 3.5 : 2.5;
                  const dash = drafted ? "6 3" : undefined;
                  const coords = f.geometry?.coordinates;
                  const onSelect = () => mode === "select" && setSelected(i);
                  if (f.geometry?.type === "Point") {
                    const [x, y] = coords as [number, number];
                    const [lx, ly] = utmToLocal(frame, [x, y]);
                    const r = 3 / view.k;
                    return (
                      <g key={i} data-feature={i} onClick={onSelect}>
                        <circle cx={lx} cy={ly} r={(3 + 1) / view.k} fill="#0b0f10" opacity={0.9} vectorEffect="non-scaling-stroke" />
                        <circle cx={lx} cy={ly} r={r} fill={color} opacity={0.9} vectorEffect="non-scaling-stroke" />
                      </g>
                    );
                  }
                  if (f.geometry?.type === "LineString") {
                    const pts = (coords as [number, number][]).map((p) => utmToLocal(frame, p).join(",")).join(" ");
                    return (
                      <g key={i} data-feature={i} onClick={onSelect}>
                        <polyline points={pts} fill="none" stroke="#0b0f10" strokeWidth={base + 2} strokeDasharray={dash} opacity={0.9} vectorEffect="non-scaling-stroke" />
                        <polyline
                          points={pts}
                          fill="none"
                          stroke={color}
                          strokeWidth={base}
                          strokeDasharray={dash}
                          opacity={0.9}
                          vectorEffect="non-scaling-stroke"
                          onDoubleClick={(e) => {
                            e.stopPropagation();
                            const pt = toUtmFromScreen(e.clientX, e.clientY);
                            addVertexToFeature(i, pt);
                          }}
                        />
                      </g>
                    );
                  }
                  if (f.geometry?.type === "Polygon") {
                    const ring = (coords as [number, number][][])[0] ?? [];
                    const pts = ring.map((p) => utmToLocal(frame, p).join(",")).join(" ");
                    return (
                      <g key={i} data-feature={i} onClick={onSelect}>
                        <polygon points={pts} fill="none" stroke="#0b0f10" strokeWidth={base + 2} strokeDasharray={dash} opacity={0.9} vectorEffect="non-scaling-stroke" />
                        <polygon
                          points={pts}
                          fill={color}
                          fillOpacity={drafted ? 0.12 : 0.2}
                          stroke={color}
                          strokeWidth={base}
                          strokeDasharray={dash}
                          opacity={0.9}
                          vectorEffect="non-scaling-stroke"
                          onDoubleClick={(e) => {
                            e.stopPropagation();
                            const pt = toUtmFromScreen(e.clientX, e.clientY);
                            addVertexToFeature(i, pt);
                          }}
                        />
                      </g>
                    );
                  }
                  return null;
                })}
                {draft.length > 0 && frame && (
                  <polyline
                    points={draft.map((p) => utmToLocal(frame, p).join(",")).join(" ")}
                    fill="none"
                    stroke="#090"
                    strokeDasharray="4 2"
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                {draft.map((p, i) => {
                  const [lx, ly] = utmToLocal(frame!, p);
                  return <circle key={`d${i}`} cx={lx} cy={ly} r={3 / (view?.k ?? 1)} fill="#090" vectorEffect="non-scaling-stroke" />;
                })}
                {selected !== null &&
                  vertexList(labels.features[selected]).map((v, vi) => {
                    const [lx, ly] = utmToLocal(frame!, v);
                    return (
                      <circle
                        key={`v${vi}`}
                        data-vertex="1"
                        cx={lx}
                        cy={ly}
                        r={5 / (view?.k ?? 1)}
                        fill="#fff"
                        stroke="#d00"
                        strokeWidth={1}
                        vectorEffect="non-scaling-stroke"
                        style={{ cursor: "grab" }}
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          dragVertexRef.current = { feature: selected, index: vi };
                        }}
                        onClick={(e) => {
                          if (e.shiftKey) {
                            e.stopPropagation();
                            removeVertex(selected, vi);
                          }
                        }}
                      />
                    );
                  })}
              </g>
            )}
          </svg>
        </div>
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <b>Legend:</b> drafted (dashed) vs operator (solid); colours: marking=cyan, crosswalk=amber, curb=green, curb_ramp=purple.
        </div>
      </div>
      <aside style={{ border: "1px solid #ccc", padding: 8 }}>
        <h3 style={{ marginTop: 0 }}>Attributes</h3>
        {selectedFeature ? (
          <div style={{ display: "grid", gap: 8 }}>
            <label>
              <span>element</span>
              <input
                value={selectedFeature.properties.element}
                onChange={(e) => selected !== null && updateFeature(selected, { element: e.target.value as LabelFeature["element"] })}
              />
            </label>
            <label>
              <span>type</span>
              <input
                value={selectedFeature.properties.type}
                onChange={(e) => selected !== null && updateFeature(selected, { type: e.target.value as LabelFeature["type"] })}
              />
            </label>
            <label>
              <span>origin</span>
              <input value={selectedFeature.properties.origin} readOnly />
            </label>
            <label>
              <span>width_m</span>
              <input
                value={selectedFeature.properties.width_m ?? ""}
                onChange={(e) =>
                  selected !== null &&
                  updateFeature(selected, { width_m: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </label>
            <label>
              <span>height_m</span>
              <input
                value={selectedFeature.properties.height_m ?? ""}
                onChange={(e) =>
                  selected !== null &&
                  updateFeature(selected, { height_m: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </label>
            <label>
              <span>approved by</span>
              <input value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} />
            </label>
          </div>
        ) : (
          <p>No selection.</p>
        )}
        <details style={{ marginTop: 12 }} open={rawOpen} onToggle={(e) => setRawOpen((e.target as HTMLDetailsElement).open)}>
          <summary>Raw JSON</summary>
          <textarea
            readOnly
            value={JSON.stringify(labels, null, 2)}
            style={{ width: "100%", minHeight: 200, fontFamily: "monospace", fontSize: 11 }}
          />
        </details>
      </aside>
    </div>
  );
}
