"""The troubleshooting case model.

Field names track the company document's "Evidence per case" requirement exactly:
symptom, topology note, show outputs, expected fault, OSI layer, concept tag — plus
severity, which the document's `cases.csv` deliverable and dashboard both require.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.app.models.enums import ConceptTag, OSILayer, Severity, SourceLabel
from backend.app.models.lab_state import IntendedFlow, LabState


class ShowOutput(BaseModel):
    """One captured show-command output.

    ``output`` is realistic Cisco-style text. It is the evidence the AI must cite from,
    and the evidence verifier matches AI citations against it verbatim.
    """

    device: str = Field(description="Device the command was run on, e.g. SW1")
    command: str = Field(description="Exact command, e.g. 'show vlan brief'")
    output: str = Field(description="Realistic Cisco-style output text")


class Case(BaseModel):
    case_id: str = Field(description="Stable identifier, e.g. CASE-001")
    title: str

    # --- the six evidence fields the document mandates -------------------------------
    symptom: str = Field(description="What the user reports, in their words")
    topology_note: str = Field(description="Device / VLAN / link layout in prose")
    show_outputs: list[ShowOutput] = Field(min_length=1)
    expected_fault: str = Field(description="Ground truth: the actual fault")
    osi_layer: OSILayer
    concept_tag: ConceptTag

    # --- required by the cases.csv deliverable and the dashboard ----------------------
    severity: Severity

    # --- grading / evaluation support ------------------------------------------------
    expected_root_cause_keywords: list[str] = Field(
        default_factory=list,
        description="Used to score an AI diagnosis against the known correct answer",
    )
    expected_rule_ids: list[str] = Field(
        default_factory=list,
        description="Rule IDs the deterministic engine must fire on this case. "
        "Asserted by the golden test, which validates dataset and engine together.",
    )
    expected_fix_steps: list[str] = Field(default_factory=list)

    security_relevant: bool = Field(
        default=False,
        description="True for faults that are a security exposure, not just an outage "
        "(e.g. guest Wi-Fi reaching an internal server).",
    )

    # --- the machine-readable network ------------------------------------------------
    lab_state: LabState
    intended_flows: list[IntendedFlow] = Field(default_factory=list)

    # --- provenance: the prototype never claims a real hardware capture --------------
    source_label: SourceLabel = SourceLabel.SIMULATED_LAB

    def show_output_for(self, command: str, device: Optional[str] = None) -> Optional[ShowOutput]:
        """Look up a captured output by command (and optionally device)."""
        wanted = command.strip().lower()
        for entry in self.show_outputs:
            if entry.command.strip().lower() != wanted:
                continue
            if device and entry.device.lower() != device.lower():
                continue
            return entry
        return None

    def all_output_text(self) -> str:
        """Every show output concatenated — the corpus the evidence verifier searches."""
        return "\n".join(entry.output for entry in self.show_outputs)


class CaseSummary(BaseModel):
    """Lightweight projection for the case-library list view."""

    case_id: str
    title: str
    symptom: str
    concept_tag: ConceptTag
    osi_layer: OSILayer
    severity: Severity
    security_relevant: bool
    source_label: SourceLabel

    @classmethod
    def from_case(cls, case: Case) -> "CaseSummary":
        return cls(
            case_id=case.case_id,
            title=case.title,
            symptom=case.symptom,
            concept_tag=case.concept_tag,
            osi_layer=case.osi_layer,
            severity=case.severity,
            security_relevant=case.security_relevant,
            source_label=case.source_label,
        )
