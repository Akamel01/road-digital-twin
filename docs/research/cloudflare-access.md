# Cloudflare Access for the twin control API

Question: issue #6, part of map #3. Read on 2026-11-07 with the keychain token `cloudflare-api-token`, GET requests only. Nothing was changed. No secrets or account IDs are in this file.

## Answer

- **No Zero Trust team exists yet.** Access is not enabled on the account. There is no team domain, no Google identity provider, no Access application and no Access policy. All of this is new work on day 1.
- **A tunnel already exists, but it is Librarian's.** `*.papyrus-ai.net` is a proxied CNAME to one named tunnel. On the box that tunnel runs as the production container `sme_tunnel`, with a locally managed config file that sends `papyrus-ai.net` and `*.papyrus-ai.net` to Librarian's Caddy. The token cannot read tunnels, so the API could not confirm this.
- **Access is free for one user.** The Zero Trust Free plan is $0 for up to 50 users. Setup still asks for payment details, but the Free plan is not charged.
- **What the `/api/w/*` application needs:**
  - a self-hosted application on the API hostname with path `api/w/*`;
  - an Allow policy for the operator's Google email;
  - CORS answered by Access (origin `https://twin.papyrus-ai.net`, credentials on), or OPTIONS passed to FastAPI;
  - FastAPI checking `Cf-Access-Jwt-Assertion` with RS256 against `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, with `aud` set to the application's AUD tag and `iss` set to the team domain.
- **Open point for T9:** Pages serves `twin.papyrus-ai.net`, so the API needs its own hostname (for example `twin-api.papyrus-ai.net`) on the tunnel. The spec's CORS rule already assumes two origins. The issue's wording, "`/api/w/*` on `twin.papyrus-ai.net`", would need a Worker in front of Pages instead.

## Facts from the account (read only)

| Read | Result | Meaning |
|---|---|---|
| `GET /user/tokens/verify` | active, no expiry | token works |
| `GET /accounts` | 1 account | one account holds everything |
| `GET /zones?name=papyrus-ai.net` | active, plan "Free Website" | zone is on this account |
| `GET /accounts/{id}/access/organizations` | error 10000, Authentication error | **token lacks the Access: Organizations read scope** |
| `GET /accounts/{id}/access/identity_providers` | error 9999, `access.api.error.not_enabled` | Access is not enabled; no IdP |
| `GET /accounts/{id}/access/apps` | error 9999, not enabled | no Access applications |
| `GET /accounts/{id}/access/policies` | error 9999, not enabled | no reusable policies |
| `GET /accounts/{id}/access/groups` | error 10000 | token lacks the Access groups scope |
| `GET /zones/{id}/access/apps` | error 10000 | token lacks the zone-level Access scope |
| `GET /accounts/{id}/cfd_tunnel` (also `is_deleted=true`) | success, 0 results | **not proof that no tunnel exists**; see next row |
| `GET /accounts/{id}/cfd_tunnel/<id from DNS>` | error 1001, Not authorized | **token lacks the Cloudflare Tunnel read scope**; the empty list is a scope effect |
| `GET /accounts/{id}/gateway` | error 10000 | token lacks the Zero Trust / Gateway scope |
| `GET /zones/{id}/dns_records` | 19 records | see below |
| `GET /accounts/{id}/workers/domains` | apex `papyrus-ai.net` | the apex is a Worker custom domain |

The "not enabled" errors come from the Access service itself, so they hold even though the organizations read was refused: there is no Zero Trust organization on the account.

**DNS, as it matters here:**
- `*.papyrus-ai.net` is a proxied CNAME to `01ca75c2-….cfargotunnel.com`, one named tunnel.
- The apex is a proxied `AAAA 100::`, the usual placeholder for a Worker route or custom domain. The Workers domain read confirms it.
- There is no `twin` or `twin-api` record. Such a name falls through to the wildcard today, so it reaches Librarian's Caddy.
- A specific record such as `twin` (Pages) or `twin-api` (tunnel) overrides the wildcard for that name only.

**The tunnel on the box.**
- `docker ps` on the box lists `sme_tunnel`. A deeper `docker inspect` was refused because it reads production, so it was not run.
- Librarian's compose file runs `cloudflared tunnel --config /etc/cloudflared/config.yml run`, with a credentials file and a local config file. Source: the local checkout `papyrus-ai-wt-45/docker-compose.yml`, service `cloudflared`. Its image digest matches the running container's image.
- That checkout's `.templates/cloudflared-config.yml` names the same tunnel ID as the DNS wildcard. Its ingress sends `papyrus-ai.net` and `*.papyrus-ai.net` to `http://caddy:80`, and `/deploy-webhook.*` to the deploy hook.
- The tunnel is **locally managed**: its routes live in a file on the box, not in the dashboard. That checkout may be older than the live config.

## Facts from Cloudflare's docs

**Path-scoped applications** ([application paths](https://developers.cloudflare.com/cloudflare-one/policies/access/app-paths/)):
- An application can cover one hostname plus a path. A `*` in the path matches the rest of the path.
- A wildcard path "does not cover the parent path nor the apex domain". So `api/w/*` protects `/api/w/runs` and leaves `/api/r/*` public, and `/api/w` itself is not covered. FastAPI should have no route on the bare `/api/w`.
- When rules share a root, "the more specific rule takes precedence".
- Query strings are not supported in paths. The page does not mention HTTP methods, so Access cannot protect POST only. Use a path, which the spec already does.
- All applications deny by default; a user must match an Allow policy ([self-hosted app](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-public-app/)).
- The hostname must be in an active zone on the account. A tunnel is recommended but not required.

**CORS and OPTIONS** ([CORS](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/cors/)):
- A CORS request reaches an Access-protected site only with a valid `CF_Authorization` cookie.
- Browsers never send cookies on OPTIONS, so by default a preflight gets 403.
- There are two settings under the application's Advanced settings, CORS:
  - **Answer the preflight at the edge.** Set Allow-Origin `https://twin.papyrus-ai.net`, Allow-Credentials `true`, Allow-Methods `POST`, and Allow-Headers `Content-Type`. The OPTIONS request never reaches the origin.
  - **Bypass OPTIONS to origin.** This sends OPTIONS to FastAPI and removes the Access CORS settings. Use it only if the origin enforces CORS.
- The spec wants both layers. Use the first setting, and keep FastAPI's `CORSMiddleware` for the real POST response.
- The doc's example uses `credentials: 'same-origin'`. That works only for a same-origin API. For a separate `twin-api` hostname, the panel's fetch must use `credentials: 'include'`, or the cookie is not sent. This is the Fetch standard, not the Cloudflare page.
- The `CF_Authorization` cookie is set on the API hostname only after a top-level visit that completes login. A `fetch` that meets the login redirect fails under CORS. The panel needs a "sign in" link that opens a protected URL on the API host in the window. This is inferred from the cookie flow; test it on day 1.
- Don't test in Incognito, which blocks the cookie as a third-party cookie.

**JWT validation** ([validating JWTs](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/)):
- Read the `Cf-Access-Jwt-Assertion` header, not the cookie.
- The algorithm is RS256.
- The keys are at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`. Match the JWT's `kid` to an entry in `public_certs`; do not use `public_cert`.
- Check `aud` against the AUD tag. The tag is in the application's Additional settings. It "will never change unless you delete or recreate the Access application", so it can sit in config.
- Check `iss` against `https://<team>.cloudflareaccess.com`. PyJWT checks `exp` by default.
- Keys rotate every 6 weeks by default, and old keys stay valid for 7 days. Cache the JWKS, and refetch on an unknown `kid`. PyJWT's `PyJWKClient` does this.
- Both the team name and the AUD tag are unknown until day 1, so T9 should read them from environment variables.

**Plan and setup** ([plan page](https://www.cloudflare.com/plans/sase-zero-trust.md), [setup](https://developers.cloudflare.com/cloudflare-one/setup/)):
- The Free plan is "$0 forever" for teams under 50 users and includes Zero Trust Network Access, which is Access.
- Onboarding asks for a team name, which becomes `<team>.cloudflareaccess.com`.
- It also asks for a plan and payment details: "this step is still needed but you will not be charged".

**Login method** ([Google IdP](https://developers.cloudflare.com/cloudflare-one/identity/idp-integration/google/), [one-time PIN](https://developers.cloudflare.com/cloudflare-one/identity/one-time-pin/)):
- **Google** needs a Google Cloud OAuth client, of type Web application and with External audience:
  - JavaScript origin: `https://<team>.cloudflareaccess.com`;
  - redirect URI: `https://<team>.cloudflareaccess.com/cdn-cgi/access/callback`.
  - Its Client ID and secret then go into Zero Trust, Integrations, Identity providers.
- **One-time PIN** is no longer added on its own, and new organizations default to the "Cloudflare identity provider".
- For one user, an Allow rule on one email address is enough with either Google or OTP. Google matches the spec.

## Steps the operator must approve (day 1)

These are all writes or account actions. None were done.

1. **Enable Zero Trust:**
   - choose the team name (it is public in the login URL);
   - pick the Free plan;
   - enter payment details. The operator does this; Claude enters no payment details.
2. **Google OAuth client** in Google Cloud Console, with the two URIs above. Paste the Client ID and secret into Zero Trust. The operator does this, because the secret is a credential.
3. **Choose the API hostname.** The recommendation is `twin-api.papyrus-ai.net`, with Pages on `twin.papyrus-ai.net`.
4. **Choose the tunnel route.** There are two options:
   - **(a) A separate twin tunnel (recommended).** Its own `cloudflared` container in the twin compose stack, and its own CNAME `twin-api` → `<new-id>.cfargotunnel.com`. It doesn't touch Librarian production.
   - **(b) Librarian's existing tunnel.** Add an ingress rule for `twin-api.papyrus-ai.net` above the wildcard in the live config on the box, and restart `sme_tunnel`. This briefly drops all Librarian traffic.
   - **Token scopes either way:** Claude can make (a) through the API only after the token gains Cloudflare Tunnel Edit. It can manage Access after the token gains the Access scopes (apps and policies, organizations, IdPs). Otherwise the operator does these steps in the dashboard.
5. **Create the Access application:**
   - self-hosted, on `twin-api.papyrus-ai.net`, path `api/w/*`;
   - session length to decide (the map lists it as open);
   - CORS: answer the preflight with origin `https://twin.papyrus-ai.net`, credentials on, methods `POST`, headers `Content-Type`.
6. **Create the Access policy:** Allow, Include emails = the operator's Google address, login method Google.
7. **Copy the AUD tag and team name** into the API's environment (`CF_ACCESS_AUD`, `CF_ACCESS_TEAM`). These are not secrets, but keep them out of the repo.
8. **Pages DNS:** add a `twin` custom domain on the Pages project. This adds a specific record that overrides the wildcard.
9. **Day-1 checks (spec section 8):**
   - a POST to `/api/w/runs` without a cookie gets 302 or 403 at the edge;
   - a forged JWT straight at the origin gets 401;
   - `curl -I -X OPTIONS` returns the `access-control-*` headers;
   - a GET to `/api/r/*` works signed out.

## Not verified

- The live tunnel config on the box. The only copy read is a local checkout's template, and production reads on the box were refused.
- Whether the token can be given the missing read scopes. That is a dashboard change for the operator.
- Whether the Access session cookie needs SameSite changes for `twin` → `twin-api` calls. The two hosts are same-site, so this should not matter, but test it on day 1.
