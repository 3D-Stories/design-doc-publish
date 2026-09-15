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
    assert c.zone == "3dstories.ca"
    # Convention resolution names a repository under exactly one owner.
    assert c.github_owner == "3D-Stories"
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
    c = load_config(dict(MINIMAL, DOC_HARNESS_ZONE=".3DStories.CA."))
    assert c.zone == "3dstories.ca"


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


class TestIndexSettings:
    """#65. Two knobs the index walk needs, and the bound on each.

    Both are REJECTED rather than clamped when they are out of range. A mistyped 64 that
    quietly becomes 32 is a setting the operator cannot see is wrong, and this file's whole
    stance is that a configuration mistake should fail at start-up naming its variable.
    """

    def test_the_defaults_are_eight_workers_and_a_six_hour_stale_bound(self):
        cfg = load_config(MINIMAL)
        assert cfg.index_workers == 8
        assert cfg.index_max_stale_age == 21600

    def test_the_worker_count_can_be_set(self):
        assert load_config({**MINIMAL, "DOC_HARNESS_INDEX_WORKERS": "4"}).index_workers == 4

    @pytest.mark.parametrize("value", ["0", "33", "-1"])
    def test_a_worker_count_outside_one_to_thirty_two_refuses_by_name(self, value):
        # 32 is the ceiling because GitHub's secondary rate limits punish burst concurrency,
        # and 8 is a measured starting point rather than an optimum.
        with pytest.raises(ConfigError) as caught:
            load_config({**MINIMAL, "DOC_HARNESS_INDEX_WORKERS": value})
        assert "DOC_HARNESS_INDEX_WORKERS" in str(caught.value)

    def test_thirty_two_workers_is_accepted(self):
        assert load_config({**MINIMAL, "DOC_HARNESS_INDEX_WORKERS": "32"}).index_workers == 32

    def test_zero_means_no_staleness_bound(self):
        cfg = load_config({**MINIMAL, "DOC_HARNESS_INDEX_MAX_STALE_AGE": "0"})
        assert cfg.index_max_stale_age == 0

    def test_a_stale_bound_at_or_below_the_ttl_refuses(self):
        """900 is the index TTL, so a bound of 900 makes the stale window exactly zero and a
        stale snapshot is never served at all — which would leave the whole issue unfixed while
        looking configured. The reviewer who asked for 900 as the DEFAULT had missed this."""
        for value in ("900", "60", "1"):
            with pytest.raises(ConfigError) as caught:
                load_config({**MINIMAL, "DOC_HARNESS_INDEX_MAX_STALE_AGE": value})
            assert "DOC_HARNESS_INDEX_MAX_STALE_AGE" in str(caught.value)
            assert "900" in str(caught.value)

    def test_a_bound_above_the_ttl_is_accepted(self):
        cfg = load_config({**MINIMAL, "DOC_HARNESS_INDEX_MAX_STALE_AGE": "86400"})
        assert cfg.index_max_stale_age == 86400

    def test_a_negative_stale_bound_refuses(self):
        with pytest.raises(ConfigError):
            load_config({**MINIMAL, "DOC_HARNESS_INDEX_MAX_STALE_AGE": "-1"})
