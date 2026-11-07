# Stage 7: Critic review

Target: `decisions-bundle.md`, lines 1–179. Standard: EGM `feature-spec-standard.md`. Reviewers: egm-design, egm-structural, egm-style.

## egm-structural — Verdict: FAIL against the feature-spec standard

This is expected, because the bundle is a set of decision records and no spec exists yet.

1. **Blocker: no Alternatives Considered section.** Deferrals don't count as alternatives: Lyft, the choice of reconstruction method, copying versus depending, why #43 was replaced, fusion, and the two EVT formulations.
2. **Blocker: no Risks & Mitigations section.** Candidates:
   - the 5-day v1;
   - the SSD still pending;
   - missing the 20 cm target;
   - the public UI and the personal access tokens;
   - BADAS being gated;
   - the p99 target;
   - the nuScenes NC/SA terms.
3. **Major: no Problem Statement.** "Why" lists benefits, but never says what today's audits cost or how screening fails.
4. **Major: no Goals & Non-Goals section.** Non-goals are scattered through the decisions:
   - static only;
   - no 3D viewer;
   - cameras-only in v1.1;
   - read-only UI;
   - signals in v2.
5. **Major: no Proposed Architecture section.** No component or data-flow view runs from source to twin to drawings, UI and AuditorAI.
6. **Major: Round 4 and Round 5 headings break the hierarchy.** They are H3 siblings of Decisions, yet continue its numbering. Round 3 has no heading.
7. **Major: broken cross-reference** between line 91 and the open questions.
8. **Major: relative links copied from the README** (`docs/decisions/`, `LICENSE`) break at the bundle's location.
9. **Nit:** the decision records have uneven templates (Context and Consequences appear only in 0001).
10. **Nit:** the date and provenance lines use inconsistent formats.
11. **Nit:** there is no blank line after the headings in the open questions.
12. **Nit:** the README section heading doesn't match its siblings.

Suggested fix: write the design spec with all five required sections, using these records as its sources.

## egm-style — no Blockers

1. **Major: claims about things not yet built, written in the present tense.**
   - "The twin is georeferenced and measurable" (line 18).
   - "Every finding traces…" (line 31).
   - "Outputs serve as evidence" (line 151).

   Rewrite as design goals ("will", "intended to").
2. **Major: "risk measures that run in real time" (line 19) has no conditions.** Quote the 0003 figures and say they cover EVT scoring only.
3. **Major: "open-source BADAS" (line 20)** overstates it. Say "Apache-2.0, gated on Hugging Face".
4. **Major: unsupported claims about current practice.**
   - Screening steps "exist only to ration audit time" (line 28).
   - Spending follows complaints (line 29).

   Cite a source, or calibrate the wording.
5. **Major: "Most of the data comes from AVs" (line 62)** is an unverified share. Say "the v1 data (nuScenes) comes from AV sensor rigs".
6. **Major: contradiction.** Line 91 conflicts with lines 120 and 170.
7. **Major: the accuracy target gives no statistic** (mean, RMSE or P95?), and curbs have no stated ground truth (line 99).
8. **Major: superseded items are not marked.** Item 9 (one site, not many), item 11 (cameras-only moved to v1.1) and item 14 (UI settled in item 18).
9. **Major: internal shorthand is undefined.** Grilling, wayfinder, opencode, the box, job-hunt #43, UI-12, the Crown living-mark, ODD, MAIS3+, WOMD, inD/rounD, GSN, and Mission Control (drone-survey). Add a glossary.
10. **Nits:**
    - "first two stages" sits next to a three-item list;
    - filler words: "actually", "real work", "complete";
    - the slogan "products stand on evidence and engineering";
    - "builds and renders run" is hard to parse;
    - "agreed with all recommendations" doesn't record what was agreed;
    - "Severity is triggered when P(crash) ≥ 1e-3" gives no time window.

## egm-design — Verdict: FAIL (decision log, not a spec)

1. **Blocker: the Alternatives Rule is not met.** The "agreed recommendations" are never recorded, nothing was rejected with a reason, and there are no links to the planning records.
2. **Blocker: no Risks & Limits section.**
3. **Major: the v1 schedule can't be done as written.** It has 5 days, the reconstruction method is still open, masking is unresolved, and the budget is unclear. Name a simple baseline (accumulated lidar with ego poses, no 3DGS), estimate effort per deliverable, and define a fallback scope.
4. **Major: the accuracy check doesn't match what nuScenes provides.**
   - The map expansion is 2D, with no elevation and no curb layer (curbs would come from the drivable_area or walkway boundary).
   - The 20 cm target has no basis, and ego-pose and map error are not in the budget.
   - **Check:** many nuScenes ego_pose records reportedly have z = 0. If so, stacked clouds come out flat, and the profile must come from local ground fitting.
5. **Major: sight distance may not be feasible on the chosen data.**
   - Boston and Singapore are mostly flat, so a mini scene may contain no crest curve.
   - Each scene is a single pass of about 20 s and a few hundred metres, with 32-beam lidar range limits and occlusion.
   - Masking parked cars can overstate sight distance.
   - No method is named (AASHTO or TAC, eye and object heights).

   Confirm a suitable site exists, and report "indeterminate" when geometry falls out of coverage.
6. **Major: licensing and hosting.**
   - Derived point clouds and DXF/PDF files carry nuScenes' NC/SA terms, separate from the code's Apache-2.0 licence.
   - Is papyrus-ai.net a commercial context?
   - Where are the derived files stored? Are they committed?
   - The terms for Nexar clips are not stated.
7. **Major: static hosting limits.** Cloudflare Pages caps a file at about 25 MiB, and one scene's cloud can exceed that. Specify the web format (COPC, Potree, 3D Tiles), decimation, and size budgets.
8. **Major: there is no architecture or interface.**
   - The AuditorAI contract and its schema are undefined.
   - No component or data-flow view.
   - AuditorAI integration isn't in v1, yet it is "the first consumer". State it as a v1 non-goal explicitly.
9. **Major: risk-engine assumptions.**
   - MCMC is not real-time; name the inference method.
   - Pair scoring is O(n²) with no bound on n.
   - The total-risk formula assumes pairs are independent.
   - BADAS covers ego video only.
   - The 1e-3 threshold has no basis.
10. **Major: goals and non-goals are scattered and contradict each other.** Line 91 vs the open questions, line 109 vs 126, the README source order, and line 112 vs 127–134.
11. **Nit:** box hardware isn't stated, and does v1 need a GPU at all?
12. **Nit:** how the Librarian CLI stores and expires tokens is left to the Librarian ticket.
13. **Nit:** unlinked references, broken relative links, and the scope of the "AI" naming rule.
14. **Nit:** no measurable acceptance criteria per v1 deliverable.
