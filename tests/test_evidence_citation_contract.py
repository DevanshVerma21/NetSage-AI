"""The evidence citation contract, pinned against real supplied output.

Live runs produced a substantively correct CASE-001 diagnosis in which all seven citations
were paraphrases, so the deterministic verifier failed every one and capped confidence at LOW.
The fix was to the prompt, not the verifier. These tests therefore do two things:

* assert the verifier's contract on CASE-001's **actual** supplied output — exact substring
  passes, paraphrase fails, whitespace and case differences pass, mis-attribution fails — so
  that "the verifier is too strict" can never be quietly resolved by loosening it;
* assert the prompt text still carries the clauses that were added to obtain that behaviour,
  so a later edit cannot silently drop them.

No model is called anywhere in this module.
"""

from __future__ import annotations

import pytest

from backend.app.ai.evidence_verifier import normalise, verify_evidence
from backend.app.models.diagnosis import Evidence
from backend.app.services.case_repo import load_cases

SWITCHPORT = "show interfaces Gi0/2 switchport"
IP_BRIEF = "show ip interface brief"

# The two lines the CASE-001 fault actually turns on, copied from data/cases.json.
EXACT_SWITCHPORT_LINE = "Access Mode VLAN: 30 (Inactive)"
EXACT_VLAN30_ROW = (
    "Vlan30                 192.168.30.1    YES manual administratively down down"
)


@pytest.fixture
def corpus():
    """CASE-001's supplied show output, keyed by command — the real evidence corpus."""
    case = next(c for c in load_cases() if c.case_id == "CASE-001")
    return {out.command: out.output for out in case.show_outputs}


def _verify(corpus, source_command, excerpt):
    return verify_evidence(
        [Evidence(source_command=source_command, excerpt=excerpt, why_it_matters="test")],
        corpus,
    )


# --- the corpus is what we think it is -----------------------------------------------------


def test_the_example_lines_really_are_in_the_supplied_output(corpus):
    """If this fails, the prompt's worked contract quotes output that no longer exists."""
    assert EXACT_SWITCHPORT_LINE in corpus[SWITCHPORT]
    assert EXACT_VLAN30_ROW in corpus[IP_BRIEF]


def test_there_is_no_vlan_30_row_to_quote(corpus):
    """The fault is an absence, which is why the prompt forbids quoting missing text."""
    assert "30   SERVERS" not in corpus["show vlan brief"]
    assert "\n30 " not in corpus["show vlan brief"]


# --- exact substring -> PASS ---------------------------------------------------------------


def test_an_exact_substring_passes(corpus):
    result = _verify(corpus, SWITCHPORT, EXACT_SWITCHPORT_LINE)
    assert result.status == "passed"
    assert result.verified_count == 1
    assert result.failed_count == 0


def test_an_exact_table_row_passes(corpus):
    result = _verify(corpus, IP_BRIEF, EXACT_VLAN30_ROW)
    assert result.status == "passed"


def test_a_partial_line_passes_because_it_is_still_contiguous(corpus):
    """A shorter contiguous span of a real line is a legitimate citation."""
    result = _verify(corpus, SWITCHPORT, "30 (Inactive)")
    assert result.status == "passed"


# --- paraphrase -> FAIL --------------------------------------------------------------------


@pytest.mark.parametrize(
    "excerpt",
    [
        "VLAN 30 is inactive",
        "Gi0/2 is an access port in VLAN 30, which is inactive",
        "the access VLAN on Gi0/2 is 30 and it is not active",
        "Access Mode VLAN 30 Inactive",  # punctuation removed - a normalisation
        "Access VLAN: 30 (Inactive)",  # one word dropped
    ],
)
def test_a_paraphrase_fails(corpus, excerpt):
    result = _verify(corpus, SWITCHPORT, excerpt)
    assert result.status == "failed"
    assert result.failed_items[0].reason == "excerpt_not_found"


def test_a_summary_of_a_table_fails(corpus):
    result = _verify(corpus, IP_BRIEF, "three SVIs are up and Vlan30 is down")
    assert result.status == "failed"


def test_an_annotated_excerpt_fails(corpus):
    """Real text plus the model's own commentary is no longer the supplied text."""
    result = _verify(corpus, SWITCHPORT, f"{EXACT_SWITCHPORT_LINE} <-- VLAN missing")
    assert result.status == "failed"


def test_an_invented_line_fails(corpus):
    """The line the model would like to have seen. Quoting an absence is impossible."""
    result = _verify(corpus, "show vlan brief", "30   SERVERS   active   Gi0/2")
    assert result.status == "failed"
    assert "does not appear anywhere" in result.failed_items[0].detail


# --- stitched text -> FAIL -----------------------------------------------------------------


def test_text_stitched_from_two_non_adjacent_lines_fails(corpus):
    result = _verify(corpus, IP_BRIEF, "Vlan10                 192.168.10.1 Vlan30")
    assert result.status == "failed"


def test_text_stitched_from_two_commands_fails(corpus):
    result = _verify(corpus, SWITCHPORT, f"{EXACT_SWITCHPORT_LINE} {EXACT_VLAN30_ROW}")
    assert result.status == "failed"


# --- altered whitespace and case -> the existing verifier contract -------------------------


def test_collapsed_whitespace_passes_per_the_existing_contract(corpus):
    """Documented behaviour, unchanged: runs of whitespace are collapsed before comparison.

    A model that reflowed a table's column padding still cited real evidence, and no amount
    of whitespace tolerance can make a fabricated address appear in the supplied text.
    """
    reflowed = "Vlan30 192.168.30.1 YES manual administratively down down"
    assert reflowed != EXACT_VLAN30_ROW
    assert _verify(corpus, IP_BRIEF, reflowed).status == "passed"


def test_tabs_and_newlines_are_treated_as_whitespace(corpus):
    result = _verify(corpus, SWITCHPORT, "Access Mode\tVLAN:\n30 (Inactive)")
    assert result.status == "passed"


def test_case_folding_passes_per_the_existing_contract(corpus):
    """Also unchanged: Cisco output casing is inconsistent and is not a fidelity signal."""
    assert _verify(corpus, SWITCHPORT, "access mode vlan: 30 (inactive)").status == "passed"


def test_normalise_is_whitespace_and_case_only(corpus):
    """Guard the boundary: normalisation must not start removing punctuation or words."""
    assert normalise("A  b\tC\n") == "a b c"
    assert normalise("Access Mode VLAN: 30 (Inactive)") == "access mode vlan: 30 (inactive)"
    assert normalise("30 (Inactive)") != normalise("30 Inactive")


# --- wrong command -> FAIL -----------------------------------------------------------------


def test_a_command_that_was_not_supplied_fails(corpus):
    result = _verify(corpus, "show vlan", EXACT_SWITCHPORT_LINE)
    assert result.status == "failed"
    assert result.failed_items[0].reason == "unknown_source_command"


def test_an_abbreviated_command_fails(corpus):
    """`sh ip int br` is not the supplied command string, so the citation is unattributable."""
    result = _verify(corpus, "sh ip int br", EXACT_VLAN30_ROW)
    assert result.status == "failed"
    assert result.failed_items[0].reason == "unknown_source_command"


def test_right_text_attributed_to_the_wrong_supplied_command_fails(corpus):
    """Mis-attribution is its own failure and is reported as such, not waved through."""
    result = _verify(corpus, "show vlan brief", EXACT_SWITCHPORT_LINE)
    assert result.status == "failed"
    assert result.failed_items[0].reason == "excerpt_not_found"
    assert "different supplied command" in result.failed_items[0].detail


# --- mixed outcomes ------------------------------------------------------------------------


def test_one_good_and_one_paraphrased_citation_is_partial(corpus):
    result = verify_evidence(
        [
            Evidence(
                source_command=SWITCHPORT,
                excerpt=EXACT_SWITCHPORT_LINE,
                why_it_matters="real",
            ),
            Evidence(
                source_command=SWITCHPORT,
                excerpt="VLAN 30 is inactive",
                why_it_matters="paraphrase",
            ),
        ],
        corpus,
    )
    assert result.status == "partial"
    assert (result.verified_count, result.failed_count) == (1, 1)


def test_a_failed_citation_keeps_its_original_text(corpus):
    """§7: never overwrite or repair a failed citation."""
    result = _verify(corpus, SWITCHPORT, "VLAN 30 is inactive")
    assert result.failed_items[0].excerpt == "VLAN 30 is inactive"


# --- the source_command contract (v1.2.1) --------------------------------------------------
#
# Live runs showed Gemini intermittently emitting "SW1: show vlan brief" for the supplied
# command "show vlan brief". The excerpts were verbatim and correct; all four citations still
# failed as unknown_source_command, capping a correct diagnosis at LOW. The verifier is right:
# a citation nobody can attribute is not evidence. These cases pin that contract so it cannot
# later be "fixed" by teaching the verifier to strip prefixes.

VLAN_BRIEF = "show vlan brief"
EXACT_VLAN20_ROW = "20   HR                               active    Gi0/1"


def test_a_supplied_command_is_valid(corpus):
    """A: 'show vlan brief' -> valid."""
    result = _verify(corpus, VLAN_BRIEF, EXACT_VLAN20_ROW)
    assert result.status == "passed"
    assert result.verified_count == 1


@pytest.mark.parametrize(
    "source_command",
    [
        "SW1: show vlan brief",          # B — the observed live failure
        "SW1 — show vlan brief",
        "SW1 show vlan brief",
        "show vlan brief (SW1)",         # D-shaped, on the VLAN command
    ],
)
def test_a_device_prefixed_command_is_invalid(corpus, source_command):
    """B/D: a correct excerpt under a device-decorated command is unattributable."""
    result = _verify(corpus, source_command, EXACT_VLAN20_ROW)
    assert result.status == "failed"
    assert result.failed_items[0].reason == "unknown_source_command"
    # The excerpt is preserved exactly as the model wrote it, never repaired.
    assert result.failed_items[0].excerpt == EXACT_VLAN20_ROW


@pytest.mark.parametrize(
    "source_command",
    [
        "R1: show ip route",             # C
        "show ip route (R1)",            # D
        "R1 - show ip route",
    ],
)
def test_a_device_decorated_route_command_is_invalid(corpus, source_command):
    """C/D: the same defect on a routing command, and 'show ip route' is genuinely supplied."""
    assert "show ip route" in corpus  # the undecorated form is available to be copied
    result = _verify(corpus, source_command, "Gateway of last resort is not set")
    assert result.status == "failed"
    assert result.failed_items[0].reason == "unknown_source_command"


def test_the_undecorated_route_command_is_valid(corpus):
    """G: correct command + correct excerpt -> valid. The control for the cases above."""
    result = _verify(corpus, "show ip route", "Gateway of last resort is not set")
    assert result.status == "passed"


def test_a_device_prefix_is_not_silently_stripped(corpus):
    """The fix is in the prompt. If someone teaches the verifier to strip 'SW1:', this fails."""
    decorated = _verify(corpus, "SW1: show vlan brief", EXACT_VLAN20_ROW)
    plain = _verify(corpus, VLAN_BRIEF, EXACT_VLAN20_ROW)
    assert plain.status == "passed"
    assert decorated.status == "failed"


# --- the prompt still carries the contract -------------------------------------------------


@pytest.mark.parametrize(
    "clause",
    [
        "contiguous substring",
        "No paraphrasing",
        "No summarising",
        "No normalising",
        "No stitching",
        "Absence is not quotable",
        "EVIDENCE CITATION CONTRACT",
        # The worked example lives on CASE-040 so CASE-001 stays uncontaminated for evaluation.
        "Vlan91 has an invalid subnet mask",  # the WRONG example
        "ip address 172.16.91.1 255.255.0.255",  # the RIGHT example
        # v1.2.1 — the source_command contract.
        "SOURCE_COMMAND MUST BE COPIED EXACTLY",
        "prepend a device name",
        "append a device name",
        "SW1: show vlan brief",  # the WRONG source_command example
        "show vlan brief (SW1)",
        "Do not infer or reconstruct",
    ],
)
def test_the_diagnose_prompt_states_the_contract(clause):
    from backend.app.ai.prompt_loader import load_prompt

    assert clause in load_prompt("diagnose_prompt").text


def test_the_worked_example_does_not_use_case_001_output(corpus):
    """The example must not teach CASE-001's answer — CASE-001 is the live smoke-test case."""
    from backend.app.ai.prompt_loader import load_prompt

    text = load_prompt("diagnose_prompt").text
    assert EXACT_SWITCHPORT_LINE not in text
    assert EXACT_VLAN30_ROW not in text
    for line in corpus[SWITCHPORT].splitlines():
        stripped = line.strip()
        if len(stripped) > 20:
            assert stripped not in text, stripped


def test_the_guardrails_state_the_contract():
    import re

    from backend.app.ai.prompt_loader import load_prompt

    # Collapse the file's own line wrapping before matching, so a reflowed paragraph does not
    # look like a missing clause.
    text = re.sub(r"\s+", " ", load_prompt("system_guardrails").text).lower()
    for clause in ("contiguous substring", "no stitching", "no paraphrasing", "no summarising"):
        assert clause in text, clause
