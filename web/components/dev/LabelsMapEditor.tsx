"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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

interface Props {
  site: string;
  meta: SiteMeta | null;
  onMeta: (m: SiteMeta) => void;
}

type Mode = "select" | "point" | "line" | "polygon";

interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

function boundsOf(fc: GeoJsonFeatureCollection<LabelFeature> | null, meta: SiteMeta | null) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  function visit(c: unknown) {
    if (!Array.isArray(c)) return;
    if (c.length === 2 && typeof c[0] === "number" && typeof c[1] === "number") {
      const [x, y] = c as [number, number];
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      return;
    }
    for (const v of c) visit(v);
  }
  if (meta?.polygon) visit((meta.polygon as { coordinates?: unknown }).coordinates ?? meta.polygon);
  if (fc) for (const f of fc.features) visit(f.geometry?.coordinates);
  if (!isFinite(minX)) {
    minX = 0; minY = 0; maxX = 100; maxY = 100;
  }
  const pad = Math.max((maxX - minX) * 0.05, 1);
  return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
}

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

export default function LabelsMapEditor({ site, meta, onMeta }: Props) {
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
  const [viewBox, setViewBox] = useState<ViewBox>({ x: 0, y: 0, w: 100, h: 100 });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const panRef = useRef<{ startX: number; startY: number; vb: ViewBox } | null>(null);
  const dragVertexRef = useRef<{ feature: number; index: number } | null>(null);

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
    if (!site) return;
    let cancelled = false;
    loadLabels(site)
      .then((l) => {
        if (!cancelled) {
          setLabels(l);
          setViewBox(boundsOf(l, meta));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [site, meta]);

  const screenToData = useCallback(
    (clientX: number, clientY: number): [number, number] => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return [0, 0];
      const x = viewBox.x + ((clientX - rect.left) / rect.width) * viewBox.w;
      const y = viewBox.y + ((clientY - rect.top) / rect.height) * viewBox.h;
      return [x, y];
    },
    [viewBox],
  );

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
    setLabels((prev) => ({
      ...prev,
      features: prev.features.filter((_, i) => i !== selected),
    }));
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
      setViewBox(boundsOf(l, meta));
      setInfo("New version created.");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function onSvgPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if (mode !== "select") {
      const pt = screenToData(e.clientX, e.clientY);
      setDraft((d) => [...d, pt]);
      return;
    }
    if ((e.target as Element).tagName.toLowerCase() === "svg" || (e.target as SVGElement).dataset?.bg === "1") {
      panRef.current = { startX: e.clientX, startY: e.clientY, vb: { ...viewBox } };
    }
  }

  function onSvgPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    if (panRef.current) {
      const dx = e.clientX - panRef.current.startX;
      const dy = e.clientY - panRef.current.startY;
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      const scaleX = panRef.current.vb.w / rect.width;
      const scaleY = panRef.current.vb.h / rect.height;
      setViewBox({
        ...panRef.current.vb,
        x: panRef.current.vb.x - dx * scaleX,
        y: panRef.current.vb.y - dy * scaleY,
      });
      return;
    }
    if (dragVertexRef.current) {
      const { feature, index } = dragVertexRef.current;
      const pt = screenToData(e.clientX, e.clientY);
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
    }
  }

  function onSvgPointerUp() {
    panRef.current = null;
    dragVertexRef.current = null;
  }

  function onWheel(e: React.WheelEvent<SVGSVGElement>) {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.1 : 0.9;
    setViewBox((vb) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return vb;
      const mx = vb.x + ((e.clientX - rect.left) / rect.width) * vb.w;
      const my = vb.y + ((e.clientY - rect.top) / rect.height) * vb.h;
      const nw = vb.w * factor;
      const nh = vb.h * factor;
      return { x: mx - (mx - vb.x) * (nw / vb.w), y: my - (my - vb.y) * (nh / vb.h), w: nw, h: nh };
    });
  }

  const selectedFeature = selected !== null ? labels.features[selected] : null;

  function vertexList(f: GeoJsonFeature<LabelFeature>): [number, number][] {
    const c = f.geometry?.coordinates;
    if (!c) return [];
    if (f.geometry?.type === "Point") return [c as [number, number]];
    if (f.geometry?.type === "Polygon") return ((c as [number, number][][])[0] ?? []).slice(0, -1);
    return (c as [number, number][]) ?? [];
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 12 }}>
      <div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          {(["select", "point", "line", "polygon"] as Mode[]).map((m) => (
            <button key={m} type="button" onClick={() => { setMode(m); setDraft([]); }} disabled={busy}>
              {m}
            </button>
          ))}
          <button type="button" onClick={finishDraft} disabled={busy || draft.length === 0}>Finish</button>
          <button type="button" onClick={deleteSelected} disabled={busy || selected === null}>Delete</button>
          <button type="button" onClick={undo} disabled={busy || history.length === 0}>Undo</button>
          <button type="button" onClick={handleSave} disabled={busy || !meta || meta.frozen}>Save</button>
          <button type="button" onClick={handleApprove} disabled={busy || !meta || meta.frozen}>Approve</button>
          <button type="button" onClick={handleNewVersion} disabled={busy || !meta}>New version</button>
        </div>
        {error ? <p role="alert">{error}</p> : null}
        {info ? <p role="status">{info}</p> : null}
        <svg
          ref={svgRef}
          width="100%"
          height="480"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
          onPointerDown={onSvgPointerDown}
          onPointerMove={onSvgPointerMove}
          onPointerUp={onSvgPointerUp}
          onWheel={onWheel}
          style={{ border: "1px solid #ccc", background: "#f8f8f8", touchAction: "none" }}
        >
          <rect data-bg="1" x={viewBox.x} y={viewBox.y} width={viewBox.w} height={viewBox.h} fill="transparent" />
          {labels.features.map((f, i) => {
            const sel = selected === i;
            const stroke = sel ? "#d00" : "#333";
            const coords = f.geometry?.coordinates;
            if (f.geometry?.type === "Point") {
              const [x, y] = coords as [number, number];
              return (
                <circle
                  key={i}
                  cx={x}
                  cy={y}
                  r={Math.max(viewBox.w / 200, 1)}
                  fill={sel ? "#d00" : "#06c"}
                  onClick={() => mode === "select" && setSelected(i)}
                />
              );
            }
            if (f.geometry?.type === "LineString") {
              const pts = (coords as [number, number][]).map((p) => p.join(",")).join(" ");
              return (
                <polyline
                  key={i}
                  points={pts}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={Math.max(viewBox.w / 300, 0.5)}
                  onClick={() => mode === "select" && setSelected(i)}
                />
              );
            }
            if (f.geometry?.type === "Polygon") {
              const ring = (coords as [number, number][][])[0] ?? [];
              const pts = ring.map((p) => p.join(",")).join(" ");
              return (
                <polygon
                  key={i}
                  points={pts}
                  fill={sel ? "rgba(208,0,0,0.15)" : "rgba(0,102,204,0.15)"}
                  stroke={stroke}
                  onClick={() => mode === "select" && setSelected(i)}
                />
              );
            }
            return null;
          })}
          {draft.length > 0 && (
            <polyline
              points={draft.map((p) => p.join(",")).join(" ")}
              fill="none"
              stroke="#090"
              strokeDasharray="4 2"
            />
          )}
          {draft.map((p, i) => (
            <circle key={`d${i}`} cx={p[0]} cy={p[1]} r={Math.max(viewBox.w / 200, 1)} fill="#090" />
          ))}
          {selected !== null &&
            vertexList(labels.features[selected]).map((v, vi) => (
              <circle
                key={`v${vi}`}
                cx={v[0]}
                cy={v[1]}
                r={Math.max(viewBox.w / 150, 1.5)}
                fill="#fff"
                stroke="#d00"
                strokeWidth={1}
                style={{ cursor: "grab" }}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  dragVertexRef.current = { feature: selected, index: vi };
                }}
              />
            ))}
        </svg>
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
