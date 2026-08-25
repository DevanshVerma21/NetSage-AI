"""Phase 2 pipeline demonstration.

Prints the AI diagnosis pipeline's behaviour on three scenarios, so the verification layers
can be inspected without a frontend and without an API key:

    1. the happy path      — CASE-001 through the mock provider
    2. an evidence failure — a provider that fabricates a citation
    3. confidence capping  — the same fabrication, showing model vs effective confidence

    python -m backend.scripts.phase2_demo
"""

from __future__ import annotations

from backend.app.ai.base import ProviderResult
from backend.app.ai.mock_provider import MockProvider
from backend.app.models.diagnosis import AIDiagnosis, Evidence
from backend.app.services import case_repo
from backend.app.services.diagnose import diagnose_case

RULE = "=" * 78
THIN = "-" * 78


class FabricatingProvider:
    """A deliberately dishonest provider, used to demonstrate that the verifier catches it.

    It claims high confidence and cites a VLAN that appears nowhere in the supplied output.
    """

    name = "fabricating-demo"
    model = "adversarial-test-double"

    def is_available(self) -> bool:
        return True

    def diagnose(self, request) -> ProviderResult:
        return ProviderResult(
            diagnosis=AIDiagnosis(
                root_cause=(
                    "VLAN 40 (DATABASE) is missing from the VLAN database on SW1, which is "
                    "why the file server is unreachable."
                ),
                confidence="high",
                confidence_score=0.94,
                osi_layer="L2",
                category="VLAN",
                evidence=[
                    Evidence(
                        source_command="show vlan brief",
                        excerpt="40   DATABASE                         active    Gi0/9",
                        why_it_matters=(
                            "Fabricated: this line does not exist in the supplied output."
                        ),
                    ),
                    Evidence(
                        source_command="show ip interface brief",
                        excerpt="Vlan40                 192.168.40.1    YES manual up   up",
                        why_it_matters="Also fabricated.",
                    ),
                ],
                insufficient_evidence=False,
                next_command="show vlan brief",
                notes_for_reviewer=(
                    "Adversarial test double for the Phase 2 demonstration. Both citations "
                    "are invented on purpose."
                ),
            ),
            provider=self.name,
            model=self.model,
            latency_ms=1,
        )


def print_result(result) -> None:
    for line in result.summary_lines():
        print(f"  {line}")


def scenario_happy_path(case) -> None:
    print(RULE)
    print("SCENARIO 1 — happy path: CASE-001 through the deterministic MOCK provider")
    print(RULE)

    result = diagnose_case(case, provider=MockProvider())
    print_result(result)

    print(f"\n  AI evidence citations ({len(result.ai.evidence)}), all verifier-checked:")
    for index, item in enumerate(result.ai.evidence, start=1):
        print(f"    [{index}] source_command: {item.source_command}")
        print(f"        excerpt        : {item.excerpt}")
        print(f"        why it matters : {item.why_it_matters}")

    print(f"\n  Verification: {result.evidence_verification.details}")
    print(f"\n  Reconciliation: {result.reconciliation.reason}")

    print(f"\n  Recommended fix steps ({len(result.ai.fix_steps)}) — proposals only:")
    for step in result.ai.fix_steps:
        print(f"    {step.order}. [{step.device}] risk={step.risk}")
        for command in step.cli_commands:
            print(f"         {command}")
        print(f"       rationale: {step.rationale}")

    print(f"\n  Verification steps ({len(result.ai.verification_steps)}):")
    for step in result.ai.verification_steps:
        print(f"    - {step.command}")
        print(f"      expect: {step.expected_result}")


def scenario_evidence_failure(case):
    print()
    print(RULE)
    print("SCENARIO 2 — evidence verification FAILURE (fabricated citations)")
    print(RULE)

    result = diagnose_case(case, provider=FabricatingProvider())
    print_result(result)

    print("\n  The provider claimed HIGH confidence. The verifier checked every citation")
    print("  against the supplied output and rejected all of them:")
    print()
    for item in result.evidence_verification.failed_items:
        print(f"    FAILED [{item.index}]  reason={item.reason}")
        print(f"      source_command : {item.source_command}")
        print(f"      excerpt        : {item.excerpt}")
        print(f"      why it failed  : {item.detail}")

    print("\n  The diagnosis is NOT discarded — the reviewer still sees it, alongside the")
    print("  warning. What changes is how much the system is willing to stand behind it.")
    return result


def scenario_confidence_capping(failed_result) -> None:
    print()
    print(RULE)
    print("SCENARIO 3 — confidence capping: model confidence vs effective confidence")
    print(RULE)

    decision = failed_result.confidence
    print(f"  model_confidence      : {decision.model_confidence.upper()} "
          f"({decision.model_confidence_score:.2f})   <- what the provider claimed")
    print(f"  effective_confidence  : {decision.effective_confidence.upper()} "
          f"({decision.effective_confidence_score:.2f})   <- what the system stands behind")
    print(f"  was_capped            : {decision.was_capped}")
    print()
    print("  Applied ceilings:")
    for cap in decision.applied_caps:
        print(f"    - condition : {cap.condition}")
        print(f"      ceiling   : {cap.ceiling.upper()}")
        print(f"      reason    : {cap.explanation}")
    print()
    print(f"  {decision.summary()}")

    print()
    print(THIN)
    print("  Both values are retained. The reviewer can always see the gap between the")
    print("  model's self-assessment and the independently verified result.")
    print(THIN)


def main() -> int:
    case_repo.clear_cache()
    case = case_repo.get_case("CASE-001", use_cache=False)
    if case is None:
        print("error: CASE-001 not found in the dataset")
        return 2

    print()
    print(RULE)
    print("NETSAGE AI — PHASE 2 AI DIAGNOSIS PIPELINE DEMONSTRATION")
    print("AI proposes. Deterministic rules verify. Human approves.")
    print(RULE)
    print("No API key and no network access are required for any scenario below.")
    print()

    scenario_happy_path(case)
    failed = scenario_evidence_failure(case)
    scenario_confidence_capping(failed)

    print()
    print(RULE)
    print("Every diagnosis above ends at status=awaiting_human_review with applied=False.")
    print("No fix has been applied, simulated or verified — that is Phase 3.")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
