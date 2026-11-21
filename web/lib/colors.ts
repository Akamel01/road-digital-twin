export type RGBA = [number, number, number, number];

export interface Tokens {
  mark: RGBA;
  cross: RGBA;
  curb: RGBA;
  sight: RGBA;
  fac: RGBA;
  danger: RGBA;
  white: RGBA;
}

function rgb(hex: string): [number, number, number] {
  const h = hex.trim().replace(/^#/, "");
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

export const FALLBACK_TOKENS: Tokens = {
  mark: [...rgb("#f2f2ee"), 255],
  cross: [...rgb("#7fc4e8"), 255],
  curb: [...rgb("#e0a94f"), 255],
  sight: [...rgb("#c9b6f2"), 255],
  fac: [...rgb("#f2d27a"), 255],
  danger: [...rgb("#e0704f"), 255],
  white: [...rgb("#ffffff"), 255],
};

export function hexToRgba(hex: string, alpha: number = 255): RGBA {
  const [r, g, b] = rgb(hex);
  return [r, g, b, alpha];
}

export function withAlpha(c: RGBA, a: number): RGBA {
  return [c[0], c[1], c[2], a];
}

const TOKEN_VARS: Record<keyof Tokens, string> = {
  mark: "--feat-mark",
  cross: "--feat-cross",
  curb: "--feat-curb",
  sight: "--sight",
  fac: "--fac",
  danger: "--danger",
  white: "--on-glass",
};

export function readTokens(root?: HTMLElement): Tokens {
  const el =
    root ?? (typeof document !== "undefined" ? (document.documentElement as HTMLElement) : null);
  const out = { ...FALLBACK_TOKENS } as Tokens;
  if (!el || typeof getComputedStyle === "undefined") return out;
  const style = getComputedStyle(el);
  (Object.keys(TOKEN_VARS) as (keyof Tokens)[]).forEach((key) => {
    const v = style.getPropertyValue(TOKEN_VARS[key]).trim();
    if (v) out[key] = hexToRgba(v);
  });
  return out;
}
