# Papyrus brand identity — the Crown and living-mark states

The Crown logo and its living-mark states are the identity for **every** Papyrus project, including this website and all the others.

## Identity rule (verbatim)

> Every Papyrus project shows these states. Use the nearest existing state when nothing fits, and never invent a new animation without the operator's approval.

- Whenever an icon is idle, it shows the idle animation. When something is loading, it shows the loading animation, and so on for each state.
- When a user waits on a process that fits none of the states, use the **most relevant existing** state.
- **Never create a new animation** without the operator's approval.
- These logos and animations live in one shared library, so every new project picks up the identity automatically.

## States

| State | Meaning | Figure |
|---|---|---|
| idle | ready, nothing running | the Crown logo, swaying slightly |
| loading | fetching, length unknown | a papyrus boat rocking on the Nile |
| thinking | the model is reasoning | the ibis of Thoth, nodding |
| reading | taking in a document | an open scroll, text appearing line by line |
| searching | looking across sources | the Eye of Horus, its pupil sweeping |
| waiting | blocked on the person | Bastet, the seated cat, blinking, tail flicking |
| developing | building an answer | a pyramid rising course by course |
| done | finished | the Crown logo at rest |

Stroke is `currentColor`, `vector-effect: non-scaling-stroke`. Widths come from each strand's `.w` (0 means hidden).

## Embedding

### ES module

```js
import { mount, CANDIDATES, STATES } from 'https://papyrus-ai.net/brand/living-mark.js';
// or pinned: https://cdn.jsdelivr.net/gh/Akamel01/papyrus-home@brand-v1.0.0/public/brand/living-mark.js
const m = mount(svg, 'crown', 'idle');
m.setState('thinking');
m.destroy();
```

`mount(svg, candidate, state)` returns `{ setState(name), destroy() }`. The only candidate is `crown`.

### React

```tsx
import LivingMark from '@/components/LivingMark';
<LivingMark state="loading" size={24} />
```

### Static SVG

Use files in `svg/`: `svg/crown-<state>.svg`. Favicon: `crown-favicon.svg`.

## Mapping table — common processes to state

| Process | State |
|---|---|
| sync | loading |
| upload | loading |
| download | loading |
| deploy | developing |
| sign-in | loading |
| payment | loading |
| export | developing |
| indexing | searching |
| build | developing |
| fetching data | loading |
| reasoning / generating | thinking |
| reading a document | reading |
| searching sources | searching |
| waiting for user input | waiting |
| idle / ready | idle |
| finished / success | done |

## Versioning

`VERSION` (currently `1.0.0`) is mirrored in the header comment of `living-mark.js`. Pin to a git tag `brand-vX.Y.Z` via jsDelivr for stability, or use the site's `/brand/` URL for latest.
