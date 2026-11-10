"use client";

import { useEffect, useRef } from "react";

// Papyrus living mark (papyrus-home public/brand, copied to /brand). Source of truth: papyrus-home#37.
// Loaded at run time from the same origin so the bundler does not touch the plain-JS library.
export type MarkState = "idle" | "loading" | "thinking" | "reading" | "searching" | "waiting" | "developing" | "done";

interface Mounted {
  setState: (s: string) => void;
  destroy: () => void;
}

export default function LivingMark({ state, size = 32 }: { state: MarkState; size?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const mark = useRef<Mounted | null>(null);
  const want = useRef(state);
  want.current = state;

  useEffect(() => {
    let dead = false;
    const svg = ref.current;
    if (!svg) return;
    import(/* webpackIgnore: true */ "/brand/living-mark.js").then((m: { mount: (s: SVGSVGElement, c: string, st: string) => Mounted }) => {
      if (dead) return;
      mark.current = m.mount(svg, "crown", want.current);
    });
    return () => {
      dead = true;
      mark.current?.destroy();
      mark.current = null;
    };
  }, []);

  useEffect(() => {
    mark.current?.setState(state);
  }, [state]);

  return (
    <svg ref={ref} width={size} height={size} viewBox="0 0 64 64" fill="none" stroke="currentColor" aria-hidden="true" />
  );
}
