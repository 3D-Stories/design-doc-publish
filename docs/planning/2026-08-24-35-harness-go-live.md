# #35 — Expose the harness at `*.3dstories.ca`

Design for the second child of #38. #34 shipped a harness that answers only on the compose
network. This child puts it on the public internet behind Cloudflare Access, and nothing else.

Proportionality note: the expected diff is roughly 150 lines across five files. This document is
deliberately short, because a design longer than the change it describes is the defect.

**Revision 2**, after the Step 4 gate. Pass 1 drew 6 self-review findings and 9 cross-model
findings; the ambiguity breaker returned `stop` and the owner resolved it. What changed is listed
under "What revision 2 added" at the end, with the criterion each addition serves.

## What the credential reality forces

The design opens here rather than ending here, because one measured fact determines the shape of
everything below.

The only Cloudflare credential this project has is the scoped API token in the Traefik container
on gateway `10.0.17.201`. Tested, not assumed (decisions D11 and D12):

| Call | Result |
| --- | --- |
| `GET /zones?name=3dstories.ca` | success — zone `ebad2c7a`, account `ac3d3263` |
| `GET /zones/<zone>/dns_records` | success |
| `GET /accounts/<account>/cfd_tunnel` | error 10000 Authentication error |
| `GET /accounts/<account>/access/apps` | error 10000 Authentication error |

The account id in rows three and four came out of the zone object, not the accounts listing, so
this is not the weaker "cannot list accounts" result. The legacy global-key path was eliminated
too: `CF_API_EMAIL` sits beside the token in `/opt/traefik/.env`, but `X-Auth-Email` plus
`X-Auth-Key` returns error 6003, so the value is a scoped token and the email is vestigial.

**Therefore: this run creates the wildcard DNS record itself. It cannot create the tunnel or the
Access application.** The owner created those two in the dashboard and delivered a
remotely-managed tunnel token, so this design consumes a token rather than a `cert.pem`.

**How the DNS call actually executes** (finding A9). The token stays on the gateway and never
travels. Every DNS call runs ON `10.0.17.201` over SSH from this host, in the shape the
`cloudflare-dns` skill prescribes:

```bash
ssh root@10.0.17.201 'bash -s' <<'REMOTE'
CF_TOKEN=$(docker exec traefik printenv CF_DNS_API_TOKEN)
[ -z "$CF_TOKEN" ] && { echo "ABORT: token empty"; exit 1; }
# ... the call, printing only Cloudflare's response ...
REMOTE
```

SSH from `10.0.17.205` to `10.0.17.201` as root is proven working — it is how every probe in the
table above was run. Reading the token requires an owner approval each time, because the auto-mode
classifier blocks `docker exec … printenv`, and that refusal is correct behavior rather than an
obstacle to route around.

## Approaches considered

**A1 — remotely-managed tunnel, token delivered as a compose file-secret. SELECTED.**
`cloudflared` joins the stack as a second service, dials outward to Cloudflare, and reaches the
harness by service name on the compose network. Ingress rules live in the Cloudflare dashboard.

**A2 — locally-managed tunnel with a committed `config.yml` and a credentials JSON. REJECTED, and
the reason is a capability, not a preference.** Creating a locally-managed tunnel requires either
`cloudflared tunnel login`, which is an interactive browser flow, or account-level `cfd_tunnel`
API access. Neither exists here, and no `cert.pem` or credentials JSON is present on either box.
A2 is the better shape on paper — ingress would be a reviewable file in git rather than dashboard
state — and it is worth revisiting the day a tunnel-scoped token exists. Recorded as a follow-up
rather than silently dropped.

**A3 — put the harness behind the existing Traefik on the gateway instead of a tunnel. REJECTED.**
The issue's scope names a Cloudflare tunnel and Access explicitly, and Traefik would require
publishing a host port. #34's entire safety argument rests on the harness publishing none.

## What A2's rejection costs, stated plainly

AC 1 asks for "ingress: `*.3dstories.ca` -> harness, with a catch-all 404 rule". With a
remotely-managed tunnel that ingress is dashboard state, so it cannot be a committed file. The
committed **runbook** carries the exact ingress specification instead, so the intent is reviewable
in git even though the mechanism is not. That is a real reduction in reviewability and it is the
price of the credential situation, not a design preference.

## The change

### 1. `compose.yaml` — the cloudflared service

```yaml
  cloudflared:
    image: cloudflare/cloudflared@sha256:0aa26e284f05e6c77ae375b8c9c11d9eb6a448fb7bcd8d40f31cb6176189eb38
    restart: unless-stopped
    command: ["tunnel", "--no-autoupdate", "run"]
    environment:
      TUNNEL_TOKEN_FILE: /run/secrets/tunnel_token
    secrets:
      - tunnel_token
    depends_on:
      harness:
        condition: service_healthy

secrets:
  tunnel_token:
    file: ${DOC_HARNESS_TUNNEL_TOKEN_FILE:?set DOC_HARNESS_TUNNEL_TOKEN_FILE}
```

Four things here are deliberate.

**The top-level `secrets:` block is part of the change, not an implied detail** (finding A1). A
service referencing an undeclared secret makes compose reject the file outright, so cloudflared
would never start. This was missing from revision 1 and it is the finding that would have broken
the deploy.

**The token arrives as a FILE, not an environment variable.** `docker inspect` prints a
container's environment, so a token in `environment:` is readable by anything that can talk to the
Docker socket. `--token-file` and its `TUNNEL_TOKEN_FILE` env form both exist — verified by probe
below — so the token sits in a `secrets:` mount at `/run/secrets/tunnel_token` and never enters
the repo, the compose file, or the container environment.

**The secret's PATH comes from a required-substitution env var** (finding S3), matching the pattern
`compose.yaml` already uses for the two harness secrets. The token file lives at
`~/.secrets/doc-harness-tunnel-token`, outside the repo, and hardcoding one operator's home
directory into a tracked file would be a host-specific value in shared source.

**The image is pinned by digest, not `:latest`** (findings S6 and A7, one merged finding). This
project pins every runtime dependency exactly and `test_the_requirement_is_pinned_exactly` asserts
it. `--no-autoupdate` does not stop a later pull from resolving a different image, so a moving tag
would let the stack's behavior change without a commit. That digest is `cloudflared version
2026.8.2`, read from the pulled image, and it is the exact binary whose `--token-file` behavior was
probed. Update it only through a reviewed re-probe.

**`depends_on: service_healthy`** is why the Dockerfile gains a healthcheck. Without it cloudflared
starts advertising a route to a harness that has not finished taking its cache lock.

**Still no published ports.** cloudflared dials outward, so `test_it_publishes_no_host_ports`
keeps passing unchanged. #34's safety argument is not weakened by this child; it is replaced by a
stronger one, because Access now sits in front.

### 2. `Dockerfile` — a healthcheck with no new request surface

```dockerfile
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python3", "-c", "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()"]
```

This resolves the advisory #34 declined into this child, and it resolves it the way #34's reasoning
demanded. A healthcheck needs something to probe, and adding an unauthenticated `/health` route to
a service whose whole design is that only two gated hosts answer would have been a new request
surface no criterion asked for. A TCP connect from inside the container proves the listener is
accepting without adding any route at all. Verified by probe: the command exits 1 when nothing
listens, which is the correct unhealthy signal.

**Why a TCP accept is a sufficient readiness signal here, checked rather than assumed** (finding
A8, refuted). The concern was that the listener might bind before initialization, making the
container look healthy during exactly the window this exists to prevent. `harness/__main__.py:47-58`
shows `build()` completing `take_cache_lock`, `registry.initialize()` and `cache.initialize()` and
RETURNING before `main()` reaches `waitress.serve()` at line 73. The listener cannot bind early, so
an accepting socket does imply initialization completed.

**The loopback coupling** (finding S5). The check connects to `127.0.0.1:8080` and the harness binds
`DOC_HARNESS_BIND`, default `0.0.0.0:8080` (`harness/config.py:79`), which accepts on loopback.
Narrowing that bind to one interface breaks the healthcheck silently, and because cloudflared uses
`service_healthy` the tunnel would then never start. Change both in the same commit or neither.

### 3. `docs/runbooks/2026-08-24-35-harness-go-live.md` — the runbook (AC 5)

New directory. Carries, each with a one-line undo: the dashboard steps for the tunnel and the
Access application; the ingress specification A2 would have committed as a file, including that the
service URL is `harness:8080` and never `localhost:8080`; the wildcard DNS record as the exact API
call; the service-token headers `CF-Access-Client-Id` and `CF-Access-Client-Secret` with their
value locations named (finding S4 — #36 consumes the same two); the healthcheck loopback coupling;
and the C4 slow-client test with the numbers below.

### 4. `tests/harness/test_entrypoint.py` — grow the guard

`TestComposeAndDockerfile` already reads both files, so it is the right home. New assertions: the
cloudflared service exists; the image is pinned by digest and is NOT `:latest`; a top-level
`secrets:` block declares `tunnel_token`; the token is NOT an environment VALUE; the secret file
path comes from a required-substitution env var; `depends_on` requires `service_healthy`; the
Dockerfile declares a `HEALTHCHECK`; and the no-published-ports invariant still holds with two
services.

### 5. `README.md` — a go-live subsection under the existing harness section.

## The C4 prerequisite, with numbers (finding A4)

#34 deferred one High finding into this child with an owner acknowledgement: waitress offers no
absolute request deadline, so `DOC_HARNESS_CHANNEL_TIMEOUT` bounds inactivity rather than total
request time, and a trickling client can hold a channel. #34's exposure was nil because it
published no port. This child ends that, so the check is real work here — and revision 1 stated it
without a way to pass or fail it, which is what A4 caught.

The test, executable as written:

- **Client behavior:** send one byte of a request header every **30 s**.
- **Maximum acceptable termination time: 120 s** from the first byte. Cloudflare must close the
  connection within that window.
- **Total observation window: 300 s.** If the connection is still open at 300 s, the test FAILS.
- **Origin-side assertion:** sample the harness's accepted-connection count immediately before the
  test and at every 30 s tick, with
  `docker compose exec harness python3 -c "import socket; print(open('/proc/net/tcp').read().count('\n'))"`
  as the crude channel count, or the container's own log line count for accepted requests.
  **The count must not rise at any tick.** A single increment means a byte reached the origin and
  the test FAILS regardless of when Cloudflare closes.
- **Pass requires both:** terminated within 120 s AND the origin count unmoved across the whole
  window.

## platform_apis

Every load-bearing platform claim below was probed live, with the exact invocation the design
ships, on 2026-08-24.

- **`cloudflared` accepts a tunnel token, and accepts it as a FILE.**
  `docker run --rm cloudflare/cloudflared:latest tunnel run --help` lists `--token value`
  (`$TUNNEL_TOKEN`) and `--token-file value` (`$TUNNEL_TOKEN_FILE`). The file form is what made the
  secrets-mount design possible; without the probe this would have shipped the token in an
  environment variable.
- **Compose v5.5.0 supports file-based secrets, rendering to `/run/secrets/<name>`.**
  `docker compose config` on a probe file containing `secrets: {t: {file: ...}}` rendered
  `source: t, target: /run/secrets/t`. Verified against the real binary on this host.
- **The healthcheck command runs in the harness base image and fails correctly.**
  `docker run --rm python:3.12-slim python3 -c "socket.create_connection(('127.0.0.1',8080),2)"`
  raised `ConnectionRefusedError` with nothing listening.
- **The tunnel EXISTS and its token belongs to this account.** Decoding the delivered token's
  non-secret `t` field yields tunnel `85f6194f-3347-44b4-84c3-3bbcfbb076bb`, and its `a` field is
  `ac3d326308ffea9fb4bd02f4c9cf023c`, which equals the account id the zone object reports. No
  account-scoped API call was needed to learn either.
- **DNS WRITE capability is a PREREQUISITE, proved by a disposable spike, not inferred from a
  read** (finding A2). A successful `GET` on `dns_records` proves read, not write. Before the real
  create, the apply step creates a throwaway `TXT` record named `_doc-harness-spike`, asserts
  Cloudflare's response reports `success: true`, then DELETEs it and asserts that too. **If either
  call does not report success, the apply ABORTS and AC 2 is reported blocked** — it does not
  proceed to the real record on the strength of a read.
- **The tunnel's INGRESS configuration is NOT verifiable with the available credential** (finding
  S2). `cfd_tunnel` is refused, so this run cannot read which routes the tunnel serves. The live
  proof in AC 4 is therefore the ONLY evidence for AC 1. **A 404 through the tunnel is the expected
  symptom if the published application route was never saved**, and that diagnosis belongs at the
  live step rather than in an earlier guess.
- **This session is on the host AC 1 names.** `hostname` is `claude-code`, `ip addr` shows
  `10.0.17.205`, Docker Compose is v5.5.0, and port 8080 is not listening on the host.

## Acceptance criteria mapping

| AC | Where it lands | How it is proved |
| --- | --- | --- |
| 1 | `compose.yaml` cloudflared service; ingress specified in the runbook | `test_entrypoint.py` for the service; the live proof for the ingress, which is its only possible evidence |
| 2 | the wildcard CNAME, created by this run after the write spike passes | `dig` against two resolvers, then the live fetch |
| 3 | Access application and its two policies, created by the owner in the dashboard | an anonymous fetch getting the Access login page |
| 4 | the live proof itself | a service-token request returning 200 plus the `X-Doc-Deployment` echo |
| 5 | `docs/runbooks/2026-08-24-35-harness-go-live.md` | reading it; secrets by NAME only, one undo per step |

**AC 2 has no fallback, deliberately** (finding A5). Revision 1 offered per-host records if
Cloudflare refused the wildcard. That silently redefines the criterion, which asks for a wildcard
CNAME, and would let the rollout report success while AC 2 was false. **If the wildcard is refused,
stop and report AC 2 blocked.** Per-host records are acceptable only if the owner amends AC 2. This
is distinct from AC 3, whose own text explicitly permits exact-host Access entries as a fallback.

## What revision 2 added, and the criterion each addition serves

| Addition | Serves |
| --- | --- |
| the top-level `secrets:` declaration | AC 1 — without it compose rejects the file |
| the digest pin | AC 1 — a runtime dependency this project pins exactly |
| the secret path as a required env var | AC 5 — no host-specific value in a tracked file |
| the DNS-apply execution path over SSH | AC 2 — names the mechanism rather than assuming it |
| the DNS write spike as a prerequisite | AC 2 — turns a read-inferred claim into a measured one |
| the ingress-unverifiable declaration | AC 1 and AC 4 — declares the gap instead of omitting it |
| the C4 numbers and origin-side assertion | AC 4 — makes the check able to fail |
| the AC 2 no-fallback rule | AC 2 — stops a false success |
| the service-token header and value names | AC 4 and AC 5 |
| the healthcheck loopback coupling note | AC 1 |
| the startup-order citation | AC 1 |

No component here serves no criterion, so revision 2 adds no scope.

## Findings disposed without a change

- **A3 — asked for proof the tunnel and Access application can be created. MOOT.** Both exist: the
  tunnel id was decoded from the delivered token, and the owner reported the wildcard Access
  hostname accepted. The review's snapshot predates both.
- **A8 — argued the healthcheck could report healthy before initialization. REFUTED** at
  `harness/__main__.py:47-58` and `:73`, cited in section 2.
- **A6 — asked for a full Access policy matrix with precedence and per-path testing. DECLINED,
  owner decision.** The two policies were built by hand minutes before this revision; the runbook
  names both actions and both include rules; and the live proof exercises exactly the two paths
  that matter, an anonymous request getting the login page and a service-token request getting 200.
  A precedence table for two policies would also be a transcription of dashboard state this run
  cannot read back, so it could drift with nothing to catch it. Recorded rather than silently
  dropped.

## What is deferred, and to where

Nothing new is deferred. The C4 check that #34 deferred is DISCHARGED here, with numbers. A2's
committed-ingress advantage is a follow-up for the day a tunnel-scoped token exists.
