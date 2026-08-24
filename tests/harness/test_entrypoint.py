"""The container surface: the entry point, the cache lock, and the compose declarations."""
import pathlib
import os
import re
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

    # ---- the image must carry what the code loads at RUNTIME, not only what it imports ----
    # Found live on 2026-08-24: every request to the derived index returned 500. The image
    # copied `harness/` and `index/` only, and `index/build_index.py` loads two modules out of
    # its SIBLING `scripts/` directory at call time. A missing sibling is invisible to an import
    # check, because nothing imports it — the failure appears only when a page actually renders,
    # which no test did.
    #
    # The requirement is DERIVED from the code rather than listed here, so the next sibling load
    # site is covered without anyone remembering to extend a list. It asserts that each loaded
    # FILE reaches `/app/<dir>/`, not that one particular COPY form is used: copying the whole
    # directory and copying the two modules are both correct, and the image deliberately takes
    # the narrow one so the publisher toolchain and its tests stay out of a serving container.

    _SIBLING_LOAD = re.compile(
        r'root\s*=\s*Path\(__file__\)\.resolve\(\)\.parent\.parent\s*/\s*"([^"]+)"'
        r'\s*\n\s*path\s*=\s*root\s*/\s*"([^"]+)"')

    def _runtime_sibling_loads(self):
        """(directory, filename) pairs loaded relative to the app root, one level down.

        Restricted to files sitting DIRECTLY inside a copied top-level package, where
        `parent.parent` is the application root. A file nested deeper computes a different
        root, so including one here would assert the wrong destination.
        """
        found = set()
        for package in ("harness", "index"):
            directory = os.path.join(REPO_ROOT, package)
            for name in sorted(os.listdir(directory)):
                if not name.endswith(".py"):
                    continue
                found.update(self._SIBLING_LOAD.findall(
                    open(os.path.join(directory, name)).read()))
        return found

    @staticmethod
    def _copy_lines(text):
        """Every COPY as (sources, destination). Line continuations are joined first."""
        joined = text.replace("\\\n", " ")
        out = []
        for line in joined.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[0] == "COPY" and not parts[1].startswith("--"):
                out.append((parts[1:-1], parts[-1]))
        return out

    def test_every_file_loaded_at_runtime_is_copied_into_the_image(self):
        needed = self._runtime_sibling_loads()
        # Without this, a drifted pattern would match nothing and the test would pass vacuously.
        assert needed, "the scan found no sibling loads at all — the pattern has drifted"
        copies = self._copy_lines(open(os.path.join(REPO_ROOT, "Dockerfile")).read())
        for directory, filename in sorted(needed):
            destination = "/app/%s/" % directory
            satisfied = any(
                dest.rstrip("/") == destination.rstrip("/")
                and any(src.rstrip("/") in (directory, "%s/%s" % (directory, filename))
                        for src in sources)
                for sources, dest in copies)
            assert satisfied, (
                "%s/%s is loaded at runtime, and no COPY puts it at %s"
                % (directory, filename, destination))

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

    def test_the_secret_path_comes_from_a_substitution_not_a_literal(self):
        # The invariant is that no operator's home directory is baked into a tracked file.
        text = self._compose()
        assert "${DOC_HARNESS_TUNNEL_TOKEN_FILE" in text
        assert "/home/" not in text, "no absolute home directory in shared source"
        assert "~/" not in text, "no home shorthand in shared source either"

    def test_the_tunnel_is_opt_in_so_the_local_no_cloudflare_path_still_works(self):
        """#34 documented running the harness with no Cloudflare at all. This is the guard
        for that path, and it exists because #35 broke it once: a top-level secrets: block is
        interpolated whatever profile is active, so a `:?` required substitution made plain
        `docker compose config` fail for anyone who only wanted the harness."""
        assert 'profiles: ["tunnel"]' in self._service("cloudflared")
        top = self._compose().split("\nsecrets:\n", 1)[1]
        assert "DOC_HARNESS_TUNNEL_TOKEN_FILE:?" not in top, (
            "a required substitution here breaks `docker compose config` for the harness-only path")
        assert "DOC_HARNESS_TUNNEL_TOKEN_FILE:-" in top, "it must still carry a default"

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
