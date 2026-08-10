# This account's Vercel limits

Facts about the `3d-stories` team that the tooling cannot discover for itself, kept here so
they are not re-derived by trial and error. **Nothing here is a step to perform** — the deploy
and its verification are stages 5 and 6 of `scripts/publish_doc.py`. This file exists for the
one question the script does not answer: *can these pages be made private?*

Short answer: **no, not the production alias.** Public is the convention anyway (owner decision
2026-07-24 — it matches every other Vercel upload across these projects), so deployment
protection is deliberately never enabled.

## What was measured

Verified live on this account 2026-07-24, team `3d-stories`:

- **Vercel Authentication is unavailable for *production*** on this plan — the API refuses with
  `invalid_sso_protection`.
- **Team password protection is off** — `Advanced Deployment Protection is not enabled`.
- **`protection enable --sso` only reaches `prod_deployment_urls_and_all_previews`**, which
  exempts the `<name>.vercel.app` alias. So only PREVIEW deploys actually gate.

## The consequence that bites

The per-deployment URL and the production alias behave differently, and it is easy to read one
as the other:

| URL shape | what it serves |
|---|---|
| `https://<name>.vercel.app` (the alias) | the page, `200`, public |
| `https://<name>-<hash>-3d-stories.vercel.app` (per-deployment) | an SSO stub |

Re-confirmed 2026-08-03 while trying to read an older revision of a published page: three
per-deployment URLs each returned a **15-byte** body, while the alias served the real 53 KB
document. **A deployment's history is not readable over HTTP** — to compare against an earlier
version, keep the rendered bytes (the committed `.html` is the durable copy) rather than
expecting to fetch the previous deploy.

## Because the pages are public

Secrets by NAME only. Internal host paths and design rationale are fine; strip internal IPs,
hostnames and hardware identifiers such as drive serials. `SKILL.md` carries this rule too, and
a test pins it there — this paragraph is context, not the source of truth.
