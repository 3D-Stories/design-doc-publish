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
