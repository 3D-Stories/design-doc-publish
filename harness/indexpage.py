"""The server-rendered index, reusing `index/build_index.py`'s presentation code.

**The renderer is loaded BY PATH.** `index/` has no `__init__.py`, and
`scripts/tests/test_build_index.py` already loads it this way. Making `index` a package would
create about as collision-prone a top-level name as exists and would change pytest collection
for 53 existing test files — real risk, for a behaviour this child does not need. The peer
consult recommended the package; that recommendation is declined here with the reason recorded
in the design.

**`now` is pinned to the registry's `generated_at`, not to the wall clock.** `render()` emits
relative ages ("6h"). With the ETag derived from the generation alone, a wall-clock `now` would
make the body change while the validator did not — an ETag that is simply wrong. Pinning them
together makes body and validator agree by construction. The accepted cost is that server-rendered
age labels advance only when the registry changes; the page's own client-side `_ago` twin keeps
the displayed ages ticking in the browser.

**The project list comes from the registry** (findings S10 and C3), because the container has no
workspace file and `known_projects()` would return an empty list there, dropping every row into
the `other` bucket.

**Every registry value comes from ONE `index_snapshot()` call.** Step 11 finding F4: four separate
reads let a publish land between them, so the "agree by construction" claim above was not true of
the code. One read transaction makes it true.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
from datetime import datetime, timezone

from .registry import Registry
from .serving import Response

EYEBROW = "3dstories · living documentation"

_MODULE_LOCK = threading.Lock()
_MODULE = None


def build_index_module():
    """Load `index/build_index.py` once per process, by path."""
    global _MODULE
    with _MODULE_LOCK:
        if _MODULE is None:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(here, "index", "build_index.py")
            spec = importlib.util.spec_from_file_location("harness_build_index", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["harness_build_index"] = module
            spec.loader.exec_module(module)
            _MODULE = module
        return _MODULE


def _rows_for(snapshot: dict, bi, zone: str) -> list[dict]:
    projects = snapshot["projects"]
    rows = []
    for r in snapshot["rows"]:
        name = r["name"]
        group, chip = bi.classify(name, projects)
        updated = None
        stamp = r.get("published_at") or ""
        if stamp:
            try:
                updated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                updated = None
        rows.append({
            "name": name,
            "url": f"https://{name}.{zone}",
            "title": r.get("title") or name,
            "group": group,
            "chip": chip,
            "updated": updated,
            "updated_src": "page" if updated else "none",
        })
    return rows


def render_index(registry: Registry, *, zone: str = "docs.3dstories.ca",
                 if_none_match: str | None = None) -> Response:
    # ONE snapshot, so the ETag and the body cannot describe different generations
    # (Step 11 finding F4). The 304 decision is made from the same read as the body.
    snapshot = registry.index_snapshot()
    etag = f'"gen-{snapshot["generation"]}"'
    if if_none_match == etag:
        return Response(304, {"ETag": etag}, b"")

    bi = build_index_module()
    rows = _rows_for(snapshot, bi, zone)
    # Pinned, not `datetime.now()`. See the module docstring.
    pinned = datetime.fromtimestamp(snapshot["generated_at"], tz=timezone.utc)
    body = bi.render(rows, pinned.strftime("%Y-%m-%d"), pinned, bi.signature(rows),
                     eyebrow=EYEBROW).encode("utf-8")
    return Response(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Length": str(len(body)),
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }, body)
