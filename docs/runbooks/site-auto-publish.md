# Auto-publish twin.papyrus-ai.net

The site publishes a run when it is not worse than the published one: no fewer gate checks pass, and its margin sum (room to the thresholds in `twin/gates.yaml`) is at least the published sum minus 0.01 (`TIE_MARGIN`, rebuild noise). Ties publish, so merged code reaches the site. Operator, 2026-11-16 (it was "strictly better", ADR 0005). The first run always publishes.

## Queue it

After an eval: `{"type": "publish", "run_id": "<run>"}`, or add `"publish": true` to a `run`/`rerun`/`eval` job to publish when its eval is GO. Add `"dry_run": true` to build without deploying.

A publish job builds the showcase from the run (`twin publish`), writes `status.json` (verdict, time) which the site shows in the top bar, builds `web/` (needs Node and npm) and runs `npx -y wrangler@4.151.2 deploy` from `web/`. It then appends the run to `<store>/published/history.json`. A skip (NO-GO, not better) finishes the job with `publish_result: skipped: <reason>`.

By hand: `uv run twin site publish <run> [--dry-run] --store /data/twin-dev`.

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
