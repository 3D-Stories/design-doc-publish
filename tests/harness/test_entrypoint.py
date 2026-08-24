"""The container surface: the entry point, the cache lock, and the compose declarations."""
import pathlib
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_importing_the_app_does_not_import_waitress():
    """The load-bearing separation: the test gate must never need the runtime dependency."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);\n"
         "import harness.app, harness.control, harness.serving, harness.indexpage\n"
         "print('waitress' in sys.modules)" % REPO_ROOT],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", "importing the core must not pull in the server"


def test_importing_the_entrypoint_module_does_not_import_waitress():
    # The import lives inside main(), so even this module is importable without it.
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);\n"
         "import harness.__main__\n"
         "print('waitress' in sys.modules)" % REPO_ROOT],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


class TestCacheLock:
    def test_a_second_process_cannot_take_the_lock(self, tmp_path):
        from harness.__main__ import take_cache_lock
        held = take_cache_lock(str(tmp_path))
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from harness.__main__ import take_cache_lock\n"
            "try:\n"
            "    take_cache_lock(%r); print('ACQUIRED')\n"
            "except RuntimeError as exc:\n"
            "    print('REFUSED', 'harness.lock' in str(exc))\n" % (REPO_ROOT, str(tmp_path)))
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        assert out.stdout.strip().startswith("REFUSED"), out.stdout + out.stderr
        assert "True" in out.stdout, "the refusal must name the lock file"
        held.close()

    def test_the_lock_is_reacquirable_after_the_holder_goes_away(self, tmp_path):
        from harness.__main__ import take_cache_lock
        first = take_cache_lock(str(tmp_path))
        first.close()
        second = take_cache_lock(str(tmp_path))
        second.close()


class TestComposeAndDockerfile:
    def _compose(self):
        path = os.path.join(REPO_ROOT, "compose.yaml")
        assert os.path.exists(path)
        return open(path).read()

    def test_it_declares_exactly_two_volumes(self):
        text = self._compose()
        assert "registry:" in text and "blobcache:" in text
        assert "/var/lib/doc-harness" in text and "/var/cache/doc-harness" in text

    def test_it_publishes_no_host_ports(self):
        # #34's whole safety argument depends on the harness being unreachable from
        # outside the compose network until #35 puts Cloudflare in front of it.
        for line in self._compose().splitlines():
            stripped = line.strip()
            assert not stripped.startswith("ports:"), "the harness must publish no host port"
            assert not stripped.startswith("- \"8080:"), stripped

    def test_it_declares_one_replica(self):
        assert "replicas: 1" in self._compose()

    def test_it_requires_both_secrets_by_name_and_carries_no_values(self):
        text = self._compose()
        assert "DOC_HARNESS_GITHUB_TOKEN" in text and "DOC_HARNESS_PUBLISH_TOKEN" in text
        assert ":?" in text, "both secrets must be required, not defaulted"

    def test_the_dockerfile_installs_the_pinned_requirements(self):
        text = open(os.path.join(REPO_ROOT, "Dockerfile")).read()
        assert "harness/requirements.txt" in text
        assert "python3\", \"-m\", \"harness" in text.replace("'", '"')

    def test_the_requirement_is_pinned_exactly(self):
        text = open(os.path.join(REPO_ROOT, "harness", "requirements.txt")).read()
        lines = [l.strip() for l in text.splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        assert lines == ["waitress==3.0.2"], "one exactly-pinned runtime dependency"

    # ---- #35: the cloudflared service that puts the harness on the internet ----
    # Read as text, not parsed: this repo's compose assertions are all textual and the test
    # gate is deliberately dependency-free, so no YAML parser is introduced here. But a
    # whole-file string search is too weak for a two-service file — a review found that
    # `condition: service_healthy` or `tunnel_token` sitting under the WRONG service would
    # satisfy it. So the service block is sliced out first and the assertions run inside it.

    def _service(self, name):
        """The lines of one top-level service block, by indentation. No YAML parser."""
        out, inside = [], False
        for line in self._compose().splitlines():
            if line.strip().startswith("#"):
                continue                      # a comment must never satisfy an assertion
            if line.startswith(f"  {name}:"):
                inside = True
                continue
            if inside:
                # a new sibling service (two-space indent, non-blank) ends this block
                if line.strip() and not line.startswith("    "):
                    break
                out.append(line)
        assert out, f"no service block found for {name}"
        return "\n".join(out)

    def test_the_cloudflared_service_exists(self):
        # Deliberately not `"cloudflared:" in text`: an image line reading
        # `cloudflare/cloudflared:2026.8.2` would satisfy that with no service at all.
        assert self._service("cloudflared")

    def test_cloudflared_is_pinned_by_digest_and_never_a_moving_tag(self):
        # --no-autoupdate does not stop a later pull resolving a different image, so a
        # moving tag would let the stack's behavior change with no commit to review.
        lines = [l.strip() for l in self._service("cloudflared").splitlines()
                 if l.strip().startswith("image:")]
        assert len(lines) == 1, "exactly one cloudflared image line"
        assert "@sha256:" in lines[0], lines[0]
        assert ":latest" not in lines[0], lines[0]

    def test_the_tunnel_token_is_a_declared_top_level_file_secret(self):
        # A service referencing an undeclared secret makes compose reject the whole file,
        # so cloudflared would never start. This is the assertion for that.
        text = self._compose()
        assert "\nsecrets:\n" in text, "a TOP-LEVEL secrets: block must exist"
        top = text.split("\nsecrets:\n", 1)[1]
        assert "tunnel_token:" in top and "file:" in top
        # and the service must actually reference it, or the declaration is decorative
        assert "tunnel_token" in self._service("cloudflared")

    def test_the_tunnel_token_is_never_an_environment_value(self):
        # docker inspect prints a container's environment, so the token rides a file
        # secret. cloudflared's own --help says --token takes precedence over
        # --token-file, so setting both would silently defeat this.
        block = self._service("cloudflared")
        for line in block.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("TUNNEL_TOKEN:"), stripped
            assert not stripped.startswith("- TUNNEL_TOKEN="), stripped
        # env_file would put the value out of this file's sight entirely, which defeats the
        # point of asserting on the file at all.
        assert "env_file" not in block, "the token must not arrive via env_file"

    def test_the_secret_path_comes_from_a_required_substitution(self):
        # No operator's home directory baked into a tracked file.
        assert "DOC_HARNESS_TUNNEL_TOKEN_FILE:?" in self._compose()

    def test_cloudflared_waits_for_a_healthy_harness(self):
        # Without this cloudflared advertises a route to a harness that has not finished
        # taking its cache lock. Asserted on the DEPENDENCY EDGE, not on the string anywhere
        # in the file: `service_healthy` under some other service proves nothing.
        block = self._service("cloudflared")
        assert "depends_on:" in block
        after = block.split("depends_on:", 1)[1]
        assert "harness:" in after, "cloudflared must depend on harness specifically"
        assert "condition: service_healthy" in after.split("harness:", 1)[1]

    def test_the_dockerfile_declares_a_healthcheck_with_no_new_request_surface(self):
        # A TCP connect, deliberately NOT an HTTP /health route: the whole design is that
        # only gated hosts answer, so a new unauthenticated route would undo it.
        text = open(os.path.join(REPO_ROOT, "Dockerfile")).read()
        assert "HEALTHCHECK" in text
        # Assert on the directive itself, not the whole file: a prose comment must not be
        # able to fail this, and it is the COMMAND that either adds a request surface or does
        # not. Joins the continued line so the CMD travels with its HEALTHCHECK.
        joined = text.replace("\\\n", " ")
        line = next(l for l in joined.splitlines() if l.strip().startswith("HEALTHCHECK"))
        assert "socket.create_connection" in line
        assert "import socket" in line, "the probe must import what it calls"
        for http in ("curl", "wget", "http://", "urllib", "/health"):
            assert http not in line, f"the healthcheck must add no request surface: {http}"


class TestBuildWiring:
    def test_build_constructs_the_real_stack_without_a_server(self, tmp_path):
        from harness.__main__ import build
        cfg, app, lock = build({
            "DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "p",
            "DOC_HARNESS_REGISTRY_PATH": str(tmp_path / "r.db"),
            "DOC_HARNESS_CACHE_DIR": str(tmp_path / "cache"),
        })
        assert callable(app)
        lock.close()

    def test_build_does_not_require_a_server(self, tmp_path):
        """Step 11 F9. The old assertion was `... or True`, so it could never fail.

        The invariant is about what `build()` IMPORTS, and this process may already carry
        waitress for other reasons, so the check runs in a clean interpreter where the only
        import that can have happened is one `build()` made itself.
        """
        program = (
            "import sys\n"
            "from harness.__main__ import build\n"
            "cfg, app, lock = build({\n"
            "    'DOC_HARNESS_GITHUB_TOKEN': 'g', 'DOC_HARNESS_PUBLISH_TOKEN': 'p',\n"
            "    'DOC_HARNESS_REGISTRY_PATH': %r,\n"
            "    'DOC_HARNESS_CACHE_DIR': %r,\n"
            "})\n"
            "lock.close()\n"
            "assert 'waitress' not in sys.modules, 'build() imported a server'\n"
        ) % (str(tmp_path / "sub.db"), str(tmp_path / "subcache"))
        proc = subprocess.run([sys.executable, "-c", program],
                              cwd=str(pathlib.Path(__file__).resolve().parents[2]),
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr

    def test_build_refuses_without_a_token(self, tmp_path):
        from harness.__main__ import build
        from harness.config import ConfigError
        with pytest.raises(ConfigError):
            build({"DOC_HARNESS_PUBLISH_TOKEN": "p",
                   "DOC_HARNESS_CACHE_DIR": str(tmp_path / "cache")})
