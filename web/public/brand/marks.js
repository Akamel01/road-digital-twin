// Papyrus living mark — candidates × states.
// Every candidate draws a fixed set of strands, each a polyline with a fixed point
// count, so any two poses morph by pointwise lerp: no morph library needed.
// pose(state, t) -> [[x,y]...][]   (viewBox 0 0 64 64, t in seconds)
// draw.widths gives each strand's stroke width in px (one weight per strand,
// not one weight for the whole mark).

const D = Math.PI / 180;
const clamp01 = x => x < 0 ? 0 : x > 1 ? 1 : x;
const smooth = x => (x = clamp01(x), x * x * (3 - 2 * x));
const inout = x => .5 - .5 * Math.cos(Math.PI * clamp01(x));

// ── geometry helpers ─────────────────────────────────────────────────────────
const lerp = (a, b, m) => [a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m];
function resample(pts, n, a = 0, b = 1) {         // n points evenly by arc length over [a,b]
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const L = cum[cum.length - 1], out = [];
  for (let j = 0, i = 1; j < n; j++) {
    const s = L * (a + (b - a) * j / (n - 1));
    while (i < pts.length - 1 && cum[i] < s) i++;
    const seg = cum[i] - cum[i - 1] || 1;
    out.push(lerp(pts[i - 1], pts[i], clamp01((s - cum[i - 1]) / seg)));
  }
  return out;
}
// SVG path subset (absolute M L Q C, one subpath) -> dense polyline
function dense(d) {
  const tk = d.match(/[MLQC]|-?\d*\.?\d+/g), pts = [];
  let i = 0, cmd, cur;
  const n = () => +tk[i++], P = () => [n(), n()];
  while (i < tk.length) {
    if (/[MLQC]/.test(tk[i])) cmd = tk[i++];
    if (cmd === 'M') { cur = P(); pts.push(cur); cmd = 'L'; continue; }
    const ctl = cmd === 'L' ? [] : cmd === 'Q' ? [P()] : [P(), P()], end = P(), all = [cur, ...ctl, end];
    for (let k = 1; k <= 24; k++) {
      let q = all; const s = k / 24;
      while (q.length > 1) q = q.slice(1).map((p, j) => lerp(q[j], p, s));   // de Casteljau
      pts.push(q[0]);
    }
    cur = end;
  }
  return pts;
}
const N = 64;
const fig = (d, n = N) => resample(dense(d), n);
const circle = (cx, cy, r) => { const k = .5523 * r;
  return `M${cx} ${cy - r} C${cx + k} ${cy - r} ${cx + r} ${cy - k} ${cx + r} ${cy} C${cx + r} ${cy + k} ${cx + k} ${cy + r} ${cx} ${cy + r} C${cx - k} ${cy + r} ${cx - r} ${cy + k} ${cx - r} ${cy} C${cx - r} ${cy - k} ${cx - k} ${cy - r} ${cx} ${cy - r}`; };
const xf = (pts, { rot = 0, ox = 32, oy = 32, dx = 0, dy = 0 } = {}) => {
  const c = Math.cos(rot * D), s = Math.sin(rot * D);
  return pts.map(([x, y]) => [ox + (x - ox) * c - (y - oy) * s + dx, oy + (x - ox) * s + (y - oy) * c + dy]);
};
const line = (x0, y0, x1, y1, n = N) => Array.from({ length: n }, (_, j) => [x0 + (x1 - x0) * j / (n - 1), y0 + (y1 - y0) * j / (n - 1)]);

// ── The working states: Egyptian figures, five strands each, hairline.
const S = {
  boat: [
    'M15 19 C11 14 6 17 9 22 C11 27 14 31 19 34 C26 38 40 38 46 34 C51 31 54 26 56 21 C58 16 53 13 50 18',  // hull, papyrus-bundle ends curled in
    'M32 35 L32 6',                                                                                         // mast
    'M17 11 C27 7.5 37 7.5 47 11 L45 27 C37 25 27 25 19 27 L17 11',                                         // wide sail between two curved yards
    'M18 26 L12 42'],                                                                                       // steering oar
  ibis: [
    'M40 30 C33 25 22 26 18 33 C16 37 13 40 10 43 C16 42 21 41 25 40 C33 39 41 37 42 32 C42 31 41 30 40 30', // body and tail
    'M41 30 C45 26 46 20 43 16 C41 12 44 9 48 10 C52 11 54 17 54 25 C54 28 53 31 52 33',                     // neck, head, long curved beak
    'M28 54 L30.5 39 L33 54',                                                                                 // legs
    circle(47.6, 13.2, .7),                                                                                 // eye
    'M14 54 L50 54'],                                                                                       // ground line
  eye: [
    'M46 25 C38 32 21 32 12 26 C20 18 36 17 46 24 L56 24',                                                  // lids and cosmetic line
    'M12 16 C22 9 40 9 55 14',                                                                              // brow
    'M22 30 C22 35 21 40 20 46',                                                                            // the drop
    'M33 31 C35 39 43 45 48 41 C51 38 49 34 46 35 C44 36 44 39 46 39'],                                    // the spiral, the scroll's own curl
  cat: [
    'M22 56 L23 40 C23 34 22 30 21 27 C19 26 17.5 23 18.5 21 L19.5 17 L20.5 9.5 L25 14.5 L29.5 10 L29.5 18 C30 23 33 26 38 30 C44 35 46 44 44 50 C43 54 40 56 36 56 L22 56', // the seated cat, ears up
    'M26.5 56 L26.5 41',                                                                                    // the far front leg
    'M20 28.5 C22.5 31 25.5 31 28 29'],                                                                     // her collar
  page: [
    'M16 46 L16 18 L48 18 L48 46 L16 46',                                                                   // the open sheet, face on
    'M13 18 C13 14 19 14 19 18 L19 46 C19 50 13 50 13 46 L13 18',                                          // left roll
    'M45 18 C45 14 51 14 51 18 L51 46 C51 50 45 50 45 46 L45 18'],                                         // right roll
};
const F = Object.fromEntries(Object.entries(S).map(([k, v]) => [k, v.map(d => fig(d))]));

function figure(state, t) {
  switch (state) {
    case 'loading': {                     // a papyrus boat rocking on the Nile
      const o = { rot: 3.5 * Math.sin(1.3 * t), ox: 32, oy: 34, dy: .8 * Math.sin(1.3 * t + .6) };
      const water = Array.from({ length: N }, (_, j) => { const x = 6 + 52 * j / (N - 1); return [x, 45 + 1.3 * Math.sin(.32 * x - 2.6 * t)]; });
      const [hull, mast, sail, oar] = F.boat;
      return [xf(hull, o), xf(mast, o), water, xf(sail, o), xf(oar, o)];
    }
    case 'thinking': {                    // the ibis of Thoth, god of wisdom and writing, nodding
      const o = { rot: 6 * Math.sin(1.1 * t) - 2, ox: 41, oy: 30 };
      const [body, head, legs, eye, ground] = F.ibis;
      return [body, xf(head, o), legs, xf(eye, o), ground];
    }
    case 'searching': {                   // the Eye of Horus, its pupil sweeping
      const [lids, brow, drop, spiral] = F.eye, x = 29 + 6 * Math.sin(.95 * t);
      return [lids, brow, fig(circle(x, 24.5, 4.2)), drop, spiral];
    }
    case 'waiting': {                     // Bastet, seated, waiting; her tail flicks now and then
      const [body, leg, collar] = F.cat, p = (t / 3.2) % 1, f = Math.sin(Math.PI * smooth(p / .3)) * (p < .3 ? 1 : 0);
      const tail = fig(`M40 55.5 C46 57 51 55 51 ${50 - 4 * f} C51 ${47 - 5 * f} ${49 + 3 * f} ${45 - 4 * f} ${47 + 4 * f} ${45 - 5 * f}`);
      const blink = .5 + .5 * (1 - (p > .6 && p < .68 ? Math.sin(Math.PI * (p - .6) / .08) : 0));
      return [body, leg, collar, tail, fig(`M21.2 19.6 Q22.6 ${19.6 - 1.1 * blink} 24 19.6 Q22.6 ${19.6 + 1.1 * blink} 21.2 19.6`)];
    }
    case 'reading': {                     // the scroll turned to face you; text appears line by line
      const p = (t / 3.2) % 1, out = 1 - smooth((p - .88) / .12), w1 = smooth(p * 2.4) * out, w2 = smooth(p * 2.4 - 1.1) * out;
      const [pg, l, r] = F.page;
      const f = [pg, l, r, line(22, 27, 22 + 20 * w1, 27), line(22, 35, 22 + 16 * w2, 35)];
      f.w = [W.fig, W.fig, W.fig, W.fig * smooth(w1 * 12), W.fig * smooth(w2 * 12)];   // an unwritten line has no width, so its cap shows no dot
      return f;
    }
    case 'developing': {                  // a pyramid rising course by course
      const p = (t / 5) % 1, h = smooth(p / .62) * (1 - smooth((p - .86) / .14)), top = 52 - 38 * h;
      const face = fig(`M10 52 L${10 + 22 * h} ${top} L${54 - 22 * h} ${top} L54 52`);
      const course = f => { const y = 52 - 38 * f, k = smooth((h - f) * 8), hw = (22 - 22 * f) * k, yy = top + (y - top) * k;
        return line(32 - hw, yy, 32 + hw, yy); };
      return [line(6, 52, 58, 52), face, course(.25), course(.5), course(.75)];
    }
  }
}


// ── The logo: a papyrus head. One generator, five variants between the living plant
// and the Wadj of Egyptian art. Strokes vary in weight: heavy stem, fine rays.
const K = 14;                                       // strands in every pose, so every pose morphs into every other
const W = { stem: 2.4, leaf: 1.2, edge: 1.3, ray: .8, fig: 1.4, hidden: 0 };
// a leaf: a closed lens from its base, pointing at `ang` degrees from vertical
const leaf = (x, y, ang, len, wid) => {
  const a = ang * D, tx = x + Math.sin(a) * len, ty = y - Math.cos(a) * len, mx = (x + tx) / 2, my = (y + ty) / 2, px = Math.cos(a) * wid, py = Math.sin(a) * wid;
  return fig(`M${x} ${y} Q${mx + px} ${my + py} ${tx} ${ty} Q${mx - px} ${my - py} ${x} ${y}`);
};
// extra strands hide by lying along a visible one (a thinner line under a thicker one)
function pad(strands, widths, host) {
  const s = [...strands], w = [...widths], n = strands.length;
  for (let j = 0; s.length < K; j++) { const h = host ?? j % n, a = (Math.floor(j / n) * .37) % .8; s.push(resample(strands[h], N, a, a + .2)); w.push(W.hidden); }
  s.w = w; return s;
}

function head(v, t, sway) {
  const swing = sway ? 1.4 * Math.sin(.9 * t) : 0, o = { rot: swing, ox: 32, oy: 61 };
  const nd = [32, v.node], strands = [line(32, 61, 32, v.node)], w = [W.stem];
  for (const dir of [-1, 1]) { strands.push(leaf(32, v.node + v.leafDrop, dir * v.leafAng, v.leafLen, v.leafWid)); w.push(W.leaf); }
  const tips = [];
  for (let i = 0; i < v.rays; i++) {
    const u = v.rays > 1 ? (i - (v.rays - 1) / 2) / ((v.rays - 1) / 2) : 0, lag = sway ? 1.8 * Math.sin(.9 * t - Math.abs(u) * .9 - .4) : 0;
    let a = (u * v.spread + lag) * D, x = nd[0], y = nd[1];
    const L = v.len * (1 - v.dome * u * u), pts = [[x, y]];
    for (let j = 1; j < 20; j++) { a += u * v.droop * .12 * (j / 19); x += Math.sin(a) * L / 19; y -= Math.cos(a) * L / 19; pts.push([x, y]); }
    tips.push([x, y]);
    strands.push(resample(pts, N)); w.push(W.ray);
  }
  strands.push(resample(dense('M' + tips.map(p => p.join(' ')).join(' L')), N)); w.push(W.edge);     // the rim through the ray tips
  const s = pad(strands, w, 0).map(p => xf(p, o)); s.w = w.concat(Array(K - w.length).fill(W.hidden)); return s;
}

const CROWN = { node: 35, rays: 7, spread: 46, droop: .3, len: 22, dome: .05, leafAng: 44, leafLen: 8, leafWid: 2, leafDrop: 5 };

function crown(state, t) {
  if (state === 'idle') return head(CROWN, t, true);
  if (state === 'done') return head(CROWN, 0, false);
  const f = figure(state, t);
  return pad(f, f.w || Array(f.length).fill(W.fig));
}
export const CANDIDATES = { crown };
export const STATES = ['idle', 'loading', 'thinking', 'reading', 'searching', 'waiting', 'developing', 'done'];
