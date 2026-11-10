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
| G5 | Accuracy against the HD map, matched precision (P95 of samples within the match radius) | markings ≤ 0.30 m, crosswalks ≤ 0.50 m, curbs ≤ 0.50 m (map-conditioned); false-positive rate ≤ 0.10 and coverage ≥ 0.70 per element |
| G6 | Runtime | area run ≤ 30 min on the box |

- **2026-11-09 (gates version 2):** G5 now means matched precision. Its P95 counts only samples within the match radius (1 m) of the reference. False positives and coverage are gated separately, so a missed or invented feature no longer hides in the P95 (#158, #159).
- **2026-11-10 amendment (#177):** G2 and G3 are measured on ground-class points only. Ground means lidarseg driveable_surface, sidewalk and terrain where a sweep has labels (keyframes), and the ground stage's RANSAC ground elsewhere. Before, G3 compared every point within 0.5 m of the ground and G2 took the 10th percentile of all points per cell, so walls, kerbs, vegetation and roofs counted as height disagreement (scene-0757 G3 0.58 m, of which only about 0.11 m was ground). Metric names and thresholds are unchanged. Known limit: a sweep offset so far that the RANSAC split calls it non-ground is invisible to the ground-only G3; the per-sweep height fit (ADR 0006 Q7) reports its own residuals.
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
