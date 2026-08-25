"""Evidence verifier tests.

The verifier is the component that turns "the AI must cite real evidence" from a prompt
instruction into an enforced property, so these tests are deliberately adversarial: they
try to get fabricated evidence past it.
"""

from __future__ import annotations

import pytest

from backend.app.ai.evidence_verifier import normalise, verify_evidence
from backend.app.models.diagnosis import Evidence

VLAN_OUTPUT = """VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Gi0/4, Gi0/5
10   SALES                            active    Gi0/3
20   HR                               active    Gi0/1
30   SERVERS                          active    Gi0/2"""

ROUTE_OUTPUT = """Gateway of last resort is not set

C        192.168.10.0/24 is directly connected, Vlan10
C        192.168.20.0/24 is directly connected, Vlan20"""


@pytest.fixture
def corpus():
    return {
        "show vlan brief": VLAN_OUTPUT,
        "show ip route": ROUTE_OUTPUT,
    }


def cite(command: str, excerpt: str) -> Evidence:
    return Evidence(
        source_command=command,
        excerpt=excerpt,
        why_it_matters="test citation",
    )


# --- C. real citations pass -----------------------------------------------------------


def test_real_citation_passes(corpus):
    result = verify_evidence([cite("show vlan brief", "30   SERVERS")], corpus)

    assert result.status == "passed"
    assert result.verified_count == 1
    assert result.failed_count == 0
    assert result.warning() is None


def test_multiple_real_citations_across_commands_pass(corpus):
    result = verify_evidence(
        [
            cite("show vlan brief", "20   HR                               active    Gi0/1"),
            cite("show ip route", "Gateway of last resort is not set"),
        ],
        corpus,
    )

    assert result.status == "passed"
    assert result.verified_count == 2


# --- D. fabricated citations fail -----------------------------------------------------


def test_fabricated_citation_fails(corpus):
    """The canonical attack: a plausible-looking VLAN that was never in the output."""
    result = verify_evidence([cite("show vlan brief", "40   DATABASE")], corpus)

    assert result.status == "failed"
    assert result.failed_count == 1
    assert result.failed_items[0].reason == "excerpt_not_found"
    assert "does not appear anywhere" in result.failed_items[0].detail


def test_failed_citation_is_recorded_not_discarded(corpus):
    """A failed citation must remain visible to the reviewer, never silently removed."""
    result = verify_evidence([cite("show vlan brief", "40   DATABASE")], corpus)

    assert result.failed_items, "the failed citation was dropped instead of recorded"
    # The verbatim text is preserved on the item itself...
    assert result.failed_items[0].excerpt == "40   DATABASE"
    # ...and the human-readable summary names it too (whitespace collapsed for one-line
    # display).
    assert "40 DATABASE" in result.details


def test_mix_of_real_and_fabricated_is_partial(corpus):
    result = verify_evidence(
        [
            cite("show vlan brief", "30   SERVERS"),
            cite("show vlan brief", "99   FAKE_VLAN"),
        ],
        corpus,
    )

    assert result.status == "partial"
    assert result.verified_count == 1
    assert result.failed_count == 1
    assert "PARTIAL" in result.warning()


def test_failed_status_produces_an_explicit_warning(corpus):
    result = verify_evidence([cite("show vlan brief", "40   DATABASE")], corpus)

    warning = result.warning()
    assert warning is not None
    assert "EVIDENCE INTEGRITY FAILED" in warning
    assert "LOW" in warning


# --- E. whitespace handling -----------------------------------------------------------


def test_whitespace_differences_do_not_cause_false_failures(corpus):
    """Collapsed inner spacing is still a real citation."""
    result = verify_evidence([cite("show vlan brief", "30 SERVERS")], corpus)
    assert result.status == "passed"


def test_leading_and_trailing_whitespace_is_tolerated(corpus):
    result = verify_evidence([cite("show vlan brief", "   30   SERVERS   ")], corpus)
    assert result.status == "passed"


def test_tab_and_newline_normalisation(corpus):
    result = verify_evidence([cite("show vlan brief", "30\tSERVERS")], corpus)
    assert result.status == "passed"


def test_case_differences_are_tolerated(corpus):
    """Cisco output casing is inconsistent and is not a fidelity signal."""
    result = verify_evidence([cite("show vlan brief", "30   servers")], corpus)
    assert result.status == "passed"


def test_normalise_collapses_all_whitespace_forms():
    assert normalise("  a \t b \n c  ") == "a b c"
    assert normalise("SERVERS") == "servers"


def test_whitespace_tolerance_does_not_excuse_fabrication(corpus):
    """Normalisation must not be loose enough to make invented text match."""
    result = verify_evidence([cite("show vlan brief", "3 0   S E R V E R S")], corpus)
    assert result.status == "failed"


# --- F. wrong source command ----------------------------------------------------------


def test_wrong_source_command_fails(corpus):
    """Real text, but attributed to a command that was never supplied."""
    result = verify_evidence([cite("show interfaces trunk", "30   SERVERS")], corpus)

    assert result.status == "failed"
    assert result.failed_items[0].reason == "unknown_source_command"


def test_wrong_command_distinguishes_misattribution_from_fabrication(corpus):
    """A mis-attributed real quote and an invented quote are different failures, and the
    reviewer needs to be able to tell them apart."""
    misattributed = verify_evidence([cite("show interfaces trunk", "30   SERVERS")], corpus)
    fabricated = verify_evidence([cite("show interfaces trunk", "99   INVENTED")], corpus)

    assert "mis-attributed" in misattributed.failed_items[0].detail
    assert "does not appear in any supplied output" in fabricated.failed_items[0].detail


def test_citation_attributed_to_the_wrong_supplied_command_fails(corpus):
    """Both commands exist, but the excerpt belongs to the other one."""
    result = verify_evidence([cite("show ip route", "30   SERVERS")], corpus)

    assert result.status == "failed"
    assert result.failed_items[0].reason == "excerpt_not_found"
    assert "different supplied command" in result.failed_items[0].detail


# --- empty and edge cases -------------------------------------------------------------


def test_no_citations_while_declining_is_acceptable(corpus):
    """An honest 'I don't have enough evidence' makes no claim, so there is nothing to
    verify and nothing to fail."""
    result = verify_evidence([], corpus, insufficient_evidence=True)

    assert result.status == "passed"
    assert "made no evidential claims" in result.details


def test_no_citations_while_asserting_a_cause_fails(corpus):
    """Asserting a root cause with zero evidence is an unsupported claim."""
    result = verify_evidence([], corpus, insufficient_evidence=False)

    assert result.status == "failed"
    assert "without citing any evidence" in result.details


def test_empty_corpus_fails_every_citation():
    result = verify_evidence([cite("show vlan brief", "30   SERVERS")], {})

    assert result.status == "failed"
    assert result.failed_items[0].reason == "unknown_source_command"


def test_command_matching_is_case_and_space_insensitive(corpus):
    result = verify_evidence([cite("  SHOW   VLAN   BRIEF  ", "30   SERVERS")], corpus)
    assert result.status == "passed"


def test_result_counts_are_consistent(corpus):
    result = verify_evidence(
        [
            cite("show vlan brief", "30   SERVERS"),
            cite("show vlan brief", "40   DATABASE"),
            cite("show ip route", "Gateway of last resort is not set"),
        ],
        corpus,
    )

    assert result.total_count == 3
    assert result.verified_count == 2
    assert result.failed_count == 1
    assert result.has_failures is True
