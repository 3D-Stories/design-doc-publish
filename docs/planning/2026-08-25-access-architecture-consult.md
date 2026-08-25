The catch-all-with-exceptions model is ADOPTED for zone Access: one wildcard Cloudflare Access application protects every new one-label hostname automatically, and public hosts are explicit, marked exceptions. Three independent models (grok, deepseek-v4-pro, gpt-5.6-sol) and Cloudflare's own documentation all endorse it — and the zone has run exactly this shape since 2026-08-24. The owner's least-privilege claim is half right: the model is default-deny for NEW hosts, but it provides no separation BETWEEN protected services, and one finding needs action now — the automation service token sits on the wildcard application, making it a skeleton key for the whole zone.

· [live](https://2026-08-25-design-doc-publish-access-architecture-consult.3dstories.ca)

```verdict
confirmed | Catch-all with exceptions is the right architecture for this zone. Dedicated Access applications are created only when a service's policy must differ.
```

```provenance
consulted | grok 1.0.5 (proposal), deepseek-v4-pro via the qwen CLI (proposal), gpt-5.6-sol via codex (adversarial review of the synthesis)
research | Cloudflare docs (app-paths, policies, require-access-protection) via context7; field guides via exa web search
zone state | measured live 2026-08-24/25: one wildcard app on *.3dstories.ca, nine bypass apps, wildcard DNS to a cloudflared tunnel
redaction | LAN addresses are redacted on this public page; the operational prompt with real values lives in the session record
```

## Is the owner's catch-all model right?

Yes, and it is already running. Cloudflare built wildcard Access applications for exactly this pattern, and the surveyed homelab guides converge on it: protect `*.<zone>` by default, mark public hosts explicitly. A new one-label hostname is protected the moment it exists, with zero per-site Access work. The exception list is the whole public surface, readable in one screen.

```chips
default-deny for new hosts | done
segmentation between services | blocked
service token isolated | pending
account-level fail-closed | planned
```

## Where does the least-privilege claim break?

"Least privilege" is two different properties. The wildcard gives one and not the other.

Default-deny: a new hostname cannot be reached without passing the zone login. That is real, and it is the property the owner wanted.

Segmentation: one wildcard application means one application audience. One login session, one stolen JWT, or one service token is valid on every host the application covers. With a single human user this is tolerable today. It stops being tolerable the day a second identity or a scoped bot arrives.

```callout
crit | The skeleton key is real today, not someday
The automation service token is attached to the wildcard application, so that ONE token currently unlocks every protected host on the zone. Grok found it; the gpt-5.6-sol review confirmed the risk is present now. Move the token to a dedicated docs-control application.
```

## What must change now?

```steps
1 | Isolate the service token | Create a dedicated application for the docs control host carrying the service-token policy plus the owner allow; remove the token policy from the wildcard. Test immediately after — one docs caution reports a specific application observed to block requests over a wildcard.
2 | Turn on Require Access protection | The account-level setting blocks any hostname with NO Access application. Without it, accidental deletion of the wildcard application fails the whole zone OPEN. The reviewer rated this mandatory, not optional.
3 | Grey-cloud the six external-service records | autodiscover, lyncdiscover, msoid, sip, email and _domainconnect should be DNS-only, and their six bypass applications deleted. Bypass only skips the login while Cloudflare still proxies an origin it cannot serve — the standing 521/530 errors. Diagnose each record as it is flipped rather than assuming one cause.
```

## What is deferred, and why?

The bypasses for the two admin hosts stay for now: removing them puts the zone login in front of tools that already carry their own authentication, which is defense-in-depth at the cost of a login step — the owner's call. The two-label hole (a nested name is matched by the DNS wildcard but not by the Access wildcard) is real but currently blocked by certificate coverage; step 2 above closes it properly. The apex is not covered by the wildcard and needs its own application only if it is ever proxied.

## What is the standing rule for new services?

Spin up the service, route it through a tunnel, proxy its one-label hostname. The wildcard protects it automatically. Create a dedicated Access application ONLY when the policy must differ: its own service token, additional people, or a different session length — and never attach a carve-out policy to the wildcard itself, which would hand the exception to every covered host.

```callout
note | Exceptions are named and reviewed
Every exception application is named bypass-<host> with its purpose. Deleting one fails CLOSED onto the wildcard. The list is reviewed on a schedule, and an entry that outlives its service is removed.
```

## What does the onboarding prompt look like under this model?

The prompt below is the template handed to a project session to put a LAN-only service behind the zone login. LAN addresses are redacted here; the operational copy carries real values.

```text
Put <service>.3dstories.ca behind the zone's Cloudflare Access login. The zone runs
catch-all-with-exceptions: ONE Access app on *.3dstories.ca (allow the owner's email)
protects every proxied one-label host automatically. DO NOT create an Access app for this
site — the only job is getting its traffic through Cloudflare's edge via a tunnel.

VERIFY FIRST: if DNS is an A record to a private address, Cloudflare never sees the traffic
and cannot protect it. Pick the tunnel origin from the service's compose file (a service
name like proxy:8443 — NEVER localhost, which inside the cloudflared container is
cloudflared itself). Self-signed origin => originRequest noTLSVerify on that one route.

CREDENTIALS: the Cloudflare API token (Access Edit + Cloudflare Tunnel Edit) sits in the
secrets directory; the DNS token lives inside the traefik container on the gateway. PATCH
fails with error 10405 — POST to create, PUT whole objects. Never print a token value.

STEPS: (1) create the tunnel (config_src cloudflare); PUT its configuration with ingress
[{hostname <service>.3dstories.ca, service <origin>}, {service http_status:404}]; store its
token file mode 600. (2) add cloudflared to the service's compose: digest-pinned image,
["tunnel","--no-autoupdate","run"], TUNNEL_TOKEN_FILE via a compose secret. TRAP: the image
runs as uid 65532 and cannot read a 600 file owned by uid 1000 — set user: "1000:1000".
Ship via PR. (3) DNS LAST: flip the record to CNAME <tunnel-id>.cfargotunnel.com,
proxied — record the old value first; the undo is restoring it.

VERIFY from the public internet: anonymous fetch answers 302 to the Access login;
after owner login the app renders (screenshot); www.3dstories.ca still answers 200 with
no cf-access-domain header; the tunnel reads healthy via the API. Log every change and
its one-step undo. If blocked, ask the owner with the exact command — never work around it.
```

## What did each consultant actually contribute?

The grok proposal found the service-token skeleton key, split the least-privilege claim into its two halves, and named the two-label and apex gaps. The deepseek proposal (via the qwen CLI, which is configured to route there — reported honestly) supplied the exception-list failure modes and their mitigations, including naming and scheduled review. The gpt-5.6-sol review corrected the synthesis in six places: the token risk is present-tense, carve-outs belong on dedicated applications and never on the wildcard, the 521/530 diagnosis must be per-record rather than blanket, bypassed traffic is unlogged only by Access, certificate failure is not an authorization control, and Require Access protection should be mandatory.
