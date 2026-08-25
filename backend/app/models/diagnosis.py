"""The structured AI diagnosis schema.

This module is a **leaf**: it imports nothing from ``backend.app.ai`` so the provider,
verifier and reconciler modules can all depend on it without a cycle.

Every field type is a ``Literal`` rather than a Python ``Enum``. That is deliberate: the
Gemini SDK converts this model into its own schema dialect, and ``Literal`` converts into a
clean ``{"type": "STRING", "enum": [...]}`` with no ``$defs``/``$ref`` indirection. The
values are kept identical to the internal enums in ``models/enums.py`` so conversion in
either direction is exact — see the ``as_*`` helpers at the bottom.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.enums import ConceptTag, Confidence, OSILayer

# --- Literal aliases, kept in lockstep with models/enums.py -----------------------------

ConfidenceLiteral = Literal["low", "medium", "high"]
OSILayerLiteral = Literal["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
CategoryLiteral = Literal[
    "VLAN",
    "GATEWAY",
    "DHCP",
    "DNS",
    "ROUTING",
    "ACL",
    "NAT",
    "WIRELESS",
    "INTERFACE_CONFIG",
]
RiskLiteral = Literal["low", "medium", "high"]
IntegrityLiteral = Literal["passed", "partial", "failed"]
ReconciliationLiteral = Literal["agree", "partial", "ai_only", "rules_only", "conflict"]

# Numeric band each confidence label must fall inside (constraint 16 of the prompt).
CONFIDENCE_BANDS: dict[str, tuple[float, float]] = {
    "low": (0.0, 0.4),
    "medium": (0.4, 0.75),
    "high": (0.75, 1.0),
}

CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


class Evidence(BaseModel):
    """One citation. ``excerpt`` must appear verbatim in the output of ``source_command``.

    The evidence verifier checks this mechanically; the model's assertion is not trusted.
    """

    model_config = ConfigDict(extra="forbid")

    source_command: str = Field(
        min_length=1,
        description="Exact command the excerpt came from, e.g. 'show vlan brief'",
    )
    excerpt: str = Field(
        min_length=1,
        description="Text copied verbatim from that command's supplied output",
    )
    why_it_matters: str = Field(
        min_length=1,
        description="Interpretation of the excerpt. Inference belongs here, not in excerpt.",
    )


class AlternativeHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: str = Field(min_length=1)
    why_less_likely: str = Field(min_length=1)


class FixStep(BaseModel):
    """A recommended configuration step. Never a record of an executed action."""

    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1, description="1-based execution order")
    device: str = Field(min_length=1)
    cli_commands: list[str] = Field(
        min_length=1, description="Exact IOS commands a human would type, in order"
    )
    rationale: str = Field(min_length=1)
    risk: RiskLiteral


class VerificationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    expected_result: str = Field(
        min_length=1, description="A concrete expected observation, not 'check it worked'"
    )


class AIDiagnosis(BaseModel):
    """The model's proposal. Never authoritative on its own.

    Field names match the company document verbatim where the document names them:
    ``root_cause``, ``confidence``, ``evidence``, ``next_command``, ``fix_steps``.
    """

    model_config = ConfigDict(extra="forbid")

    root_cause: str = Field(min_length=1)
    confidence: ConfidenceLiteral
    confidence_score: float = Field(ge=0.0, le=1.0)
    osi_layer: OSILayerLiteral
    category: CategoryLiteral
    evidence: list[Evidence]
    insufficient_evidence: bool
    next_command: str = Field(
        min_length=1, description="Required even at high confidence"
    )
    alternative_hypotheses: list[AlternativeHypothesis] = Field(default_factory=list)
    fix_steps: list[FixStep] = Field(default_factory=list)
    verification_steps: list[VerificationStep] = Field(default_factory=list)
    notes_for_reviewer: str = Field(min_length=1)

    # --- structural validation ---------------------------------------------------------

    @model_validator(mode="after")
    def _evidence_required_unless_insufficient(self) -> "AIDiagnosis":
        """A confident diagnosis with no citations is exactly what this system exists to
        prevent, so it is rejected at the schema boundary rather than merely flagged."""
        if not self.evidence and not self.insufficient_evidence:
            raise ValueError(
                "evidence must contain at least one item unless insufficient_evidence is true"
            )
        return self

    @model_validator(mode="after")
    def _fix_steps_ordering_is_sane(self) -> "AIDiagnosis":
        if self.fix_steps:
            orders = [step.order for step in self.fix_steps]
            if sorted(orders) != list(range(1, len(orders) + 1)):
                raise ValueError(
                    f"fix_steps order must be a 1-based contiguous sequence, got {orders}"
                )
        return self

    # --- convenience -------------------------------------------------------------------

    @property
    def confidence_score_matches_band(self) -> bool:
        """Whether ``confidence_score`` sits inside the band its label implies.

        Reported to the reviewer rather than enforced: a mismatch is a calibration signal,
        not grounds for discarding an otherwise usable diagnosis.
        """
        low, high = CONFIDENCE_BANDS[self.confidence]
        return low <= self.confidence_score <= high

    def as_osi_layer(self) -> OSILayer:
        return OSILayer(self.osi_layer)

    def as_category(self) -> ConceptTag:
        return ConceptTag(self.category)

    def as_confidence(self) -> Confidence:
        return Confidence(self.confidence)

    def claims_a_root_cause(self) -> bool:
        """Whether the model actually committed to a cause, as opposed to declining."""
        return not self.insufficient_evidence
