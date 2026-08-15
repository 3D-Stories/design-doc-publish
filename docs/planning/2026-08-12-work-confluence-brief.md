# Work scenario brief: serving design-doc HTML inside Confluence Cloud

Problem statement for peer consult and adversarial review. Feeds the work branch of
`docs/planning/2026-08-12-hosting-options.md` (design-doc-publish PR #22).

## Constraints, settled by the owner 2026-08-12

1. Work has NO GitHub Enterprise Cloud plan, so access-controlled (private) GitHub Pages
   is impossible. Private repos below Enterprise serve Pages publicly — forbidden for work.
2. One scope, one host: personal docs stay on Vercel end-to-end, unchanged. Work docs go
   Confluence end-to-end. No scope mixes hosts.
3. The plugin (design-doc-publish) gains a setup-time PROFILE: `personal` or `work`,
   stored per machine, with a per-repo override. The profile picks the backend bundle.
4. The plugin's identity is a contract, not a host: render → lint → deliver → prove the
   served bytes equal the committed bytes (byte-identity custody verify).

## Research findings (2026-08-12, sources in the main design doc)

- Confluence Cloud does NOT natively render HTML attachments. It forces
  `Content-Disposition: attachment` on them deliberately (XSS defense; open ticket
  CONFCLOUD-69015; Atlassian KB says the behavior stays).
- Marketplace apps DO render attached HTML files with JavaScript, inside sandboxed
  iframes that cannot touch the parent page DOM or Confluence tokens. Three candidates:
  1. "HTML Macro for Confluence" (Narva) — renders HTML files from page attachments;
     marketed for self-contained pages with JS/CSS; trusted-domain allowlist.
  2. "HTML Macro for Confluence Cloud" (Appfire/Bob Swift) — attachment data source;
     double-sandboxed iframe served from the VENDOR's domain (html.bobswift.appfire.app);
     admin-gated "Allow JavaScript".
  3. "HTML Macro for Confluence (Free)" — runs entirely on Atlassian Forge, so content
     never leaves Atlassian infrastructure; CSP modes (block-all / whitelist / allow-all);
     editor access control.
- Our pages fit the sandbox well: the lint gate already forbids external requests, and the
  pages are single-file self-contained HTML with modest inline JS (native details
  disclosure, uat localStorage).

## Proposed work path (attack this)

1. **Source of truth stays git.** The work repo commits the `.md` + `.html` pair and the
   `docs/publications.json` manifest, exactly like every other scope.
2. **Deliver:** a publish step (CI job on merge, or the publishing session) uploads the
   committed `.html` as an ATTACHMENT to that doc's Confluence page via REST API v2, and
   the page body carries: title/purpose metadata, the source commit SHA, and the HTML
   macro rendering that attachment. One Confluence page per doc; one index page per
   space lists all docs (rebuilt from manifests; 409-retry on version conflicts).
3. **Verify (custody):** download the attachment back via the REST API and byte-compare
   against the committed blob. Attachment download is API-native, so the verify contract
   survives intact — stronger than screen-scraping the rendered macro.
4. **App selection:** prefer the Forge-based macro (content stays on Atlassian infra —
   the least new data residency surface for a security review); Appfire/Narva as
   fallbacks. Admin installs the app once; the plugin's `work` profile refuses with a
   named remediation when the macro is absent.
5. **Setup profile:** `setup.py` asks personal/work once per machine; `work` profile
   stores the Confluence base URL, space key, and API token BY NAME (env var); per-repo
   override in the repo's own config.

## Questions for the peer

- Is the attachment + HTML-macro mechanism sound for ~tens of docs, or is there a simpler
  Confluence-native shape we are missing (e.g. ADF conversion, Forge custom UI)?
- What breaks at the security review: vendor-domain iframes, storage access in sandboxes,
  macro editor permissions, token scoping?
- Is byte-identity-via-attachment-download sufficient custody, given the RENDERED view
  goes through a third-party macro we do not verify?
- What is the failure story when the macro app is uninstalled or its vendor sunsets it?
