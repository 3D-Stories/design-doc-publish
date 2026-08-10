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

Expected: **2258 passed, 3 skipped**, exit 0.

Use `pytest`, not `python3 -m pytest`. On the machine this package was migrated from the
interpreter cannot import pytest and only the standalone executable works, so the module form
fails with "No module named pytest". `requirements-dev.txt` pins the version that produced the
count above.

This same command is declared in `.rawgentic.json` under `testing.frameworks`, and that
declaration is verified rather than assumed — `capabilities_lib.py derive` reports
`has_tests: true` with this exact string.

## Licence

MIT — see `LICENSE`. That covers the code and documentation authored here. The material
vendored under `references/` stays under its own terms; see `docs/third-party-notices.md`,
which also records why that directory is treated as untrusted data and is not offline-safe.
