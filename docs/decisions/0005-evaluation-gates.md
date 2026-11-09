# 0005 — Evaluation gates, GPU use and the box as a processing node

Date: 2026-11-09. Status: agreed by the operator, 2026-11-09.

This work focuses on quality before scale: one study area (the Seaport corridor, #14 and #140), mastered before the city. These rules decide when a run or a method change is good enough.

## Gates

Every threshold lives in one versioned gates file. Changing a threshold needs the operator's approval.

| # | Gate | Go when |
|---|---|---|
| G1 | Determinism | Rerunning with the same inputs, code and params gives identical metrics |
| G2 | Cross-drive ground agreement after registration | P95 ≤ 0.05 m |
| G3 | Ground height QA (`z_disagreement_p95_m`) | ≤ 0.10 m (existing) |
| G4 | Leave-one-drive-out repeatability, P95 | markings ≤ 0.10 m, curbs ≤ 0.15 m |
| G5 | Accuracy against the HD map, P95 | markings ≤ 0.30 m, crosswalks ≤ 0.50 m, curbs ≤ 0.50 m (map-conditioned); marking coverage ≥ 0.70 |
| G6 | Runtime | area run ≤ 30 min on the box |

- **Publish gate.** A twin is published only when every gate is go. A gate that can't be computed yet (for example G4 before #143) is reported "not measured". It does not count as go.
- **Method-change gate.** A pull request that changes measurements is run on the study area and compared with the baseline run. It is a no-go when a gate fails, or when any metric gets worse by more than the noise tolerance (0.02 m on P50 and P95; spec, repeatability). A go still waits for the operator's line-by-line review. Gates do not merge method changes on their own.

## GPU

Twin jobs may use all free GPU memory on the box. The GPU is shared with Librarian production (ollama), so every GPU path must:
- catch out-of-memory errors;
- fall back to the CPU and produce the same result within tolerance;
- never stop or restart production containers.

The first target is the colour stage (z-buffer projection), which takes 126 s of a 175 s single-drive run.

## Keeping the box busy

Between code changes, the box runs parameter sweeps on the study area, scored by the gates. The best passing parameter set is proposed as the new baseline, and the operator approves it. City-wide runs wait until the study area passes every gate.
