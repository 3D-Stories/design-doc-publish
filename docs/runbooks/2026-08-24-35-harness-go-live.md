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
   Do not run the command it prints — cloudflared runs as a container here, from step 5.
4. Open the tunnel's **Published application route** and add one route:

   | Field | Value |
   | --- | --- |
   | Subdomain | `*` (see the CAUTION in step 3 before you commit to this) |
   | Domain | `3dstories.ca` |
   | Path | leave empty (match all paths) |
   | Service Type | `HTTP` |
   | Service URL | `harness:8080` |

   **The URL must be `harness:8080`, not `localhost:8080`.** cloudflared runs in its own
   container, so `localhost` there is cloudflared itself. `harness` is the compose service name,
   which is how one container addresses another on the same network. The dashboard's placeholder
   is wrong for this topology.

5. Add a second, lower-priority catch-all route returning a 404 for anything the wildcard does
   not cover, per AC 1.

**Undo:** delete the tunnel in the same screen. That also removes its routes.

**Known trap, measured:** the route screen says "DNS will be automatically configured." On the
2026-08-24 run it did not create a wildcard record — the zone held 23 records and zero wildcards
afterwards. Do not assume DNS exists because that sentence is on screen. Step 6 creates it, and
step 7 verifies it.

## Step 2 — the service token (dashboard) — BEFORE the policy that uses it

Ordering matters and an earlier draft got it wrong: the `automation` policy in step 3 selects
this token, so it has to exist first.

6. **Access → Service Auth → Service Tokens → Create Service Token**, name
   `doc-harness-publisher`. Copy the Client ID and the Client Secret; the secret is shown once.

The two values are consumed as request headers `CF-Access-Client-Id` and
`CF-Access-Client-Secret`. **#36 consumes the same two** in `verify_live`, so they are not
single-use to this issue.

**Undo:** revoke the service token; the `automation` policy then denies everything.

## Step 3 — the Access application — STOP, this needs an owner decision first

> **WARNING — do not improvise the hostname here.** Both available layouts are wrong in
> different ways, and the choice between them amends an acceptance criterion, so it is the
> owner's and not the operator's.
>
> | | Option A — narrow the wildcard | Option B — exact hosts |
> | --- | --- | --- |
> | Access hostname | `*.docs.3dstories.ca` | `docs-index`, `docs-control`, one per doc |
> | DNS record (step 6) | `*.docs` | `*` as AC 2 says today |
> | Can it capture `www`? | **No, structurally** | No, while the list stays right |
> | A newly published doc is | protected automatically | **PUBLIC until someone adds an entry** |
> | Cost | **amends AC 2's text** | a permanent maintenance duty on a security boundary |
>
> **Option A is the recommendation.** Option B's row in bold is an authentication bypass, not an
> inconvenience: the tunnel route is a wildcard, so a new document host is servable the moment it
> is published, and its Access entry is added by a human afterwards.
>
> **Do not proceed with Option B unless the Access host lifecycle contract in the planning
> document is implemented first** — the entry is created and VERIFIED before the host becomes
> servable, and publication FAILS if it cannot be. Without that contract, Option B is not an
> acceptable configuration.

7. **Access → Applications → Add an application → Self-hosted**, name `doc-harness`.
8. Public hostname: whichever the owner chose above. If the application already exists with a
   bare `*` on the apex zone, this is the step that fixes the live regression — narrowing it is
   the whole point.
9. Policy `owner`: action **Allow**, include **Emails** → the owner's address.
10. Policy `automation`: action **Service Auth**, include **Service Token** → the token from
    step 6.
11. **Record both policies' action, include rule and precedence** in your notes. Step 7's
    negative-identity check cannot be constructed without them.

**Undo:** delete the application. Its policies go with it. Deleting the application removes
authentication from those hostnames, so do it only together with step 1's undo or the harness is
briefly exposed.

**Verify the edit took, because this run's credential cannot read it back.** `access/apps`
returns error 10000, so nothing here can be confirmed by API. After saving, re-open the
application and confirm every intended host is listed and both policies are still attached.

## Step 4 — the three secrets on the host

12. Save the three values on `10.0.17.205`, one per file, mode 600:

    | File | Holds |
    | --- | --- |
    | `~/.secrets/doc-harness-tunnel-token` | the tunnel token copied in step 1, item 3 |
    | `~/.secrets/doc-harness-access-client-id` | the Access client id from step 6 |
    | `~/.secrets/doc-harness-access-client-secret` | the Access client secret from step 6 |

13. Point compose at the tunnel token by path, so no home directory is baked into a tracked file:

    ```bash
    export DOC_HARNESS_TUNNEL_TOKEN_FILE=~/.secrets/doc-harness-tunnel-token
    ```

**Undo:** delete the three files.

## Step 5 — bring the stack up and prove the secret works, BEFORE touching DNS

This step moved ahead of the DNS write deliberately. An unreadable secret discovered here costs
nothing; discovered after a production DNS record exists, it costs a rollback.

14. `docker compose --profile tunnel up -d` on `10.0.17.205`. **The profile is required** —
    cloudflared is opt-in so that plain `docker compose up` keeps working for anyone running the
    harness locally with no Cloudflare at all.
15. Confirm the harness reports healthy before cloudflared advertises a route. cloudflared uses
    `depends_on: service_healthy`, so `docker compose ps` showing cloudflared started IS that
    confirmation.
16. **The real-secret smoke test.** All three must hold:

    ```bash
    docker compose logs cloudflared | grep -iE "token|unauthor|error" | head
    docker inspect "$(docker compose ps -q cloudflared)" | grep -c "$(cat ~/.secrets/doc-harness-tunnel-token)" || echo "token absent from inspect: good"
    docker compose config | grep -c "$(cat ~/.secrets/doc-harness-tunnel-token)" || echo "token absent from rendered config: good"
    ```

    Require: cloudflared running with no token-read error, and **zero** matches in both the
    container inspection and the rendered config. The tunnel also flips from `Inactive` to
    `Active` in the dashboard once the connector attaches — a remotely-managed tunnel is
    `Inactive` until then, so that transition is a positive signal rather than a fault clearing.

    **If any of the three fails, ABORT. Do not continue to step 6.**

**Undo:** `docker compose down` (add `-v` only if you also mean to discard the cache volume).

## Step 6 — the wildcard DNS record, spike first

**Read the whole step before running anything.** The production write is the LAST command here,
not the first.

17. **Reconcile any leftover spike record**, then run the disposable write spike. A successful
    `GET` proves read, not write, and this is the only thing that proves write:

    ```bash
    ssh root@10.0.17.201 'bash -s' <<'REMOTE'
    set -eu
    CF_TOKEN=$(docker exec traefik printenv CF_DNS_API_TOKEN)
    [ -z "$CF_TOKEN" ] && { echo "ABORT: token empty"; exit 1; }
    ZONE=ebad2c7aa7b0a8151b2a1f7fce5a5dc6
    API="https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records"
    AUTH="Authorization: Bearer $CF_TOKEN"

    # leftover spike from a previous aborted run?
    OLD=$(curl -s "$API?type=TXT&name=_doc-harness-spike.3dstories.ca" -H "$AUTH" \
          | python3 -c "import json,sys; r=json.load(sys.stdin).get('result') or []; print(r[0]['id'] if r else '')")
    [ -n "$OLD" ] && curl -s -X DELETE "$API/$OLD" -H "$AUTH" >/dev/null && echo "reconciled leftover spike $OLD"

    # the spike itself
    ID=$(curl -s -X POST "$API" -H "$AUTH" -H "Content-Type: application/json" \
         --data '{"type":"TXT","name":"_doc-harness-spike","content":"spike","ttl":60}' \
         | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result']['id'] if d.get('success') else '')")
    [ -z "$ID" ] && { echo "ABORT: write spike failed — AC 2 is BLOCKED"; exit 1; }
    curl -s -X DELETE "$API/$ID" -H "$AUTH" \
      | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('success') else 1)" \
      || { echo "ABORT: spike cleanup FAILED. Delete record id $ID by hand before retrying."; exit 1; }
    echo "write spike passed and cleaned up"
    REMOTE
    ```

    **If the spike aborts, stop. AC 2 is blocked and no production record is created.**

18. **Look up `*` and decide which case you are in**, before writing anything:

    | Case | Do this |
    | --- | --- |
    | no record at `*` | create it (step 19) |
    | a record at `*` matching every field below | **no-op success** — skip step 19 |
    | a record at `*` differing in any field | **ABORT** and report the difference |

    | Field | Value |
    | --- | --- |
    | `type` | `CNAME` |
    | `name` | `*` (or `*.docs` under Option A) |
    | `content` | `85f6194f-3347-44b4-84c3-3bbcfbb076bb.cfargotunnel.com` |
    | `proxied` | `true` |
    | `ttl` | `1` |

    The no-op case is not pedantry: a `POST` that times out may well have landed, and a blind
    retry double-creates.

19. **Only now** create the record, and assert the fields Cloudflare echoes back:

    ```bash
    ssh root@10.0.17.201 'bash -s' <<'REMOTE'
    CF_TOKEN=$(docker exec traefik printenv CF_DNS_API_TOKEN)
    [ -z "$CF_TOKEN" ] && { echo "ABORT: token empty"; exit 1; }
    curl -s -X POST "https://api.cloudflare.com/client/v4/zones/ebad2c7aa7b0a8151b2a1f7fce5a5dc6/dns_records" \
      -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
      --data '{"type":"CNAME","name":"*","content":"85f6194f-3347-44b4-84c3-3bbcfbb076bb.cfargotunnel.com",
               "proxied":true,"ttl":1,"comment":"doc-harness tunnel (#35)"}' \
      | python3 -m json.tool
    REMOTE
    ```

    Check `success: true` **and** that the echoed `type`, `name`, `content`, `proxied` and `ttl`
    match the table. Cloudflare answering `success: true` is not the same as the record being the
    one you asked for.

    `proxied` must be **true** — the traffic has to reach the Cloudflare edge for Access to apply.
    That is the opposite of the rule for a Tailscale or LAN address, which must be grey-clouded.
    Keep the `comment` under 100 characters or Cloudflare rejects the whole request with code 9313.

**Undo:** `DELETE` that one record by id. Explicit records are untouched, because an explicit
record beats a wildcard.

## Step 7 — verify, including the checks that can FAIL

20. Resolve the name through two public resolvers, because a Cloudflare `success: true` is not
    proof the world can see it:

    ```bash
    for r in 1.1.1.1 8.8.8.8; do printf 'via %-8s ' "$r"; dig +short @$r test.3dstories.ca; done
    ```

21. Anonymous fetch of **each host AC 3 names, by name** → expect the Access login page:

    ```bash
    for h in docs-index docs-control; do
      printf '%-14s ' "$h"
      curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' "https://$h.3dstories.ca/"
    done
    ```

22. **The regression check, and it must prove RESTORATION, not merely the absence of Access.**
    "No interstitial" is satisfied by a 404, a 5xx, a wrong origin or an unrelated redirect —
    every one of which leaves `www` broken in a different way.

    ```bash
    curl -s -D- -o /tmp/www-body https://www.3dstories.ca/
    ```

    Require ALL of: the owner-provided expected final status; the expected redirect target if
    there is one; one stable site-specific marker present in the body; and **no
    `cf-access-domain` header**. **Go-live FAILS on any miss.**

    Honest caveat: the pre-change state cannot be captured now, because `www` is already behind
    Access. The invariant has to come from the owner. If none can be established, this degrades
    to "200 with no `cf-access-domain`", and **that weakening is recorded in the PR rather than
    passed over**.

23. **The catch-all check.** Send this WITH the service token, so a 404 cannot be confused with
    an Access redirect:

    ```bash
    curl -s -D- -o /dev/null "https://unconfigured-probe.3dstories.ca/" \
      -H "CF-Access-Client-Id: $(cat ~/.secrets/doc-harness-access-client-id)" \
      -H "CF-Access-Client-Secret: $(cat ~/.secrets/doc-harness-access-client-secret)"
    ```

    Expect `404`, **no** `X-Doc-Deployment`, and **no matching request at the harness**. That last
    clause needs the origin observation from step 8 — without it a misconfigured route that DOES
    reach the harness and returns an origin 404 is indistinguishable from the catch-all working.
    **If origin observation cannot be established, report AC 1 UNPROVED.** A bare 404 is not
    evidence.

24. **The negative-identity check.** Using an authenticated identity that is outside every
    include rule recorded in step 3 item 11, request a harness host. Require an Access **denial**
    and no request reaching the harness. This is the only check that detects an over-broad allow
    rule; the anonymous and service-token checks both pass without it.

25. Service-token fetch of the real host → expect `200` and the `X-Doc-Deployment` echo:

    ```bash
    curl -s -D- -o /dev/null "https://<name>.3dstories.ca/" \
      -H "CF-Access-Client-Id: $(cat ~/.secrets/doc-harness-access-client-id)" \
      -H "CF-Access-Client-Secret: $(cat ~/.secrets/doc-harness-access-client-secret)"
    ```

**A 404 through the tunnel means step 1's published route was never saved.** That is the expected
symptom, and it is the one thing in this runbook the available credential cannot check in advance:
tunnel ingress is dashboard state and `cfd_tunnel` is refused. The live fetch is the only evidence
for AC 1.

## Step 8 — the slow-client check, inherited from #34 (C4)

#34 deferred one High finding into this issue with an owner acknowledgement. waitress offers no
absolute request deadline, so `DOC_HARNESS_CHANNEL_TIMEOUT` bounds inactivity rather than total
request time, and a client that trickles bytes can hold a channel. While the harness published no
port the exposure was nil. This runbook ends that, so the check is real work:

26. **Start the observation BEFORE the first byte, and prove the observation works.** Capture in
    the harness's network namespace, filtered to destination port 8080, for the whole window. Then
    send ONE ordinary request through the tunnel as a control and confirm the capture recorded it.
    A capture that cannot see a known-good request cannot prove the absence of a bad one, so this
    control is a prerequisite and not a formality.
27. Open a connection to the public hostname and send one byte of a request header every 30
    seconds, for up to 300 seconds.
28. **Pass requires all three:** the control request appears in the capture; Cloudflare terminates
    the slow connection within 120 seconds; and no SYN or payload from the slow-client run reaches
    port 8080 across the whole window.

    **Do not count `/proc/net/tcp` lines.** An earlier revision proposed it and it cannot work: it
    counts every TCP entry in the namespace rather than bytes to port 8080, and the `HEALTHCHECK`
    runs every 10 seconds in that same namespace, leaving sockets in `TIME_WAIT`. The count moves
    on its own. There is also no per-request access log to count instead — the harness logs only
    at start-up, on an unhandled error, and on an alert.

    If the capture cannot be made to work on this host, report C4 **NOT discharged** and leave it
    a deferred High. Never report it discharged on a check that did not run.

    **This is the same origin observation step 7 item 23 needs.** One mechanism serves both
    checks, so if it cannot be established, TWO acceptance claims fail together: C4 stays
    deferred and AC 1's catch-all is UNPROVED. Solve it once, before either.

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
