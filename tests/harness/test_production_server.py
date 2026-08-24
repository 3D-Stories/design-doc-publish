"""The one test that does NOT bypass the production server.

Design finding C5: every other test in this directory invokes the WSGI callable directly, so
none of them can see the bounds waitress enforces — the pre-application 413, the 400 on a
malformed length, chunk decoding, the channel timeout, the connection limit. A mistyped or
dropped waitress argument at the `harness/__main__.py` call site would silently remove a
load-bearing production bound and the whole suite would stay green.

So this file starts the real thing and drives it over raw sockets. It SKIPS visibly when
waitress is not importable, which is the normal state of the test gate — the gate is
dependency-free on purpose, and a visible skip is the honest way to say that this coverage did
not run rather than to pretend it did.

The four status expectations below are not guesses. They were measured on 2026-08-24 against
waitress 3.0.2, and two of them contradicted what the design said at the time.
"""
import json
import os
import socket
import subprocess
import sys
import time

import pytest

waitress = pytest.importorskip(
    "waitress",
    reason="waitress is a CONTAINER dependency and the test gate does not install it; "
           "this production-server coverage is skipped, not silently passed")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_BODY = 2048


@pytest.fixture()
def server(tmp_path):
    """The real `python3 -m harness`, on a free port, with a tiny body cap."""
    port = _free_port()
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": REPO_ROOT,
        "DOC_HARNESS_GITHUB_TOKEN": "g",
        "DOC_HARNESS_PUBLISH_TOKEN": "s3cr3t",
        "DOC_HARNESS_REGISTRY_PATH": str(tmp_path / "r.db"),
        "DOC_HARNESS_CACHE_DIR": str(tmp_path / "cache"),
        "DOC_HARNESS_BIND": f"127.0.0.1:{port}",
        "DOC_HARNESS_MAX_BODY_BYTES": str(MAX_BODY),
        "DOC_HARNESS_THREADS": "4",
        "DOC_HARNESS_MAX_CONCURRENT_PUBLISHES": "2",
    })
    proc = subprocess.Popen([sys.executable, "-m", "harness"], env=env, cwd=REPO_ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _wait_for_port(port, proc)
    yield port, proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:       # pragma: no cover
        proc.kill()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, proc, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(
                f"the harness exited early with {proc.returncode}: "
                f"{proc.stderr.read().decode(errors='replace')}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("the harness never started listening")


def raw(port: int, request: bytes, read: int = 400) -> str:
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        s.sendall(request)
        return s.recv(read).decode(errors="replace").split("\r\n")[0]
    finally:
        s.close()


HOST = "docs-control.3dstories.ca"
AUTH = "Authorization: Bearer s3cr3t"


class TestBoundsOnlyTheRealServerEnforces:
    def test_a_body_within_the_cap_reaches_the_application(self, server):
        port, _ = server
        payload = json.dumps({"nope": True}).encode()
        line = raw(port, b"POST /v1/deployments HTTP/1.1\r\nHost: %s\r\n%s\r\n"
                         b"Content-Length: %d\r\nConnection: close\r\n\r\n%s"
                         % (HOST.encode(), AUTH.encode(), len(payload), payload))
        # The app was entered and refused the manifest, which is the point: not a 413.
        assert " 422 " in line or " 400 " in line, line

    def test_an_oversized_body_is_413_from_the_server(self, server):
        port, _ = server
        big = b"x" * (MAX_BODY * 4)
        line = raw(port, b"POST /v1/deployments HTTP/1.1\r\nHost: %s\r\n%s\r\n"
                         b"Content-Length: %d\r\nConnection: close\r\n\r\n%s"
                         % (HOST.encode(), AUTH.encode(), len(big), big))
        assert " 413 " in line, line

    def test_an_absent_content_length_is_411_from_the_application(self, server):
        port, _ = server
        line = raw(port, b"POST /v1/deployments HTTP/1.1\r\nHost: %s\r\n%s\r\n"
                         b"Connection: close\r\n\r\n" % (HOST.encode(), AUTH.encode()))
        assert " 411 " in line, line

    def test_a_malformed_content_length_is_400_from_the_server_not_411(self, server):
        # Measured 2026-08-24. The design said 411 here and was WRONG: waitress answers
        # first, and the application is never entered.
        port, _ = server
        line = raw(port, b"POST /v1/deployments HTTP/1.1\r\nHost: %s\r\n%s\r\n"
                         b"Content-Length: abc\r\nConnection: close\r\n\r\n"
                         % (HOST.encode(), AUTH.encode()))
        assert " 400 " in line, line

    def test_a_chunked_body_is_dechunked_and_reaches_the_application(self, server):
        # Measured 2026-08-24. The design said a chunked body would be "refused outright".
        # It cannot be: waitress de-chunks it and strips the header, so the application
        # never sees one. Writing app code to reject chunked requests would be dead code
        # that reads as a security control.
        port, _ = server
        body = json.dumps({"nope": True}).encode()
        chunked = b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body)
        line = raw(port, b"POST /v1/deployments HTTP/1.1\r\nHost: %s\r\n%s\r\n"
                         b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n%s"
                         % (HOST.encode(), AUTH.encode(), chunked))
        assert " 422 " in line or " 400 " in line, line


class TestTheRealServerStillEnforcesTheAppRules:
    def test_the_zone_allowlist_holds_over_a_real_socket(self, server):
        port, _ = server
        line = raw(port, b"GET / HTTP/1.1\r\nHost: docs-control.evil.example\r\n"
                         b"Connection: close\r\n\r\n")
        assert " 404 " in line, line

    def test_the_bearer_holds_over_a_real_socket(self, server):
        port, _ = server
        line = raw(port, b"POST /v1/deployments HTTP/1.1\r\nHost: %s\r\n"
                         b"Content-Length: 2\r\nConnection: close\r\n\r\n{}" % HOST.encode())
        assert " 401 " in line, line
