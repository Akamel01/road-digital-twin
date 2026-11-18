# Auto-publish twin.papyrus-ai.net

A run publishes when the per-element score against the audit labels shows no geometry element worse than the published run beyond its noise; ties publish; the first run publishes. No fewer HD-map gate checks pass (gate veto kept). Attributes (curb height has no producer; ramp slopes are noisy) are reported but do not block publishing. `TIE_MARGIN` moves to the legacy fallback (margin_sum ± 0.01). Operator, 2026-11-16 (it was "strictly better", ADR 0005). The first run publishes.

## Queue itAfter an eval: `{"type": "publish", "run_id": "<run>"}`, or add `"publish": true` to a `run`/`rerun`/`eval` job to publish when its eval is GO. Add `"dry_run": true` to build without deploying.

A publish job builds the showcase from the run (`twin publish`), writes `status.json` (verdict, time) which the site shows in the top bar, builds `web/` (needs Node and npm) and runs `npx -y wrangler@4.151.2 deploy` from `web/`. It then appends the run to `<store>/published/history.json`. A skip (NO-GO, not better) finishes the job with `publish_result: skipped: <reason>`.

By hand: `uv run twin site publish <run> [--dry-run] --store /data/twin-dev`.

## Score against the audit set

`uv run twin score <run> --sites audit --store /data/twin-dev` (exit 0 publish, 1 would skip, 2 cannot score / not comparable). The CLI always compares against the published baseline (no flag); writes `<run-or-area>/score.json` (not a public asset; run scores are readable through the control API, area scores are filesystem/CLI only). `twin site publish` runs the scorer on every attempt that needs it and records the document under `"score"` in `published/history.json`.

Score.json key table: top-level `schema, method, target, target_kind, sites, elements, marking_types, attributes, compare, noise, qa`; entry keys `basis, n_extracted, n_labels, precision, recall, p95_m, measured, reason`; compare keys `baseline, comparable, reason, publish, elements`.

Noise (provisional until #299; flat, not scaled by label count — with few labels the figures are coarse):

| metric | noise |
|---|---|
| p95_m | 0.02 m |
| precision | 0.01 |
| recall | 0.01 |

Status vocabulary: `improved | tie | worse | lost | new | not measured | not compared`; only `worse`/`lost` skip.

Curb height: comparator exists, report-only; run curbs carry no `height_m` (curb height is an open question in #293; no producer exists in `twin/` today), so `n_compared: 0` with a reason; ramp slopes and gutter step are compared today. Intervals are not expressible in the label schema (#301).

Dev role: `--sites dev` never decides publishing (role mismatch is incomparable, exit 0 with a note).

Fallback: no labels, a history entry with `"score": null` **or no `"score"` key** (the legacy signal), or a changed site list / version / `label_hash` (including partial coverage: a run covering fewer sites) → old `margin_sum ± 0.01` comparison with a stderr note. `twin score` treats a published entry without a score as no baseline (exit 0, `reason: "no baseline"`). More gate checks no longer override a per-element regression; per-site baseline view is #303; autopilot does not consume `score.json`, its `publish_result` strings are unchanged.

## Token (operator, once)

Create a Cloudflare API token with **Workers Scripts: Edit** for account `1bde08c94022d2f83395dafe200028fa`, limited to the `road-digital-twin` Worker. Also needed for the custom domain route: Workers Routes/Custom Domains edit on the papyrus-ai.net zone if wrangler asks for it. Store it on the box, never in git or chat:

```
mkdir -p ~/.config/twin && chmod 700 ~/.config/twin
umask 077 && cat > ~/.config/twin/cf-token     # paste the token, Ctrl-D
chmod 600 ~/.config/twin/cf-token
```

The code reads it only inside the deploy command (`CLOUDFLARE_API_TOKEN` in the child process environment) and never prints it. Another path: `TWIN_CF_TOKEN_FILE`. Without the file the job fails with "no Cloudflare token at ...".

## Roll back

```
uv run twin site history  --store /data/twin-dev      # what was published, oldest first
uv run twin site rollback --store /data/twin-dev      # republish the run before the current one
```

Rollback needs that earlier run to still be in the store. `--dry-run` builds only.

## Node on the box

Node 22 lives in `~/.local/node` (not on the default PATH). `twin/site.py` puts `~/.local/node/bin` first on PATH for the build and deploy commands when that directory exists; set `TWIN_NODE_BIN` to use another directory.
