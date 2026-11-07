# 0003 — Collision-risk engine (later phase): agreed direction

Date: 2026-11-07. Operator agreed with grilling rounds 1 and 2. The engine is built after the digital twin.

1. **Two measures, side by side.**
   - **Event-based:** BADAS-Open (Hugging Face `nexar-ai/BADAS-Open`, Apache-2.0, gated; input is ego dashcam video).
   - **Accumulated:** dynamic Bayesian hierarchical EVT on traffic conflicts.

   Both are reported, plus an analysis of where they agree and disagree. Fusing them is a later decision.
2. **Who specifies the EVT model.** Claude drafts two cited formulations: a hierarchy of site and road-user-pair class, and dynamic parameters through a state-space model with online updates. The operator chooses one and reviews it line by line.
3. **How it differs from the operator's PhD.** The PhD estimated risk per site and per interval, offline. This engine estimates risk per frame and per road-user pair, uses only past data (causal), updates online, adds severity and an event layer, and its outputs serve as evidence for safety claims.
4. **"Now" means a short horizon.** Indicators are predicted over a short horizon (3 s proposed), and EVT supplies the tail probability.
5. **Severity.** Predicted delta-v is mapped to MAIS3+ through published curves, with separate pedestrian and cyclist impact-speed curves. Severity is triggered when P(crash) ≥ 1e-3; the operator tunes this threshold.
6. **Every road user.** Pairwise risk, plus each user's total risk: 1 − Π(1 − p_pair).
7. **Input contract.** A canonical dynamic-scene schema v0 (road users, kinematics, class, optional signal state and compliance flags). Dataset adapters write it now; Mission Control writes it later.
8. **Signals and compliance** come in v2, through WOMD or the synthetic sim. The field exists from schema v0.
9. **Modes.** Streaming per frame (causal, at least 10 Hz, p99 under 100 ms for EVT scoring) and batch over many logs.
10. **Data.** nuScenes, plus a synthetic 2D sim (ground truth for calibration), plus Nexar collision clips (real crashes; BADAS side only). Later: inD/rounD and WOMD. Lyft and similar datasets stay under consideration.
11. **Demo.** README with a GIF, plus a static replay on papyrus-ai.net inside the pipeline section, marked "coming soon".
12. **Budget.** About 8 operator hours a week.
