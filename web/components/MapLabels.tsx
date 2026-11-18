export interface LabelItem {
  id: string;
  x: number;
  y: number;
  text: string;
}

export default function MapLabels({
  items,
  k,
  tx,
  ty,
}: {
  items: LabelItem[];
  k: number;
  tx: number;
  ty: number;
}) {
  if (!Number.isFinite(k) || !Number.isFinite(tx) || !Number.isFinite(ty)) return null;
  return (
    <svg className="labels" aria-hidden="true">
      <g transform={`translate(${tx}px,${ty}px) scale(${k})`}>
        {items.map((it) => (
          <text
            key={it.id}
            className="flabel"
            x={it.x}
            y={it.y}
            fontSize={12 / k}
          >
            {it.text}
          </text>
        ))}
      </g>
    </svg>
  );
}
