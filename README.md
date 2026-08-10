# design-doc-publish

Renders a design or architecture document from markdown to a standalone HTML page and
deploys it to Vercel. One command renders, lints, deploys and verifies.

## Status

The package now lives here, moved out of `claude-skills` under
[epic #7](https://github.com/3D-Stories/design-doc-publish/issues/7). Still to come in that
epic: installable-plugin packaging ([#2](https://github.com/3D-Stories/design-doc-publish/issues/2)),
the public README written for someone who did not build this
([#3](https://github.com/3D-Stories/design-doc-publish/issues/3)), and the disposition of the
vendored reference material ([#4](https://github.com/3D-Stories/design-doc-publish/issues/4)).

**This README is still a developer-facing stub.** Issue #3 owns the version a stranger can act
on — what the output looks like, a rendered example, and a copy-pasteable first command.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest scripts/tests/ tests/ -q
```

Expected: **2218 passed, 7 skipped**, exit 0.

Three of those skips are deliberate and name their own reason under `pytest -rs`: the
per-template guards have nothing to check since the unlicensed vendored set was removed,
and they re-arm automatically if anything is vendored there again.

Use `pytest`, not `python3 -m pytest`. On the machine this package was migrated from the
interpreter cannot import pytest and only the standalone executable works, so the module form
fails with "No module named pytest". `requirements-dev.txt` pins the version that produced the
count above.

This same command is declared in `.rawgentic.json` under `testing.frameworks`, and that
declaration is verified rather than assumed — `capabilities_lib.py derive` reports
`has_tests: true` with this exact string.

## Installing it

Two commands, and the first is easy to miss — the install cannot resolve the plugin until the
marketplace is registered:

```bash
claude plugin marketplace add 3D-Stories/design-doc-publish
claude plugin install design-doc-publish@design-doc-publish
```

Then start a **new** session. A running session holds already-resolved paths, so it will not see
a skill that was installed after it started.

To remove it:

```bash
claude plugin uninstall design-doc-publish
claude plugin marketplace remove design-doc-publish
```

Uninstalling deregisters the plugin but leaves its files on disk, in a version directory marked
`.orphaned_at` under `~/.claude/plugins/cache/design-doc-publish/`. Delete that directory if you
want the disk back.

### It is not usable end to end yet, and here is exactly where it stops

Installing works. Rendering to HTML works. **Publishing does not work for anyone but the author
yet**, and it stops in a specific place, measured rather than guessed:

- Stage 1 of 7 renders your markdown to HTML. This works.
- Stage 2 of 7 refuses: `--project '<name>' is not a rawgentic project in
  ~/rawgentic/.rawgentic_workspace.json`. That path is hardcoded, and you do not have that file.
- The Vercel team is hardcoded too, so deploys would target a team you are not in.

[#9](https://github.com/3D-Stories/design-doc-publish/issues/9) is the first-run setup flow that
fixes both. **No release is tagged until it lands**, because tagging one would advertise something
that is not true yet.

## Licence

MIT — see `LICENSE`. That covers the code and documentation authored here. The material
vendored under `references/` stays under its own terms; see `docs/third-party-notices.md`,
which also records why that directory is treated as untrusted data and is not offline-safe.
