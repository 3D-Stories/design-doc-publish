"""#36 — publishing through the doc-harness control API instead of Vercel.

New surfaces live here rather than in `test_publish_doc.py`, which task T7 rewrites: keeping
the new contract in its own file means the retirement churn and the new coverage cannot
obscure each other in review.

Design: docs/planning/2026-08-24-36-publish-to-harness.md (revision 4).
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import publish_doc  # noqa: E402


# --------------------------------------------------------------------------- T1, AC1

class TestTheControlEndpointIsRequiredRatherThanDefaulted:
    """Owner decision D21. Revision 2 defaulted this to the compose-network address and
    called it reachable. Measured on the harness host: the host reaches a container's
    bridge IP with no published port, but never resolves a compose SERVICE name. So a
    default cannot be right, and an unset variable is a declared state with its own exit
    code rather than a guess."""

    def test_the_two_declared_state_exit_codes_sit_outside_the_stage_block(self):
        """`EXIT_BASE + stage` owns 11 through 17. A skip code inside that range is
        indistinguishable from a stage failure, which is the whole misreport the exit
        contract exists to prevent."""
        assert publish_doc.EXIT_CONTROL_URL_UNSET == 25
        assert publish_doc.EXIT_EDGE_SKIPPED == 26
        taken = {publish_doc.EXIT_BASE + s for s in range(1, 8)}
        assert publish_doc.EXIT_CONTROL_URL_UNSET not in taken
        assert publish_doc.EXIT_EDGE_SKIPPED not in taken

    def test_an_unset_control_url_refuses_and_names_the_variable(self):
        with pytest.raises(publish_doc.DeclaredStateError) as e:
            publish_doc.control_base({})
        assert e.value.code == publish_doc.EXIT_CONTROL_URL_UNSET
        assert "DOC_HARNESS_CONTROL_URL" in e.value.message

    def test_an_empty_control_url_is_unset_not_a_value(self):
        """An exported-but-blank variable is the same declared state, never a base URL
        of the empty string."""
        for blank in ("", "   ", "\t"):
            with pytest.raises(publish_doc.DeclaredStateError):
                publish_doc.control_base({"DOC_HARNESS_CONTROL_URL": blank})

    def test_there_is_no_default_anywhere(self):
        """The regression guard for D21. A default reintroduced here is the exact defect
        revision 2 shipped."""
        with pytest.raises(publish_doc.DeclaredStateError):
            publish_doc.control_base({"SOMETHING_ELSE": "x"})

    @pytest.mark.parametrize("raw,want", [
        ("http://172.25.0.2:8080", "http://172.25.0.2:8080"),
        ("http://172.25.0.2:8080/", "http://172.25.0.2:8080"),
        ("https://docs-control.3dstories.ca", "https://docs-control.3dstories.ca"),
        ("  http://127.0.0.1:8080  ", "http://127.0.0.1:8080"),
    ])
    def test_a_usable_base_is_normalized_to_scheme_host_port(self, raw, want):
        assert publish_doc.control_base({"DOC_HARNESS_CONTROL_URL": raw}) == want

    @pytest.mark.parametrize("bad", [
        "http://user:pw@10.0.0.1:8080",          # userinfo
        "http://10.0.0.1:8080/v1",               # path
        "http://10.0.0.1:8080/?a=b",             # query
        "http://10.0.0.1:8080/#frag",            # fragment
        "10.0.0.1:8080",                         # no scheme
        "ftp://10.0.0.1:8080",                   # wrong scheme
    ])
    def test_anything_but_scheme_host_port_is_refused(self, bad):
        """Finding N4. A control base carrying userinfo, a path, a query or a fragment is
        refused BEFORE any bearer is attached, not sanitized into one."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.control_base({"DOC_HARNESS_CONTROL_URL": bad})


class TestTheEdgeHalfSkipsVisiblyRatherThanSilently:
    """AC2's edge half needs a public hostname. None resolves, so the skip is a declared
    state with its own exit code — never a silent 0, which every caller reads as a pass."""

    def test_an_unset_public_base_is_a_skip_not_an_error(self):
        assert publish_doc.public_base({}) is None

    def test_an_empty_public_base_is_also_a_skip(self):
        for blank in ("", "   "):
            assert publish_doc.public_base({"DOC_HARNESS_PUBLIC_BASE": blank}) is None

    def test_a_set_public_base_is_normalized(self):
        assert publish_doc.public_base(
            {"DOC_HARNESS_PUBLIC_BASE": "https://<name>.3dstories.ca/"}
        ) == "https://<name>.3dstories.ca"

    def test_the_public_base_must_be_https(self):
        """Finding N4. The Access service tokens ride on this host, so plaintext is
        refused rather than downgraded."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.public_base({"DOC_HARNESS_PUBLIC_BASE": "http://<name>.3dstories.ca"})

    def test_the_flag_that_converted_the_skip_to_zero_does_not_exist(self):
        """Finding N3. `--allow-unverified-edge` turned exit 26 into 0, which contradicts
        the declared meaning of 0 and let a status-only caller record an AC2 pass that
        never happened."""
        flags = {o for a in publish_doc.build_parser()._actions for o in a.option_strings}
        assert "--allow-unverified-edge" not in flags
