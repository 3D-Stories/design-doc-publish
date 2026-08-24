"""Put the repository root on `sys.path` so `import harness...` works.

Scoped to THIS directory on purpose. A `conftest.py` at the repository root would change
`sys.path` for all 53 existing test files at once, and none of them needs it — every one either
imports nothing from the repo or loads its target explicitly with `importlib`. Keeping the change
here means the blast radius of the new package is the new package.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
