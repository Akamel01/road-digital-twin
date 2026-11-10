// Papyrus brand identity — living mark. VERSION: 1.0.0 (see ./VERSION)
import { CANDIDATES } from './marks.js';

// cubic-bezier(.32,.72,0,1), Hairline's discrete-change clock, solved by bisection.
const bez = (p1x, p1y, p2x, p2y) => x => {
  const c = (a, b, t) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3;
  let lo = 0, hi = 1, t = x;
  for (let i = 0; i < 20; i++) { t = (lo + hi) / 2; c(p1x, p2x, t) < x ? lo = t : hi = t; }
  return c(p1y, p2y, t);
};
const ease = bez(.32, .72, 0, 1), MORPH = .7;
// Pair each strand of pose A with the nearest strand of pose B (visible with visible), reversing
// a strand when that is closer, so a morph flows part to part instead of crossing the mark.
export function match(A, B) {
  const c = s => s.reduce((p, q) => [p[0] + q[0] / s.length, p[1] + q[1] / s.length], [0, 0]);
  const d = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
  const hid = (P, i) => (P.w?.[i] ?? 1.5) <= .7;
  const ca = A.map(c), cb = B.map(c), pairs = [];
  A.forEach((_, i) => B.forEach((_, j) => pairs.push([d(ca[i], cb[j]) + (hid(A, i) !== hid(B, j) ? 40 : 0), i, j])));
  pairs.sort((x, y) => x[0] - y[0]);
  const perm = [], ua = new Set(), ub = new Set();
  for (const [, i, j] of pairs) if (!ua.has(i) && !ub.has(j)) { perm[i] = j; ua.add(i); ub.add(j); }
  const rev = A.map((a, i) => { const b = B[perm[i]]; return d(a[0], b[0]) + d(a.at(-1), b.at(-1)) > d(a[0], b.at(-1)) + d(a.at(-1), b[0]); });
  return (b) => { const out = A.map((_, i) => rev[i] ? [...b[perm[i]]].reverse() : b[perm[i]]); if (b.w) out.w = A.map((_, i) => b.w[perm[i]]); return out; };
}
// widths: a line that disappears thins out in the first half; one that appears grows in the second
export const blendW = (a, b, m) => a.map((x, i) => { const y = b[i], k = !y ? Math.min(1, 2 * m) : !x ? Math.max(0, 2 * m - 1) : m; return x + (y - x) * k; });
const REST_T = { idle: 0, loading: .4, thinking: 1.4, reading: 1.2, searching: .6, waiting: 0, developing: 1.2, done: 0 };

// mount(svg, candidate) -> { setState(name), destroy() }
export function mount(svg, candidate = 'crown', state = 'idle') {
  const draw = CANDIDATES[candidate];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const still = s => reduce.matches ? () => draw(s, REST_T[s]) : t => draw(s, t);
  let pose = still(state), t = 0, last = 0, raf = 0, visible = true, prevD = '';
  const paths = draw(state, 0).map((_, i) => {
    const p = svg.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'path'));
    const a = { fill: 'none', stroke: 'currentColor', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'vector-effect': 'non-scaling-stroke' };
    for (const k in a) p.setAttribute(k, a[k]);
    return p;
  });

  const render = () => {
    const strands = pose(t), d = strands.map(p => 'M' + p.map(([x, y]) => x.toFixed(2) + ' ' + y.toFixed(2)).join('L'));
    const key = d.join();
    if (key !== prevD) { d.forEach((s, i) => paths[i].setAttribute('d', s)); prevD = key; }
    const w = strands.w || [];
    w.forEach((v, i) => { const x = v.toFixed(2); if (paths[i].getAttribute('stroke-width') !== x) paths[i].setAttribute('stroke-width', x); });
  };
  const frame = now => {
    t += Math.min(now - last, 50) / 1000; last = now; render();
    raf = visible && !reduce.matches ? requestAnimationFrame(frame) : 0;
  };
  const wake = () => { if (!raf && visible && !reduce.matches) { last = performance.now(); raf = requestAnimationFrame(frame); } };
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; wake(); });
  io.observe(svg);
  render(); wake();

  return {
    setState(next) {
      if (next === state) return;
      state = next;
      const from = pose, to = still(next);
      if (reduce.matches) { pose = to; render(); return; }
      const t0 = t, map = match(from(t), to(t));
      pose = tt => {
        const m = ease(Math.min((tt - t0) / MORPH, 1));
        if (m >= 1) { pose = to; return to(tt); }
        const a = from(tt), b = map(to(tt));
        const out = a.map((s, i) => s.map(([x, y], j) => [x + (b[i][j][0] - x) * m, y + (b[i][j][1] - y) * m]));
        if (a.w && b.w) out.w = blendW(a.w, b.w, m);
        return out;
      };
      wake();
    },
    destroy() { cancelAnimationFrame(raf); io.disconnect(); paths.forEach(p => p.remove()); },
  };
}

export { CANDIDATES, STATES } from './marks.js';
