"""Sanity test: the clean topology must fire no rules at all.

If this fails, every negative test in the suite is meaningless, so it runs first.
"""

from __future__ import annotations

from backend.app.rules.engine import run_rules
from tests.conftest import clean_flows, clean_state


def test_clean_topology_fires_no_rules():
    findings = run_rules(clean_state(), clean_flows())
    assert findings == [], f"clean topology unexpectedly fired: {[f.rule_id for f in findings]}"


def test_all_six_mandatory_rules_are_registered():
    from backend.app.rules.engine import mandatory_rule_ids

    assert mandatory_rule_ids() == ["R001", "R002", "R003", "R004", "R005", "R006"]


def test_registry_exposes_metadata_for_every_rule():
    from backend.app.rules.engine import registry

    for rule_id, meta in registry().items():
        assert meta.id == rule_id
        assert meta.name
        assert meta.description
