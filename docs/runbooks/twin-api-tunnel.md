# Runbook: twin tunnel and Cloudflare Access for the control API

Scope: the `twin` Cloudflare Tunnel that carries `twin-api.papyrus-ai.net` to the control API on the box, and the Cloudflare Access application that guards the write routes `/api/w/*`. Spec: `docs/design/twin-v1-spec.md`, sections 3, 4, 6 and 8. Decision: `docs/decisions/0002-digital-twin.md`, decision 39. Research: `docs/research/cloudflare-access.md`.

**Nothing in this runbook has been applied. The agent that wrote it changed no DNS, no Access settings and no tunnel on the box.** Each step below is run by the operator, or by Claude after the operator approves it.

**Librarian's `sme_tunnel` and every `sme_*` container, volume and DNS record are never touched by any step in this runbook.** The `twin` tunnel is a separate named tunnel with its own credentials, its own config file and its own container. The only DNS change is one new record, `twin-api`, which overrides the `*.papyrus-ai.net` wildcard for that one name only (research doc, "DNS, as it matters here").

## Facts this runbook relies on

- Librarian's production tunnel is locally managed and runs as `sme_tunnel` (research doc, "The tunnel on the box"). This runbook does not read or change it.
- Access applications deny by default. A user must match an Allow policy (research doc, "Path-scoped applications", citing the self-hosted application docs).
- A wildcard path such as `api/w/*` covers `/api/w/runs` and does not cover `/api/w` or the apex (research doc, "Path-scoped applications").
- Browsers send no cookies on CORS preflight (OPTIONS). Access can answer the preflight at the edge (research doc, "CORS and OPTIONS", citing https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/cors/).
- Decision 39: the API lives at `twin-api.papyrus-ai.net` behind its own `twin` tunnel, Zero Trust team `papyrus`, 24 h sessions. The operator enables Zero Trust and creates the `cloudflare-zt-token`.
- The API reads its Access settings from environment variables. As of this runbook, `twin/api.py` does not read them yet. That lands with ticket 11b. The names used here are `TWIN_ACCESS_TEAM`, `TWIN_ACCESS_AUD` and `TWIN_OPERATOR_EMAIL`. The research doc used `CF_ACCESS_TEAM` and `CF_ACCESS_AUD`. If 11b uses different names, change this runbook to match the code.

## Approval list

| # | Change | Approval |
|---|---|---|
| 1 | Create tunnel `twin` on the box, its config file, and the `twin_tunnel` compose service | Claude may do this, showing each file first. Nothing public changes yet. |
| 2 | DNS: one CNAME `twin-api` to `<tunnel-id>.cfargotunnel.com`, proxied | **Operator approves before it is created.** |
| 3 | Access application on `/api/w/*` and its Allow policy | **Operator approves before it is created.** Operator does the Google sign-in setup. |
| 4 | Public read routes `/api/r/*` | No Access application. Nothing to approve. |

## 1. Create the `twin` tunnel on the box

Run on the box over `ssh akamel-linux`. Do not run these on the Mac.

1. Log in to Cloudflare from cloudflared, if the box has no login yet. This opens a browser step, so the operator does it:

   ```sh
   cloudflared tunnel login
   ```

2. Create the named tunnel. Its name is `twin`, which is different from Librarian's tunnel:

   ```sh
   cloudflared tunnel create twin
   ```

   The output gives the tunnel UUID (`<tunnel-id>` below) and a credentials file at `~/.cloudflared/<tunnel-id>.json`. Check with `cloudflared tunnel list`. Source: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/

3. Put the credentials file and config in a directory that only the `twin` tunnel uses, for example `/etc/twin-tunnel/`. Do not touch `/etc/cloudflared/`, which is Librarian's.

4. Write `/etc/twin-tunnel/config.yml`. The `ingress` block sends the API hostname to the API container, and a final rule answers everything else with 404. The `ingress` and catch-all syntax comes from Cloudflare's configuration file reference (https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/). That page was not fetched while writing this runbook. Check the syntax there before the first run.

   ```yaml
   tunnel: <tunnel-id>
   credentials-file: /etc/cloudflared/<tunnel-id>.json

   ingress:
     - hostname: twin-api.papyrus-ai.net
       service: http://twin-api:8090
     - service: http_status:404
   ```

5. Add the compose service `twin_tunnel` to the twin compose file, next to the `twin-api` service. It joins the same network as `twin-api`, so the name `twin-api` resolves. Mount the config and credentials read-only. Use the same cloudflared image tag and digest that `sme_tunnel` runs, so only the config differs.

   ```yaml
   services:
     twin_tunnel:
       image: cloudflare/cloudflared@<digest-pinned-like-sme_tunnel>
       command: tunnel --config /etc/cloudflared/config.yml run
       restart: unless-stopped
       volumes:
         - /etc/twin-tunnel/:/etc/cloudflared/:ro
       networks:
         - twin
   ```

   The `networks` entry must name the same network as the `twin-api` service. The operator sets the network name.

6. Start only this service:

   ```sh
   docker compose up -d twin_tunnel
   docker compose logs --tail 50 twin_tunnel
   ```

   The logs should show the tunnel connected. No public route exists yet, so a request to `twin-api.papyrus-ai.net` still fails until step 2 is done.

**`sme_tunnel` and every `sme_*` container, volume and DNS record are never touched.** Do not run `docker compose down` in Librarian's stack. Do not run `docker volume prune` on the box. Check `docker ps` shows `sme_tunnel` still up after each step.

## 2. DNS: the `twin-api` record (operator approves first)

**Operator approves before it is created.**

The record is one CNAME:

- name: `twin-api`
- target: `<tunnel-id>.cfargotunnel.com`
- proxy: on (orange cloud)

Create it with the cloudflared command, or in the Cloudflare DNS dashboard. Both give the same record:

```sh
cloudflared tunnel route dns twin twin-api.papyrus-ai.net
```

Source for the command and the `<UUID>.cfargotunnel.com` target: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/

This is the only DNS change. Leave the apex, `twin`, and the `*` wildcard alone. Pages `twin.papyrus-ai.net` is a separate record that the Pages project sets up.

## 3. Access application for `/api/w/*` (operator approves first)

**Operator approves before it is created.** The operator creates the Google sign-in setup, because it uses a client secret. Claude does not type that secret.

First, the operator enables Zero Trust with team name `papyrus` and the Free plan. Team name and plan come from research doc, "Steps the operator must approve", step 1. The Free plan covers up to 50 users (research doc, "Plan and setup").

Then, in Zero Trust:

1. **Identity provider:** add Google. It needs a Google Cloud OAuth client of type Web application, with JavaScript origin `https://papyrus.cloudflareaccess.com` and redirect URI `https://papyrus.cloudflareaccess.com/cdn-cgi/access/callback` (research doc, "Login method"). Paste the client ID and secret into Zero Trust.

2. **Application:** create a self-hosted application.
   - Name: `twin control API writes`.
   - Domain: `twin-api.papyrus-ai.net`, path `api/w/*`. A wildcard path covers `/api/w/runs` and does not cover `/api/w` (research doc, "Path-scoped applications").
   - Session duration: 24 h (decision 39).
   - Identity provider: Google.

3. **CORS**, in the application's Advanced settings. Answer preflights at the edge so OPTIONS requests never reach the origin:
   - Allow origin: `https://twin.papyrus-ai.net`
   - Allow credentials: `true`
   - Allow methods: `POST`
   - Allow headers: `Content-Type`

   Do not turn on "bypass OPTIONS to origin". That setting removes these CORS settings (research doc, "CORS and OPTIONS"). Keep FastAPI's `CORSMiddleware` as well; the spec wants both layers.

4. **Policy:** one policy named `operator only`, action Allow, Include: emails equal to `<operator-email>` (the operator's Google account), login method Google. No other Include rules. Access denies everyone else by default (research doc, "Path-scoped applications").

5. **Copy the AUD tag.** It is under the application's Additional settings. It "will never change unless you delete or recreate the Access application" (research doc, "JWT validation"). Keep it in the API's environment, not in the repo. The team name is `papyrus`.

6. **Set the API's environment** on the `twin-api` service:

   ```sh
   TWIN_ACCESS_TEAM=papyrus
   TWIN_ACCESS_AUD=<aud-tag-from-step-5>
   TWIN_OPERATOR_EMAIL=<operator-email>
   ```

   The API checks `Cf-Access-Jwt-Assertion` against `https://papyrus.cloudflareaccess.com/cdn-cgi/access/certs`, with `iss` set to `https://papyrus.cloudflareaccess.com` and `aud` set to the AUD tag (research doc, "JWT validation"). Ticket 11b wires this in.

The read routes `/api/r/*` get no application. Access covers only the path given above.

## 4. Public read routes: no Access application

`/api/r/*` is public, so signed-out viewers can read the live panel, the runs and their files (spec section 3, "Read routes"). Do not create an Access application for `/api/r/*`. Adding one would block the public panel.

## 5. Verification

Run these after steps 1 to 3. The API must be running with the write routes merged (ticket 11b). Before 11b, `POST /api/w/runs` returns 404 at the origin.

**Edge check, no credentials.** Expect a redirect to the login page, or a 401 or 403. Do not expect a 200 or a 404.

```sh
curl -i -X POST https://twin-api.papyrus-ai.net/api/w/runs \
  -H 'Content-Type: application/json' -d '{}'
```

The status line should read `HTTP/2 302`, `401` or `403`. Access does not forward the request to FastAPI.

**Origin check, forged JWT.** Send the request straight to the API, skipping Access, with a made-up `Cf-Access-Jwt-Assertion`. Expect `401` from FastAPI. This must run on the box, on the `twin` compose network, because the origin has no public address. For example, from a throwaway curl container on that network:

```sh
docker run --rm --network <twin-network> curlimages/curl:latest \
  -i -X POST http://twin-api:8090/api/w/runs \
  -H 'Content-Type: application/json' \
  -H 'Cf-Access-Jwt-Assertion: forged.jwt.value' -d '{}'
```

Expect `HTTP/1.1 401`. A `200`, a `403` or a `404` here is a failure. Spec section 8 requires 401 at the origin for a forged or missing JWT.

**CORS preflight.** Expect the `access-control-*` headers from the edge:

```sh
curl -I -X OPTIONS https://twin-api.papyrus-ai.net/api/w/runs \
  -H 'Origin: https://twin.papyrus-ai.net' \
  -H 'Access-Control-Request-Method: POST'
```

Expect `access-control-allow-origin: https://twin.papyrus-ai.net` and `access-control-allow-credentials: true`.

**Public read.** Expect `200` signed out:

```sh
curl -i https://twin-api.papyrus-ai.net/api/r/runs
```

**Sanity check on Librarian.** Confirm production is still up after every step:

```sh
docker ps --filter name=sme_tunnel --format '{{.Names}} {{.Status}}'
```

Do not use `docker inspect` on `sme_*` containers. Research doc records that a deeper inspect of production was refused.

Test in a normal browser window, not Incognito. Incognito blocks the Access cookie as third-party (research doc, "CORS and OPTIONS").

## 6. Rollback

Each step is separate. None of them touches `sme_*`. Run them in this order. Each delete needs operator approval, because it is irreversible.

1. **Stop the tunnel:**

   ```sh
   docker compose stop twin_tunnel
   docker compose rm -f twin_tunnel
   ```

   Traffic to `twin-api.papyrus-ai.net` now fails, and the panel shows the API as unreachable. Public views keep working from static files (spec section 8).

2. **Delete the `twin-api` CNAME.** Operator approves. Use the Cloudflare DNS dashboard, or the API with the `cloudflare-api-token`. Delete only the `twin-api` record. Leave the wildcard and the Pages `twin` record alone.

3. **Delete the Access application** `twin control API writes` in Zero Trust. Operator approves. Deleting it removes the AUD tag, so `TWIN_ACCESS_AUD` must be removed too.

4. **Optional: delete the tunnel `twin`** once it has no connections:

   ```sh
   cloudflared tunnel delete twin
   ```

   Operator approves. Then delete `/etc/twin-tunnel/`.

5. **Optional: disable Zero Trust** for the team. Operator decides. Disabling it is not needed to roll back the API.

After rollback, check `docker ps` still shows `sme_tunnel` up, and `https://twin.papyrus-ai.net` (Pages) still loads.

## 7. Deploy the API container

Built from the repo's `Dockerfile` and started by `deploy/compose.yaml`. Run these on the box, in this order. **Not run yet: each command needs operator approval before it is run on the box.**

1. Check free disk. Hold when less than 10 GB is free (operator, 2026-10-26):

   ```sh
   df -h /
   ```

2. Create the env file from the example, and fill in the two values from section 3 step 6. The file is gitignored:

   ```sh
   cp deploy/twin.env.example deploy/twin.env
   ```

3. Give the non-root container user (uid 10001) the run store. The bind mount is owned by root otherwise:

   ```sh
   sudo chown 10001:10001 /data/twin-runs
   ```

   Only the operator runs `sudo`, as the box policy says.

4. Build and start only the API. Never `docker compose down` or `docker volume prune` on this box:

   ```sh
   docker compose -f deploy/compose.yaml up -d --build twin-api
   docker compose -f deploy/compose.yaml logs --tail 50 twin-api
   ```

   On start the API marks any stage left `running` by a restart as `failed` ("interrupted by restart") and clears `.current` and `.run.lock`. The log shows one warning per run changed.

5. Check the health status and that Librarian is still up:

   ```sh
   docker ps --filter name=twin-api --format '{{.Names}} {{.Status}}'
   docker ps --filter name=sme_tunnel --format '{{.Names}} {{.Status}}'
   ```

6. The tunnel (`twin_tunnel`) is section 1, step 6. Its image tag is a placeholder in `deploy/compose.yaml`: set it to the `sme_tunnel` tag and digest before starting it.

The API container is capped at 8 CPUs and 12 GB of memory. It mounts `/data/nuscenes` and `/data/osm` read-only.

## Not verified

- The tunnel and config syntax against the live Cloudflare configuration reference. Check before the first run.
- The `TWIN_ACCESS_*` and `TWIN_OPERATOR_EMAIL` variable names. They are not in `twin/api.py` yet (ticket 11b). Research doc used `CF_ACCESS_*`.
- The live state of Librarian's tunnel config on the box. The research doc could not read it.
- Whether the Access session cookie needs SameSite changes between `twin` and `twin-api`. Test on day 1 (research doc, "Not verified").
