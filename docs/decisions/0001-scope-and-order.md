# 0001 — Scope, order and the two stages

Date: 2026-11-07. Decided by the operator in planning sessions (2026-11-02 to 2026-11-07).

## Context

The project started as a real-time crash-risk system for autonomous vehicles. It replaces the earlier "AV Safety Evaluation Benchmark" idea (job-hunt #43, `docs/research/benchmark-spike.md`). On 2026-11-06 the operator placed it inside a wider road-safety pipeline: digital twin, then collision risk, then safety audit (AuditorAI), with Librarian as the evidence base.

## Decisions

1. **Name and licence.** The repo is `road-digital-twin`, public from day one, Apache-2.0.
2. **The twin comes first.** The real work begins with the digital twin. The repo holds a skeleton for the whole project, so that later stages plug in without restructuring.
3. **The audit is the first consumer.** The twin's first use is road safety audits of existing infrastructure, through AuditorAI. The AV safety case, readiness criteria and the ODD come after the risk engine.
4. **Scope wording.** Most of the data comes from AVs, but the project is never described as AV-only. The case for it is network-wide, complete safety audits.
5. **Branding.** Definitions and headline statements don't use the word "AI". The products stand on evidence and engineering.
6. **Growth.** The pipeline grows in two directions:
   - horizontally: new road types, jurisdictions and sensor setups;
   - vertically: new stages and products.

   The layout separates inputs (one adapter per source), stages, and outputs (one per consumer).
7. **Librarian is the retrieval engine** for development. Papers, standards and similar work are added to the operator's Librarian library and queried from there. The repo never stores them.

## Consequences

- Grilling continues for the later phases (risk, safety case) while the twin builds and renders run.
- Phase planning follows a set protocol: grill until the phase is settled; the operator triggers a wayfinder session; then triage and to-tickets; then delegation to opencode.
