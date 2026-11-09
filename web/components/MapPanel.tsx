"use client";

import { useState } from "react";
import { ERR_COL } from "@/lib/mapdata";
import { PHONE, useMedia } from "@/lib/media";

export type Layer = "lidar" | "ortho" | "markings" | "crosswalks" | "curbs";
export type Analysis = "accuracy" | "safety" | "coverage";
export type Layers = Record<Layer, boolean>;

const LAYERS: [Layer, string, string][] = [
  ["lidar", "Lidar", "#9aa3a7"],
  ["ortho", "Orthoimage", "#8a9a6a"],
  ["markings", "Markings", "var(--feat-mark)"],
  ["crosswalks", "Crosswalks", "var(--feat-cross)"],
  ["curbs", "Curbs", "var(--feat-curb)"],
];

const ANALYSES: [Analysis, string, string][] = [
  ["accuracy", "Accuracy", "vs HD map"],
  ["safety", "Safety check", "sight lines"],
  ["coverage", "Coverage", "seen / unseen"],
];

const LEGEND: Record<Analysis, [string, string][]> = {
  accuracy: [
    [ERR_COL.good, "≤ 0.20 m"],
    [ERR_COL.fair, "≤ 0.40 m"],
    [ERR_COL.poor, "> 0.40 m"],
  ],
  safety: [
    ["var(--sight)", "clear"],
    ["var(--danger)", "blocked"],
    ["rgb(255 255 255 / .6)", "indeterminate"],
  ],
  coverage: [
    ["#9CC7A4", "observed"],
    ["#E0704F", "unobserved"],
  ],
};

function Chevron() {
  return (
    <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M3 4.5l3 3 3-3" />
    </svg>
  );
}

interface Props {
  layers: Layers;
  onLayer: (k: Layer) => void;
  analysis: Analysis | null;
  onAnalysis: (a: Analysis) => void;
  note?: string;
}

export default function MapPanel({ layers, onLayer, analysis, onAnalysis, note }: Props) {
  const [min, setMin] = useState(false);
  // Phone: the panel is a "Layers" pill on the map; it opens as a popover. Starts closed.
  const phone = useMedia(PHONE);
  const [open, setOpen] = useState(false);
  const collapsed = phone ? !open : min;
  return (
    <div className={`mapctl glass${collapsed ? " min" : ""}`}>
      <button
        type="button"
        className="hd"
        aria-expanded={!collapsed}
        onClick={() => (phone ? setOpen((v) => !v) : setMin((v) => !v))}
      >
        <span className="over">{phone ? "Layers" : "Map"}</span>
        <Chevron />
      </button>
      <div className="body">
        <div className="grid">
          {LAYERS.map(([k, name, color]) => (
            <button
              type="button"
              key={k}
              className="tg"
              aria-pressed={layers[k]}
              onClick={() => onLayer(k)}
            >
              <span className="sw" style={{ background: color }} />
              {name}
            </button>
          ))}
        </div>
        <div className="over">Analysis</div>
        <div className="seg">
          {ANALYSES.map(([k, name, sub]) => (
            <button
              type="button"
              key={k}
              className="an"
              aria-pressed={analysis === k}
              onClick={() => onAnalysis(k)}
            >
              {name}
              <small>{sub}</small>
            </button>
          ))}
        </div>
        {analysis && (
          <>
            <div className="legend">
              {LEGEND[analysis].map(([color, label]) => (
                <span key={label}>
                  <i style={{ background: color }} />
                  {label}
                </span>
              ))}
            </div>
            {note && <p className="note">{note}</p>}
          </>
        )}
      </div>
    </div>
  );
}
