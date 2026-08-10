"""`python3 -m render` entry point.

The `if __name__` guard is load-bearing: without it, merely importing this module would run the
CLI with the importer's argv (pytest's, for instance) and raise SystemExit mid-collection.

Prefer the `render-doc` launcher for anything outside this package — a bare `-m render` resolves
by sys.path order and can pick up a different installed package named `render`.
"""
import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
