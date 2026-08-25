"""The doc-harness service.

Serves design-doc pages straight from GitHub, with no hosted platform in front of them.
Pages live only in the source repositories; this service keeps a registry and a cache and
nothing else.

`harness.app` is a plain WSGI callable with no non-stdlib imports, so the whole service is
testable by calling it directly. `harness.__main__` is the ONLY module that imports a
server, and the test gate never imports it.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
