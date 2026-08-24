# Runbook — putting the doc harness on the internet at `*.3dstories.ca`

Issue #35. Every step has a one-line undo. **Secrets appear by NAME only.** If you find a value
in this file, that is a defect — remove it and rotate the credential.

> **WARNING — read before touching Access.** An earlier run created the Access application with
> the public hostname `*` on this zone. A wildcard there matches **every** subdomain, including
> ones this project does not own, and on 2026-08-24 it put a login page in front of
> `www.3dstories.ca`. Step 2 below is written to prevent a repeat, and step 0 is the inventory
> that makes step 2 answerable. Do not skip step 0.

## What you are building

```
browser ──▶ Cloudflare edge ──▶ Access (authn) ──▶ tunnel ──▶ cloudflared ──▶ harness:8080
                                                                (compose network, no host port)
```

The harness publishes no host port and never has. Before this runbook it was unreachable from
outside the Docker network; after it, the only route in is through Cloudflare Access.

## Why some of this is dashboard work and not a script

The Cloudflare credential this project has is the scoped token in the Traefik container on the
gateway. Measured on 2026-08-24 (decisions D11 and D12):

| Call | Result |
| --- | --- |
| zone lookup and `dns_records` on `3dstories.ca` | success |
| `accounts/<id>/cfd_tunnel` | error 10000 Authentication error |
| `accounts/<id>/access/apps` | error 10000 Authentication error |

So DNS is scriptable and the tunnel and the Access application are not. Steps 1 and 2 are
dashboard work. Step 4 is an API call. The day a token carrying **Account → Cloudflare Tunnel →
Edit** and **Account → Access: Apps and Policies → Edit** exists, steps 1 and 2 become
scriptable and the tunnel can become locally-managed, which would put the ingress rules in git
instead of in dashboard state. That is a recorded follow-up, not a plan.

## Step 0 — the zone inventory (do this FIRST, both later steps depend on it)

AC 2 requires the DNS write to happen after an inventory, and AC 3 decides the Access layout from
what the inventory shows. Neither step below is answerable without it.

```bash
ssh root@10.0.17.201 'bash -s' <<'REMOTE'
CF_TOKEN=$(docker exec traefik printenv CF_DNS_API_TOKEN)
[ -z "$CF_TOKEN" ] && { echo "ABORT: token empty"; exit 1; }
curl -s "https://api.cloudflare.com/client/v4/zones/ebad2c7aa7b0a8151b2a1f7fce5a5dc6/dns_records?per_page=100" \
  -H "Authorization: Bearer $CF_TOKEN"
REMOTE
```

Write the result down — name, type, `proxied` — before continuing. Two questions must be answered
in writing:

1. **Which subdomains are already proxied?** Every one is a host a wildcard Access application
   would capture. Already known: `www` is proxied.
2. **Does an explicit record already exist at `*`?** If so, step 4 is a conflict, not a create.

**Undo:** none. This step reads and changes nothing.

**If the run cannot reach `10.0.17.201`** — the Claude Code auto-mode classifier blocks ssh to
that host in some sessions (decision D16) — then steps 0 and 4 are blocked, and the honest
outcome is to report AC 2 blocked rather than to route around the refusal.

## Step 1 — create the tunnel (dashboard)

1. Open `one.dash.cloudflare.com` and select the account.
2. **Networks → Tunnels → Create a tunnel**, connector **Cloudflared**, name `doc-harness`.
3. Save. The install screen shows a command containing `--token <value>`. Copy only that token.
   Do not run the command it prints — cloudflared runs as a container here, from step 3.
4. Open the tunnel's **Published application route** and add one route:

   | Field | Value |
   | --- | --- |
   | Subdomain | `*` |
   | Domain | `3dstories.ca` |
   | Path | leave empty (match all paths) |
   | Service Type | `HTTP` |
   | Service URL | `harness:8080` |

   **The URL must be `harness:8080`, not `localhost:8080`.** cloudflared runs in its own
   container, so `localhost` there is cloudflared itself. `harness` is the compose service name,
   which is how one container addresses another on the same network. The dashboard's placeholder
   is wrong for this topology.

5. Add a second, lower-priority catch-all route returning a 404 for anything the wildcard does not
   cover, per AC 1.

**Undo:** delete the tunnel in the same screen. That also removes its routes.

**Known trap, measured:** the route screen says "DNS will be automatically configured." On the
2026-08-24 run it did not create a wildcard record — the zone held 23 records and zero wildcards
afterwards. Do not assume DNS exists because that sentence is on screen. Step 4 creates it, and
step 5 verifies it.

## Step 2 — the Access application and its policies (dashboard)

6. **Access → Applications → Add an application → Self-hosted**, name `doc-harness`.
7. Public hostname: **exact hosts, never `*`.** Add `docs-index.3dstories.ca`,
   `docs-control.3dstories.ca`, and one entry per published doc name.

   **CAUTION: do not use subdomain `*` here.** AC 3 permits a single wildcard application only
   when nothing else on the zone is proxied on a subdomain. Step 0 answers that, and on this zone
   the answer is no — `www` is proxied. A wildcard application captures it and serves a login page
   in front of a site that has nothing to do with this project. That is not hypothetical: it
   happened on 2026-08-24 and the response header `cf-access-domain: *.3dstories.ca` is what
   identified it.

   **If the application already exists with `*`,** edit its public hostname to the exact list
   above. Verify with `curl -s -o /dev/null -w '%{http_code}' https://www.3dstories.ca/` — a `302`
   to `cloudflareaccess.com` means it is still captured.

8. Policy `owner`: action **Allow**, include **Emails** → the owner's address.
9. Policy `automation`: action **Service Auth**, include **Service Token** → the token from step 10.

**Undo:** delete the application. Its policies go with it. Deleting the application removes
authentication from those hostnames, so do it only together with step 1's undo or the harness is
briefly exposed.

## Step 3 — the service token (dashboard)

10. **Access → Service Auth → Service Tokens → Create Service Token**, name
    `doc-harness-publisher`. Copy the Client ID and the Client Secret; the secret is shown once.

The two values are consumed as request headers `CF-Access-Client-Id` and
`CF-Access-Client-Secret`. **#36 consumes the same two** in `verify_live`, so they are not
single-use to this issue.

**Undo:** revoke the service token; the `automation` policy then denies everything.

## Step 4 — the three secrets on the host, and the wildcard record

11. Save the three values on `10.0.17.205`, one per file, mode 600:

    | File | Holds |
    | --- | --- |
    | `~/.secrets/doc-harness-tunnel-token` | the tunnel token from step 3 |
    | `~/.secrets/doc-harness-access-client-id` | the Access client id from step 10 |
    | `~/.secrets/doc-harness-access-client-secret` | the Access client secret from step 10 |

12. Point compose at the tunnel token by path, so no home directory is baked into a tracked file:

    ```bash
    export DOC_HARNESS_TUNNEL_TOKEN_FILE=~/.secrets/doc-harness-tunnel-token
    ```

13. Create the wildcard record. The tunnel id is the `t` field of the tunnel token, so it needs no
    account-scoped API call — decode the token locally rather than looking the tunnel up:

    ```bash
    ssh root@10.0.17.201 'bash -s' <<'REMOTE'
    CF_TOKEN=$(docker exec traefik printenv CF_DNS_API_TOKEN)
    [ -z "$CF_TOKEN" ] && { echo "ABORT: token empty"; exit 1; }
    curl -s -X POST "https://api.cloudflare.com/client/v4/zones/ebad2c7aa7b0a8151b2a1f7fce5a5dc6/dns_records" \
      -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
      --data '{"type":"CNAME","name":"*","content":"<TUNNEL-ID>.cfargotunnel.com",
               "proxied":true,"ttl":1,"comment":"doc-harness tunnel (#35)"}'
    REMOTE
    ```

    `proxied` must be **true** — the traffic has to reach the Cloudflare edge for Access to apply.
    That is the opposite of the rule for a Tailscale or LAN address, which must be grey-clouded.
    Keep the `comment` under 100 characters or Cloudflare rejects the whole request with code 9313.

    **Reconcile before you create, in this order.** Step 0's inventory already tells you which
    case you are in:

    | Case | Do this |
    | --- | --- |
    | no record at `*` | create it |
    | a record at `*` whose every field already matches the table below | **no-op success** — do not create a second one |
    | a record at `*` with any field different | **ABORT** and report the difference; never overwrite a record this run did not create |

    | Field | Value |
    | --- | --- |
    | `type` | `CNAME` |
    | `name` | `*` |
    | `content` | `85f6194f-3347-44b4-84c3-3bbcfbb076bb.cfargotunnel.com` |
    | `proxied` | `true` |
    | `ttl` | `1` |

    The no-op case is not pedantry. A `POST` that times out may well have landed, and a blind
    retry double-creates. After any create, **assert the returned record's fields against that
    table** before running `dig`: Cloudflare answering `success: true` is not the same as the
    record being the one you asked for.

    **Run the disposable write spike first.** Create a throwaway `TXT` named
    `_doc-harness-spike`, assert `success: true`, `DELETE` it, assert that too. A successful `GET`
    proves read, not write. If either call does not report success, ABORT and report AC 2 blocked
    rather than proceeding on the strength of a read.

**Undo:** `DELETE` that one record by id. Explicit records are untouched, because an explicit
record beats a wildcard.

## Step 5 — bring the stack up and verify

14. `docker compose up -d` on `10.0.17.205`.
15. Confirm the harness reports healthy before cloudflared advertises a route. cloudflared uses
    `depends_on: service_healthy`, so `docker compose ps` showing cloudflared started IS that
    confirmation.
16. Resolve the name through two public resolvers, because a Cloudflare `success: true` is not
    proof the world can see it:

    ```bash
    for r in 1.1.1.1 8.8.8.8; do printf 'via %-8s ' "$r"; dig +short @$r test.3dstories.ca; done
    ```

17. Anonymous fetch of **each host AC 3 names, by name** → expect the Access login page:

    ```bash
    for h in docs-index docs-control; do
      printf '%-14s ' "$h"
      curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' "https://$h.3dstories.ca/"
    done
    ```

17a. **The regression check — a host that must NOT be gated.** `www.3dstories.ca` belongs to
    something else on this zone and must answer without an Access interstitial:

    ```bash
    curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://www.3dstories.ca/
    ```

    A `302` to `cloudflareaccess.com` means the Access application is still over-broad. **Go-live
    FAILS.** Go back to step 2 and narrow the hostname list.

17b. **The catch-all check — an unconfigured name must 404.** Send this WITH the service token, so
    a 404 cannot be confused with an Access redirect:

    ```bash
    curl -s -D- -o /dev/null "https://unconfigured-probe.3dstories.ca/" \
      -H "CF-Access-Client-Id: $(cat ~/.secrets/doc-harness-access-client-id)" \
      -H "CF-Access-Client-Secret: $(cat ~/.secrets/doc-harness-access-client-secret)"
    ```

    Expect `404`, **no** `X-Doc-Deployment` header, and **no** matching request at the harness.
    Anything else means the tunnel routes every name to the harness and AC 1's catch-all is not in
    force. The literal `*` in the tunnel's Path column is the first suspect; that field takes a
    regex and a bare `*` is not a meaningful one. Clearing it is dashboard-only.

18. Service-token fetch of the real host → expect `200` and the `X-Doc-Deployment` echo:

    ```bash
    curl -s -D- -o /dev/null "https://<name>.3dstories.ca/" \
      -H "CF-Access-Client-Id: $(cat ~/.secrets/doc-harness-access-client-id)" \
      -H "CF-Access-Client-Secret: $(cat ~/.secrets/doc-harness-access-client-secret)"
    ```

**A 404 through the tunnel means step 1's published route was never saved.** That is the expected
symptom, and it is the one thing in this runbook the available credential cannot check in advance:
tunnel ingress is dashboard state and `cfd_tunnel` is refused. The live fetch is the only evidence
for AC 1.

## Step 6 — the slow-client check, inherited from #34

#34 deferred one High finding into this issue with an owner acknowledgement. waitress offers no
absolute request deadline, so `DOC_HARNESS_CHANNEL_TIMEOUT` bounds inactivity rather than total
request time, and a client that trickles bytes can hold a channel. While the harness published no
port the exposure was nil. This runbook ends that, so the check is real work:

19. **Start the observation BEFORE the first byte, and prove the observation works.** Capture in
    the harness's network namespace, filtered to destination port 8080, for the whole window. Then
    send ONE ordinary request through the tunnel as a control and confirm the capture recorded it.
    A capture that cannot see a known-good request cannot prove the absence of a bad one, so this
    control is a prerequisite and not a formality.
20. Open a connection to the public hostname and send one byte of a request header every 30
    seconds, for up to 300 seconds.
21. **Pass requires all three:** the control request appears in the capture; Cloudflare terminates
    the slow connection within 120 seconds; and no SYN or payload from the slow-client run reaches
    port 8080 across the whole window.

    **Do not count `/proc/net/tcp` lines.** An earlier revision proposed it and it cannot work: it
    counts every TCP entry in the namespace rather than bytes to port 8080, and the `HEALTHCHECK`
    runs every 10 seconds in that same namespace, leaving sockets in `TIME_WAIT`. The count moves
    on its own. There is also no per-request access log to count instead — the harness logs only
    at start-up, on an unhandled error, and on an alert.

    If the capture cannot be made to work on this host, report C4 **NOT discharged** and leave it
    a deferred High. Never report it discharged on a check that did not run.

If Cloudflare does not terminate it, the remedy is edge configuration, not a watchdog inside the
harness — that option was considered in #34 and declined, with the reason recorded.

## Operational notes

**The healthcheck assumes loopback.** The Dockerfile's `HEALTHCHECK` opens a TCP connection to
`127.0.0.1:8080`. `DOC_HARNESS_BIND` defaults to `0.0.0.0:8080`, which accepts on loopback, so it
works. If you ever narrow the bind to one interface, change the healthcheck in the same commit or
the harness never reports healthy and cloudflared never starts.

**cloudflared is pinned by digest, not `:latest`.** This project pins every runtime dependency
exactly and has a test asserting it. A moving tag would let the stack's behavior change without a
commit.

**One harness replica, always.** Its LRU accounting and single-flight map are process-local, and
it takes an exclusive lock on the cache volume, so a second writer fails loudly at start-up rather
than corrupting the accounting quietly.
