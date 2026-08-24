# #35 — Expose the harness at `*.3dstories.ca`

Design for the second child of #38. #34 shipped a harness that answers only on the compose
network. This child puts it on the public internet behind Cloudflare Access, and nothing else.

Proportionality note, and revision 3 breaks it. The expected diff is still roughly 150 lines
across five files, but this document is now longer than that, and the rule says a design longer
than its own change is the defect. Stated rather than quietly dropped. Where the length went: a
live regression that had to be recorded with its measurements, two probes that had to be re-run
because the recorded evidence was wrong, and two criteria whose preconditions were missing. None
of it is commentary. The parts that would be commentary — the approach comparison and the
disposed-findings trail — are kept because a later reader needs to know what was refused and why,
which is the one thing a short document cannot reconstruct.

**Revision 4**, after Step 4 pass 3, at which the design gate CLOSED budget-exhausted. Pass 3
drew 9 findings (1 self-review, 8 cross-model), the ambiguity breaker returned `settle`, and the
design loop-back budget was spent, so this is the last design pass. A budget-exhausted close is a
legitimate WF2 outcome, not an error — but it means the two things marked "owner's call" below
genuinely are, and Step 5 onward proceeds around them rather than through them.

Its predecessor, **revision 3**, was written after Step 4 pass 2. Pass 2 drew 5 self-review findings and 6 cross-model
findings. One is Critical and it is not a hypothetical: **the Access application this issue
created is, right now, serving a login page in front of `www.3dstories.ca`, a host that has
nothing to do with this epic.** That is measured below and it drove this revision. What changed is
listed under "What revision 3 added" at the end, with the criterion each addition serves.

## STOP — a live regression this issue already caused (finding S1, Critical)

This is first because it is true right now, not because it is the most interesting part.

**`www.3dstories.ca` currently serves a Cloudflare Access login page instead of its site.**
Measured on 2026-08-24, not inferred:

| Probe | Result |
| --- | --- |
| `dig +short @1.1.1.1 www.3dstories.ca` | `172.67.197.153`, `104.21.36.169` — Cloudflare anycast, so `www` **is proxied** |
| `curl -sD- https://www.3dstories.ca/` | `HTTP/2 302` → `billowing-cake-90b6.cloudflareaccess.com/cdn-cgi/access/login/www.3dstories.ca` |
| the page that follows | `HTTP/2 200`, response header **`cf-access-domain: *.3dstories.ca`**, title `Sign in ・ Cloudflare Access` |

That response header names the culprit. The wildcard Access application created for the doc
harness on 2026-08-24 matches every subdomain of the zone, and `www` is one of them.

**AC 3 predicted this exactly and revision 2 walked past it.** Its text reads: "one wildcard
Access app **if nothing else is proxied on subdomains**, else exact-host entries." Something else
IS proxied on a subdomain. The inventory that gates that branch was never performed, by revision 1
or revision 2, and no inventory is recorded anywhere in this design. AC 2 asks for the same
inventory before the DNS write, and it is missing there too (pass-2 finding S4).

**Revision 2's AC 3 proof would have reported SUCCESS on this.** Its evidence was "an anonymous
fetch getting the Access login page" — which is precisely what `www` now returns. A check that
cannot tell the intended outcome from the regression is not a check.

### What changes because of it

1. **AC 3 cannot take its exact-host branch cleanly, and revision 4 stops pretending otherwise**
   (self-review C1, cross-model B3). Revision 3 said "exact hosts, one entry per published doc
   name" and that remedy is itself broken. A wildcard DNS record and a wildcard tunnel route make
   **every** `*.3dstories.ca` name servable; a hand-maintained Access list decides which of them
   are *protected*; and doc names are published dynamically, so the list always lags. A new
   document would be reachable with nothing in front of it. That trades a fail-CLOSED defect for
   a fail-OPEN one, which is worse in kind — and it is a hole this design introduced, not one it
   inherited.

   **The two coherent shapes, and only the owner can pick between them**, because one of them
   amends a criterion:

   | | Option A — narrow the wildcard | Option B — keep AC 2 verbatim |
   | --- | --- | --- |
   | DNS | `*.docs.3dstories.ca` | `*.3dstories.ca` as written |
   | Access | ONE wildcard app over `*.docs.3dstories.ca` | exact-host entries, maintained |
   | Can it capture `www`? | **No — structurally impossible** | No, but only while the list is right |
   | New doc published | protected automatically | **unprotected until someone adds an entry** |
   | Cost | **amends AC 2's text**, owner decision | needs the lifecycle contract below, forever |

   **Option A is the recommendation.** It removes the failure mode rather than policing it, and
   the thing it costs — one word in AC 2 — is cheaper than a permanent maintenance obligation on
   a security boundary. It is NOT taken unilaterally: amending an acceptance criterion is the
   owner's call, and they are asleep.

   **If Option B is chosen, it carries a mandatory Access host lifecycle contract** (B3), and
   without that contract Option B is not acceptable at all: maintain an authoritative
   published-host inventory; create and VERIFY the exact-host Access entry **before** the host
   becomes servable; fail the publication if the entry cannot be verified; and re-assert after
   publication that the new host answers with Access in front of it.
2. **The zone inventory becomes a recorded precondition**, with a section of its own below. No
   Access application and no DNS write happens before it exists in writing.
3. **A regression assertion joins the live proof — and it checks RESTORATION, not merely the
   absence of Access** (finding B6). "No interstitial" is satisfied by a 404, a 5xx, a wrong
   origin or an unrelated redirect, every one of which leaves the user-visible regression in
   place in another form. So the assertion records a site invariant BEFORE the Access edit — the
   expected final status, the redirect target if any, and one stable site-specific response
   marker — and requires all of them afterwards, **plus** the absence of any `cf-access-domain`
   header. Go-live FAILS otherwise.

   One honest caveat on the "before" half: the pre-change state cannot be captured now, because
   `www` is ALREADY behind Access. The invariant must come from the owner or from whatever serves
   that host, and if no invariant can be established, the check degrades to "answers 200 without
   `cf-access-domain`" and that weakening is recorded rather than glossed.

### What this design cannot fix, and who must

Narrowing the Access application is dashboard work. `GET /accounts/<id>/access/apps` returns
error 10000 to this run's credential, so this run cannot read the application, let alone edit it.
**The owner must narrow the application's public hostname.** Recorded as decision D15 with its
one-step undo. Nothing in this repository is in a bad state; the regression lives entirely in
Cloudflare's dashboard configuration.

**And that dashboard change is itself unproven for the shape being asked for** (finding B7). The
only evidence on record is that a WILDCARD hostname was accepted. Nothing shows that this
application can be converted to the target shape, that every entry saves, or that the two
policies stay attached across the edit — and this run cannot read the application back to check.
So the owner's edit is a **go-live prerequisite with its own verification**, not a step assumed to
work: configure the target hostname set, capture the resulting host and policy configuration, and
verify each intended host plus `www` **before** any DNS or compose apply runs.

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

**How the DNS call actually executes** (pass-1 finding A9). The token stays on the gateway and never
travels. Every DNS call runs ON `10.0.17.201` over SSH from this host, in the shape the
`cloudflare-dns` skill prescribes:

```bash
ssh root@10.0.17.201 'bash -s' <<'REMOTE'
CF_TOKEN=$(docker exec traefik printenv CF_DNS_API_TOKEN)
[ -z "$CF_TOKEN" ] && { echo "ABORT: token empty"; exit 1; }
# ... the call, printing only Cloudflare's response ...
REMOTE
```

**That shape works, but it is not available in every session, and revision 3 has to say so.**
Every probe in the table above was run exactly that way, from a session where the owner approved
it. In the session writing revision 3 it is refused: the Claude Code auto-mode permission
classifier blocked BOTH the full call and a bare `ssh root@10.0.17.201 'hostname'` diagnostic that
carries no credential at all. So what is blocked is **ssh to that host**, not merely the
`docker exec … printenv` that reads the token.

The refusal is correct behavior and is not routed around. Reading `/opt/traefik/.env` instead, or
any other path to the same secret, serves the exact intent the classifier protects. Recorded as
decision D16.

**Consequence, stated here rather than discovered at the apply:** in a session without that
permission, AC 2 cannot be applied and AC 4 cannot be proved, because nothing resolves until the
record exists. Confirmed still absent on 2026-08-24 — `dig +short @1.1.1.1` returns NXDOMAIN for
`test`, `docs-index` and `docs-control` on this zone. The honest outcome there is to report AC 2
blocked, not to find another way to the token.

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
    profiles: ["tunnel"]          # opt-in; see "the local path" below
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

**The top-level `secrets:` block is part of the change, not an implied detail** (pass-1 finding A1). A
service referencing an undeclared secret makes compose reject the file outright, so cloudflared
would never start. This was missing from revision 1 and it is the finding that would have broken
the deploy.

**The token arrives as a FILE, not an environment variable.** `docker inspect` prints a
container's environment, so a token in `environment:` is readable by anything that can talk to the
Docker socket. `--token-file` and its `TUNNEL_TOKEN_FILE` env form both exist — verified by probe
below — so the token sits in a `secrets:` mount at `/run/secrets/tunnel_token` and never enters
the repo, the compose file, or the container environment.

**The tunnel is an OPT-IN PROFILE, and that is a defect this design caused and then caught.**
Neither review pass raised it; testing the README's own documented command did. #34 documents
running the harness locally with **no Cloudflare at all**, and a top-level `secrets:` block is
interpolated whatever profile is active — so the required-substitution form below made plain
`docker compose config` fail with `required variable DOC_HARNESS_TUNNEL_TOKEN_FILE is missing a
value` for anyone who just wanted the harness. Measured, then fixed, then measured again:
`docker compose config --services` with no tunnel variable now prints `harness` and exits 0,
and `--profile tunnel` prints `harness` and `cloudflared` and exits 0.

The secret's default is a repo-relative placeholder that does not exist, deliberately, so nothing
silently mounts the wrong file: bringing the tunnel profile up without setting the variable fails
on a missing file that names itself.

**The secret's PATH still comes from a substitution rather than a literal** (pass-1 finding S3). The token file lives at
`~/.secrets/doc-harness-tunnel-token`, outside the repo, and hardcoding one operator's home
directory into a tracked file would be a host-specific value in shared source.

It no longer matches the two harness secrets exactly, and the difference is worth naming rather
than glossing: those use the required `:?` form, this one uses `:-` with a placeholder default.
The reason is the interpolation asymmetry above — an `environment:` value is only interpolated
for a service that is actually starting, while a top-level `secrets:` entry is interpolated
always. The required form is right for the first and wrong for the second.

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
accepting without adding any route at all. Measured in BOTH states on the harness base image
(revision 3, correcting an invalid probe — see `platform_apis`): **exit 1** with nothing listening
and **exit 0** with a listener on `127.0.0.1:8080`.

**Why a TCP accept is a sufficient readiness signal here, checked rather than assumed** (pass-1 finding
A8, refuted). The concern was that the listener might bind before initialization, making the
container look healthy during exactly the window this exists to prevent. `harness/__main__.py:47-58`
shows `build()` completing `take_cache_lock`, `registry.initialize()` and `cache.initialize()` and
RETURNING before `main()` reaches `waitress.serve()` at line 73. The listener cannot bind early, so
an accepting socket does imply initialization completed.

**The loopback coupling** (pass-1 finding S5). The check connects to `127.0.0.1:8080` and the harness binds
`DOC_HARNESS_BIND`, default `0.0.0.0:8080` (`harness/config.py:79`), which accepts on loopback.
Narrowing that bind to one interface breaks the healthcheck silently, and because cloudflared uses
`service_healthy` the tunnel would then never start. Change both in the same commit or neither.

### 3. `docs/runbooks/2026-08-24-35-harness-go-live.md` — the runbook (AC 5)

New directory. Carries, each with a one-line undo:

- **Step 0, the zone inventory** — added in revision 3, and placed first because steps 2 and 4
  are both unanswerable without it.
- the dashboard steps for the tunnel, and for the Access application — which **stops at the
  scope decision rather than prescribing either branch**, because one of them is an
  authentication bypass and the other amends a criterion.
- the ordering the review corrected: the service token is created BEFORE the policy that selects
  it, and the stack is brought up and its secret proven BEFORE any production DNS write.
- the ingress specification A2 would have committed as a file, including that the service URL is
  `harness:8080` and never `localhost:8080`.
- the DNS record as an exact API call, **plus the reconciliation rule** — create, no-op on an
  exact match, abort on a conflict — so a timed-out write cannot double-create.
- the service-token headers `CF-Access-Client-Id` and `CF-Access-Client-Secret` with their value
  locations named (pass-1 finding S4 — #36 consumes the same two).
- the verification steps, **including the three negative checks revision 3 added**: `www` must
  answer WITHOUT Access, an unconfigured hostname must 404, and `docs-index` and `docs-control`
  are checked by name.
- the healthcheck loopback coupling, and the rewritten C4 slow-client test.

### 4. `tests/harness/test_entrypoint.py` — grow the guard

`TestComposeAndDockerfile` already reads both files, so it is the right home. New assertions: the
cloudflared service exists; the image is pinned by digest and is NOT `:latest`; a top-level
`secrets:` block declares `tunnel_token`; the token is NOT an environment VALUE; the secret file
path comes from a required-substitution env var; `depends_on` requires `service_healthy`; the
Dockerfile declares a `HEALTHCHECK`; and the no-published-ports invariant still holds with two
services.

**These are static file assertions, and revision 4 adds the runtime one they cannot make**
(finding B8). Every item above reads text; none proves the pinned container can actually READ the
mounted secret, or that the token stays out of `docker inspect`. Those two were listed under
`platform_apis` as explicitly unproven and then appeared in no test and no acceptance proof, which
is how an unproven property becomes an accepted one by default. So a **real-secret compose smoke
test becomes part of AC 1's proof**, run before any live DNS work: bring the stack up with the
real secret file at its intended mode; assert cloudflared reaches a running state with no
token-read error in its logs; assert the token value appears in neither `docker inspect` nor the
rendered `docker compose config`; and **abort before the DNS apply if either fails**.

### 5. `README.md` — a go-live subsection under the existing harness section.

## The C4 prerequisite, with numbers (pass-1 finding A4)

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
- **Origin-side assertion — rewritten in revision 3, because revision 2's could not be run**
  (self-review S2 and cross-model A1, found independently by two passes, so this is confirmed
  rather than plausible). Revision 2 offered two measurements and **neither works**:
  - Counting `/proc/net/tcp` lines counts every TCP table entry in the namespace, not bytes
    delivered to port 8080. Worse, it is polluted by the `HEALTHCHECK` **this same design adds**
    at `--interval=10s`: each check opens a loopback connection in that same namespace and the
    closed socket lingers in `TIME_WAIT`, so the count moves on its own. "The count must not rise
    at any tick" could never hold, and a 30 s sample can also miss a short-lived connection
    entirely — so the check could fail spuriously AND pass while the client reached the origin.
  - "The container's own log line count for accepted requests" **does not exist.** The harness has
    exactly four log sites — `harness/__main__.py:65` and `:71`, and `harness/app.py:100`
    (unhandled error only) and `:107` (only when `response.alert` is set). None is an access log.

  **The replacement is specified but NOT yet executable, and revision 4 says so rather than
  shipping a placeholder** (finding B2, and it was right). Revision 3 printed a fenced block that
  contained only a comment — pseudocode dressed as a command. `python:3.12-slim` carries no
  `tcpdump`, and the harness container runs as an unprivileged user, so packet capture inside its
  namespace is not simply available. **No capture command has been proven on this host.**

  What the assertion must do, once a mechanism exists: observe continuously in the harness's
  network namespace for the whole window, filtered to destination port 8080, distinguishing
  loopback (the healthcheck) from tunnel traffic. Candidate mechanisms, none yet probed: a
  sidecar sharing `network_mode: service:harness` with `tcpdump` installed; `conntrack` on the
  host; or a counter added to the harness itself, which is #34 code and out of this issue's scope.

  The mechanism is **a prerequisite of the test, not an assumption**: whichever is chosen, run one
  *control* request through the tunnel first and assert the capture records it. A capture that
  cannot see a known-good request cannot prove the absence of a bad one.
  - **Pass requires:** the control request appears in the capture, the slow client is terminated
    within 120 s, and **no SYN or payload attributable to the slow-client run reaches port 8080**
    across the whole 300 s window.
  - If the capture mechanism cannot be made to work on the host, C4 is reported **NOT
    discharged** and stays a deferred High. It is never reported discharged on an assertion that
    was not run.

## The zone inventory, which is a precondition and not a courtesy (pass-2 findings S4 and A4)

AC 2 says the wildcard CNAME is created "AFTER a zone inventory", and AC 3 makes the Access
layout depend on what that inventory shows. Revision 2 recorded no inventory — the only trace was
a record count of 23 in the runbook, mentioned in passing. Finding S1 is what that omission cost.

**The inventory is a written artifact, produced before either apply**, listing every record in
zone `ebad2c7a` with its name, type and `proxied` flag. `GET /zones/<zone>/dns_records` is
available to this run's credential, so this is a read the run can do — subject to the SSH
constraint recorded in decision D16.

The apply refuses to proceed unless the inventory exists and has been read. Two things it must
answer explicitly, because these are the two questions the criteria actually turn on:

1. **Which subdomains are already proxied?** Each one is a host the wildcard Access application
   would capture. Known already, without the full inventory: `www` is proxied.
2. **Does any explicit record already exist at `*`?** If one does, the create is a conflict, not
   a create.

### The DNS record contract (finding A4)

Revision 2 said "create the wildcard CNAME" and left the payload to the implementer. The exact
record, and the reconciliation rule:

| Field | Value |
| --- | --- |
| `type` | `CNAME` |
| `name` | `*` (renders as `*.3dstories.ca`) |
| `content` | `85f6194f-3347-44b4-84c3-3bbcfbb076bb.cfargotunnel.com` |
| `proxied` | `true` — the traffic must reach the Cloudflare edge or Access never applies |
| `ttl` | `1` (automatic; required when proxied) |
| `comment` | under 100 characters, or Cloudflare rejects the request with code 9313 |

**Reconciliation, in this order.** Look up `*` first. If no record exists, create it. If one
exists and every field above already matches, that is a **no-op success**, not an error — a retry
after a timed-out write must not double-create. If one exists and any field differs, **ABORT and
report the difference**; never overwrite a record this run did not create. After a create, assert
the returned record's fields against the table before running `dig` or any HTTP check, because
Cloudflare reporting `success: true` is not the same as the record being the one that was asked
for.

## platform_apis

Every load-bearing platform claim below was probed live on 2026-08-24. Revision 3 tightened what
"live" means here, because pass 2 caught two bullets that did not meet it: one probed a different
image from the one shipped, and one quoted a command that could not have produced its stated
result. Both are re-run below. **Where a claim is still NOT proven, it says so instead of being
dropped** — see the second bullet.

**Finding ids below carry their pass**, because pass 1 and pass 2 both used the labels A2, A5, A6
and S2 for different findings.

- **`cloudflared` accepts a tunnel token as a FILE — re-probed in revision 3 on the PINNED
  DIGEST** (pass-2 finding A5). Revision 2 probed `cloudflare/cloudflared:latest`, which is not the image
  this design ships, so the evidence did not cover the shipped invocation. Re-run against
  `cloudflare/cloudflared@sha256:0aa26e28…`, the exact digest in `compose.yaml`:
  `docker run --rm <digest> tunnel run --help` prints, verbatim,
  `--token-file value  Filepath at which to read the tunnel token. … [$TUNNEL_TOKEN_FILE]`.
  The same digest reports `cloudflared version 2026.8.2 (built 2026-08-14-12:28 UTC)`.
  **One thing the re-probe taught that the design must respect:** the help text says `--token`
  "takes precedence over token-file". So exactly ONE of `TUNNEL_TOKEN` and `TUNNEL_TOKEN_FILE` may
  ever be set, and `compose.yaml` sets only the file form.
- **What the digest probe still does NOT prove**, stated rather than glossed (rest of pass-2 A5): that
  the pinned container can actually READ a host secret at the intended ownership and mode, and
  that `docker inspect` carries no token value. Neither is knowable from `--help`. Both become
  explicit assertions in the implementation's compose smoke test, run with the real secret file
  before any live fetch — not claims made here.
- **Compose v5.5.0 supports file-based secrets, rendering to `/run/secrets/<name>`.**
  `docker compose config` on a probe file containing `secrets: {t: {file: ...}}` rendered
  `source: t, target: /run/secrets/t`. Verified against the real binary on this host.
- **The healthcheck command behaves correctly in BOTH states — corrected and re-run in revision
  3** (pass-2 finding A6, and the reviewer was exactly right — not to be confused with pass-1's
  A6, the declined Access policy matrix). Revision 2's quoted probe omitted
  `import socket`, so as written it raises `NameError`, not the `ConnectionRefusedError` it
  claimed. The evidence was invalid even though the shipped `HEALTHCHECK` line does import the
  module. Corrected and re-run on `python:3.12-slim`, the harness base image, in both states:
  - **nothing listening** → `ConnectionRefusedError: [Errno 111] Connection refused`, **exit 1**
    — the correct unhealthy signal.
  - **a listener on `127.0.0.1:8080`** → **exit 0** — the correct healthy signal.

  Revision 2 recorded only a negative case, and recorded it wrongly. Both are now measured.
- **The tunnel EXISTS and its token belongs to this account.** Decoding the delivered token's
  non-secret `t` field yields tunnel `85f6194f-3347-44b4-84c3-3bbcfbb076bb`, and its `a` field is
  `ac3d326308ffea9fb4bd02f4c9cf023c`, which equals the account id the zone object reports. No
  account-scoped API call was needed to learn either.
- **DNS WRITE capability is a PREREQUISITE, proved by a disposable spike, not inferred from a
  read** (pass-1 finding A2). A successful `GET` on `dns_records` proves read, not write. Before the real
  create, the apply step creates a throwaway `TXT` record named `_doc-harness-spike`, asserts
  Cloudflare's response reports `success: true`, then DELETEs it and asserts that too. **If either
  call does not report success, the apply ABORTS and AC 2 is reported blocked** — it does not
  proceed to the real record on the strength of a read.
  **The spike cleans up after itself, including when it fails** (finding B5). Revision 3's bare
  "abort on failure" would leave the throwaway record sitting in a production zone whenever the
  DELETE failed or its response was lost — the one case cleanup matters. So: keep the created
  record's id; retry the DELETE and read back to confirm it is gone; and if cleanup still cannot
  be confirmed, abort while **printing the exact record id and the manual removal step**. A later
  run reconciles any pre-existing `_doc-harness-spike` before creating a new one.
- **The tunnel's INGRESS configuration is NOT verifiable with the available credential** (finding
  pass-1 S2). `cfd_tunnel` is refused, so this run cannot read which routes the tunnel serves. The live
  proof in AC 4 is therefore the ONLY evidence for AC 1. **A 404 through the tunnel is the expected
  symptom if the published application route was never saved**, and that diagnosis belongs at the
  live step rather than in an earlier guess.
- **This session is on the host AC 1 names.** `hostname` is `claude-code`, `ip addr` shows
  `10.0.17.205`, Docker Compose is v5.5.0, and port 8080 is not listening on the host.

## Acceptance criteria mapping

| AC | Where it lands | How it is proved |
| --- | --- | --- |
| 1 | `compose.yaml` cloudflared service; ingress specified in the runbook | `test_entrypoint.py` for the service; for the ingress, the live proof — **and its catch-all half needs its own negative request**, see below |
| 2 | the wildcard CNAME, created after BOTH the zone inventory and the write spike pass | the record contract asserted field-by-field, then `dig` against two resolvers, then the live fetch |
| 3 | Access application, scope **pending the owner's Option A / Option B decision** — see the fork above | an anonymous fetch of each protected host **by name** getting the login page; `www.3dstories.ca` proving RESTORATION, not merely the absence of Access; and an authenticated identity outside every include rule being DENIED |
| 4 | the live proof itself | a service-token request returning 200 plus the `X-Doc-Deployment` echo |
| 5 | `docs/runbooks/2026-08-24-35-harness-go-live.md` | reading it; secrets by NAME only, one undo per step |

**AC 1's catch-all needs a NEGATIVE request** (pass-2 finding A2). The live proof in revision 2 only ever
asked for the configured harness hostname. A tunnel that mistakenly routed *every*
`*.3dstories.ca` name to the harness would have passed that proof unchanged, so AC 1's "catch-all
404 rule" was never actually tested. The proof now includes a service-token request to an
unconfigured name — `unconfigured-probe.3dstories.ca` — which must return **404 with no
`X-Doc-Deployment` header and no corresponding request at the harness**. Any other result is a
failed go-live.

**"No corresponding request at the harness" needs a mechanism, and it has the same unsolved one
as C4** (finding B1). Without origin observation, a misconfigured wildcard route that DOES reach
the harness and gets an origin-generated 404 is indistinguishable from the tunnel's catch-all
doing its job — the check would pass on the failure it exists to catch. So this assertion is
bound to C4's mechanism: same capture, same control request. **If no origin observation can be
established, AC 1 is reported UNPROVED.** A bare 404 is not accepted as evidence for it. This matters more than it looks, because the tunnel's Published application route
shows a literal `*` in its Path column where Cloudflare's help text says to leave it empty; that
field is a regex and `*` is not a meaningful one. This negative request is what would catch it.

**AC 2 has no fallback, deliberately** (finding A5 of pass 1). Revision 1 offered per-host records if
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

## What revision 3 added, and the criterion each addition serves

| Addition | Serves |
| --- | --- |
| the live-regression section and its three measured probes | AC 3 — names a criterion violation that is already in production |
| the Access layout raised as an explicit owner fork, not silently decided | AC 3 — revision 3 picked exact hosts and that branch is fail-open; revision 4 refuses to pick |
| the `www.3dstories.ca`-answers-without-Access assertion | AC 3 — the check that distinguishes the intended outcome from the regression |
| `docs-index` and `docs-control` named in the AC 3 proof | AC 3 — the criterion names them, so the proof must too |
| the zone inventory as a written precondition | AC 2 and AC 3 — both criteria gate on it and neither had it |
| the DNS record contract and its reconciliation rule | AC 2 — an exact payload and a retry that cannot double-create |
| the unconfigured-hostname negative request | AC 1 — the catch-all half, which had no test at all |
| the rewritten C4 origin assertion, continuous and probe-first | AC 4 — replaces two assertions that could not be run |
| the cloudflared re-probe on the pinned digest | AC 1 — evidence now covers the shipped invocation |
| the corrected healthcheck probe, both states | AC 1 — the recorded evidence was invalid as written |

No component here serves no criterion, so revision 3 adds no scope either. Every addition is a
check or a precondition an existing criterion already asked for.

## Findings disposed without a change

- **A3 — asked for proof the tunnel and Access application can be created. MOOT.** Both exist: the
  tunnel id was decoded from the delivered token, and the owner reported the wildcard Access
  hostname accepted. The review's snapshot predates both.
- **A8 — argued the healthcheck could report healthy before initialization. REFUTED** at
  `harness/__main__.py:47-58` and `:73`, cited in section 2.
- **A3 of pass 2 — argued the two live checks do not establish the Access policies'
  authorization boundary or precedence, and asked for a negative request from an authenticated
  identity outside every allowed include rule. DECLINED as re-litigation** (decision D17). Its own
  `location` field names its target: "Findings disposed without a change, A6". A6 is the entry
  directly below, declined **by the owner** hours earlier. A declined finding reopens on new
  evidence, and A3 offers an argument rather than evidence. The join backstop did not dissolve it
  automatically — the `finding_key` differs and the fuzzy layer could not fire, because the ledger
  entries carry no `location` to match on — so this was adjudicated by hand and the owner's
  decision was left standing while they slept.
  **Pass 3 overturned that, and revision 4 adopts it — finding B4, decision D18.** Holding the
  decline would have been hiding behind a stale decision. The ground moved between passes: pass 3
  established (C1/B3) that the Access layout itself is unsettled and that the exact-host remedy is
  fail-open. The owner declined a policy matrix for a **wildcard application with two policies**;
  that object may not survive this issue. A decline is binding until new evidence arrives, and
  that IS new evidence.

  So the case A3 named — an authenticated identity outside every include rule — **moves out of the
  follow-up list and into the AC 3 and AC 4 live proof**: that identity must receive an Access
  denial, with no request reaching the harness. The runbook records each policy's action, include
  rule and precedence, so the negative identity can be constructed at all. What stays declined is
  pass-1 A6's full per-path policy MATRIX; what is adopted is the single negative request, which
  costs one curl and is the only check that can detect an over-broad allow rule.
- **S5 of pass 2 — noted, not fixed.** This design argues that a secret in `environment:` is
  readable by anything that can reach the Docker socket, and then applies that rule to the tunnel
  token alone. `DOC_HARNESS_GITHUB_TOKEN` and `DOC_HARNESS_PUBLISH_TOKEN` remain environment
  values in the same `compose.yaml`. That is a real inconsistency. It is NOT fixed here: those two
  are #34's shipped decision and this issue's scope excludes harness changes. Recorded so the next
  person does not have to rediscover it.
- **A6 of pass 1 — asked for a full Access policy matrix with precedence and per-path testing.
  DECLINED, owner decision.** The two policies were built by hand minutes before this revision; the runbook
  names both actions and both include rules; and the live proof exercises exactly the two paths
  that matter, an anonymous request getting the login page and a service-token request getting 200.
  A precedence table for two policies would also be a transcription of dashboard state this run
  cannot read back, so it could drift with nothing to catch it. Recorded rather than silently
  dropped.

## What is deferred, and to where

**C4 is NOT discharged. It remains a deferred High** (finding B2 — revision 3 declared it
discharged while the same document said it must stay deferred if the capture could not run, and
that contradiction is exactly what a close would have shipped). What #35 delivers for C4 is the
numbers and the pass criteria, which revision 1 lacked. What it does NOT deliver is an executed
run: no capture command has been proven on this host. C4 becomes discharged only when a proven
command, a recorded control capture, a termination time inside 120 s, and zero origin traffic
across the window are all on record together.

**Newly deferred by this gate's close**, each with where it resolves:

- **The Access scope decision (C1/B3)** — Option A or Option B, owner's call. Everything about
  AC 3's final shape waits on it.
- **The authenticated-negative Access check (B4)** — see its entry below; it enters the live proof.
- **The catch-all origin observation (B1)** — shares C4's unsolved mechanism.

A2's committed-ingress advantage stays a follow-up for the day a tunnel-scoped token exists.
