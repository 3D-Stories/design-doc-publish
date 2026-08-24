"""`harness.config` — env parsing, and the refusals that must happen at start-up.

The two secrets are required, and the process must refuse to start without them NAMING the
one that is missing. A service that boots without a GitHub token would answer every serving
request with a 503 that looks exactly like an upstream outage, which sends whoever is paged
to the wrong system.
"""
import pytest

from harness.config import ConfigError, HarnessConfig, load_config

MINIMAL = {"DOC_HARNESS_GITHUB_TOKEN": "gh-tok", "DOC_HARNESS_PUBLISH_TOKEN": "pub-tok"}


def test_defaults_match_the_design_table():
    c = load_config(MINIMAL)
    assert c.zone == "docs.3dstories.ca"
    assert c.cache_max_bytes == 2147483648
    assert c.max_body_bytes == 1048576
    assert c.max_blob_bytes == 104857600
    assert c.max_assets == 200
    assert c.max_publish_bytes == 268435456
    assert c.http_timeout == 20.0
    assert c.publish_deadline == 120.0
    assert c.max_github_calls == 300
    assert c.max_concurrent_publishes == 2
    assert c.threads == 8
    assert c.channel_timeout == 60
    assert c.connection_limit == 100
    assert c.github_api == "https://api.github.com"
    assert c.registry_path == "/var/lib/doc-harness/registry.db"
    assert c.cache_dir == "/var/cache/doc-harness"
    assert c.bind == "0.0.0.0:8080"


@pytest.mark.parametrize("missing", ["DOC_HARNESS_GITHUB_TOKEN", "DOC_HARNESS_PUBLISH_TOKEN"])
def test_a_missing_required_secret_refuses_and_names_it(missing):
    env = dict(MINIMAL)
    del env[missing]
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert missing in str(exc.value)


@pytest.mark.parametrize("missing", ["DOC_HARNESS_GITHUB_TOKEN", "DOC_HARNESS_PUBLISH_TOKEN"])
def test_a_blank_required_secret_is_treated_as_missing(missing):
    # An empty string is how a mis-templated compose file usually fails, and it must not
    # read as "the operator supplied a token".
    env = dict(MINIMAL, **{missing: "   "})
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert missing in str(exc.value)


def test_a_non_integer_numeric_setting_refuses_and_names_the_variable():
    with pytest.raises(ConfigError) as exc:
        load_config(dict(MINIMAL, DOC_HARNESS_CACHE_MAX_BYTES="two gigs"))
    assert "DOC_HARNESS_CACHE_MAX_BYTES" in str(exc.value)


def test_a_non_positive_numeric_setting_refuses():
    with pytest.raises(ConfigError) as exc:
        load_config(dict(MINIMAL, DOC_HARNESS_MAX_ASSETS="0"))
    assert "DOC_HARNESS_MAX_ASSETS" in str(exc.value)


def test_the_zone_is_lowercased_and_stripped_of_dots():
    # This one supplies its own zone, so it asserts the NORMALISATION and not the default.
    c = load_config(dict(MINIMAL, DOC_HARNESS_ZONE=".Docs.3DStories.CA."))
    assert c.zone == "docs.3dstories.ca"


def test_concurrent_publishes_must_leave_serving_workers_free():
    # Design, concurrency model: the semaphore must sit at least 2 below the thread count,
    # or a burst of publishes can occupy every worker and serving stops (finding B3).
    with pytest.raises(ConfigError) as exc:
        load_config(dict(MINIMAL, DOC_HARNESS_THREADS="4", DOC_HARNESS_MAX_CONCURRENT_PUBLISHES="3"))
    assert "DOC_HARNESS_MAX_CONCURRENT_PUBLISHES" in str(exc.value)
    assert "DOC_HARNESS_THREADS" in str(exc.value)
    # 2 below is fine.
    assert load_config(dict(MINIMAL, DOC_HARNESS_THREADS="4",
                            DOC_HARNESS_MAX_CONCURRENT_PUBLISHES="2")).max_concurrent_publishes == 2


def test_the_config_is_frozen():
    c = load_config(MINIMAL)
    with pytest.raises(Exception):
        c.zone = "elsewhere.example"


def test_secrets_are_not_in_the_repr():
    # The config is logged at start-up in some deployments; the tokens must not ride along.
    c = load_config(dict(MINIMAL, DOC_HARNESS_GITHUB_TOKEN="ghp_supersecret"))
    assert "ghp_supersecret" not in repr(c)
    assert isinstance(c.github_token, str) and c.github_token == "ghp_supersecret"

class TestStep11BindValidation:
    """Step 11 F12: every start-up refusal names its variable, `DOC_HARNESS_BIND` included."""

    def test_a_bind_with_no_port_is_refused_by_name(self):
        with pytest.raises(ConfigError) as exc:
            load_config(dict(MINIMAL, DOC_HARNESS_BIND="0.0.0.0"))
        assert "DOC_HARNESS_BIND" in str(exc.value)

    def test_a_bind_with_a_non_numeric_port_is_refused_by_name(self):
        with pytest.raises(ConfigError) as exc:
            load_config(dict(MINIMAL, DOC_HARNESS_BIND="0.0.0.0:http"))
        assert "DOC_HARNESS_BIND" in str(exc.value)

    def test_a_bind_with_an_out_of_range_port_is_refused(self):
        with pytest.raises(ConfigError):
            load_config(dict(MINIMAL, DOC_HARNESS_BIND="0.0.0.0:70000"))

    def test_the_default_bind_and_a_port_only_bind_are_accepted(self):
        assert load_config(MINIMAL).bind == "0.0.0.0:8080"
        assert load_config(dict(MINIMAL, DOC_HARNESS_BIND="127.0.0.1:9000")).bind == "127.0.0.1:9000"
