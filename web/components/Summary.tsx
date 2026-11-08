"use client";

import type { KeyboardEvent } from "react";
import type { Step } from "@/lib/summary";

// Arrows as in the mockup: expand (corners out) and shrink (corners in).
const EXPAND = (
  <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
    <path d="M7 1.5h3.5V5M5 10.5H1.5V7M10.5 1.5L7 5M1.5 10.5L5 7" />
  </svg>
);
const SHRINK = (
  <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
    <path d="M10.5 5H7V1.5M1.5 7H5v3.5M7 5l3.5-3.5M5 7l-3.5 3.5" />
  </svg>
);

interface Props {
  scope: string; // "area" or the facility id
  steps: Step[];
  expanded: boolean;
  onExpanded: (on: boolean) => void;
}

/** Compact: one row per step with its headline figure. Expanded: each step with its text and all figures. */
export default function Summary({ scope, steps, expanded, onExpanded }: Props) {
  if (expanded) {
    return (
      <section className="sum glass max" aria-label="Pipeline summary">
        <div className="hd">
          <div className="over">Pipeline · {scope}</div>
          <button
            type="button"
            className="sumbtn"
            onClick={() => onExpanded(false)}
            aria-label="Shrink pipeline summary"
          >
            {SHRINK}
          </button>
        </div>
        <ol>
          {steps.map((s, i) => (
            <li key={s.title}>
              <div className="t">
                <i>{i + 1}</i>
                {s.title}
              </div>
              <p>{s.text}</p>
              <div className="figs num">
                {s.figs.map((f, k) => (
                  <div key={k}>
                    <b>{f.value}</b>
                    <span>{f.label}</span>
                  </div>
                ))}
              </div>
            </li>
          ))}
        </ol>
      </section>
    );
  }

  // The card itself is the control (role=button). Enter and Space expand it, as the mockup does.
  function onKey(e: KeyboardEvent<HTMLElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onExpanded(true);
    }
  }

  return (
    <section
      className="sum glass"
      role="button"
      tabIndex={0}
      aria-expanded={false}
      aria-label="Expand pipeline summary"
      onClick={() => onExpanded(true)}
      onKeyDown={onKey}
    >
      <div className="hd">
        <div className="over">Pipeline · {scope}</div>
        <span className="sumbtn" aria-hidden="true">
          {EXPAND}
        </span>
      </div>
      <ol>
        {steps.map((s, i) => (
          <li key={s.title}>
            <i>{i + 1}</i>
            <span>{s.title}</span>
            <b className="num">
              {s.figs[0].value}
              <small>{s.figs[0].label}</small>
            </b>
          </li>
        ))}
      </ol>
    </section>
  );
}
