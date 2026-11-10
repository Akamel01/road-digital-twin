# Auto-publish twin.papyrus-ai.net

A run is published only when `twin eval` gives GO on every gate **and** it beats the published run: no check has less margin than before, and at least one has more (margin = room to the threshold in `twin/gates.yaml`). The first run only needs GO. Operator decision 2026-11-09, ADR 0005.

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

## Box needs Node

The box had no Node when this was written. Install Node 22+ (without sudo, for example a tarball under `~/.local`) before the first real publish.
