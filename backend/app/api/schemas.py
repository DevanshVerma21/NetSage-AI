"""Request and response models for the HTTP layer.

Kept separate from the storage models so the wire contract can stay stable while the
records evolve, and so no request model can smuggle in a field the services do not accept.

One field is deliberately absent from every request model in this file: a mutation. The
Fix Simulator's changes are derived from stored deterministic findings, so there is no
request shape through which a client could describe a configuration change it wants made.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models.lab_state import IntendedFlow, LabState
from backend.app.rules.engine import Finding


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    cases_loaded: int
    rules_registered: int
    mandatory_rules: list[str]
    llm_provider: str
    llm_model: str
    provider_configured: bool = Field(
        description="Whether the selected provider has credentials. Never the key itself."
    )
    human_review_required: Literal[True] = True
    execution_scope: str


class RuleCheckRequest(BaseModel):
    """Either name a stored case, or supply a lab state directly.

    This endpoint never calls the AI. It is the deterministic checker over HTTP.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: Optional[str] = None
    lab_state: Optional[LabState] = None
    intended_flows: list[IntendedFlow] = Field(default_factory=list)
    only: list[str] = Field(
        default_factory=list, description="Restrict to these rule ids, e.g. ['R005']"
    )


class RuleCheckResponse(BaseModel):
    case_id: Optional[str] = None
    findings: list[Finding]
    rule_ids: list[str]
    finding_count: int
    ai_used: Literal[False] = False


class DiagnoseRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    provider: Optional[Literal["gemini", "mock", "anthropic"]] = Field(
        default=None,
        description="Override the configured provider. Tests and demos use 'mock'.",
    )


class ReviewRequestBody(BaseModel):
    """A human verdict.

    ``edited`` requires a reason code and at least one correction; ``rejected`` requires a
    reason code and notes. Those rules are enforced in the service layer so they hold for
    every caller, not only this endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    diagnosis_id: str
    verdict: Literal["accepted", "edited", "rejected"]
    reviewer: str = "human-reviewer"
    reason_code: Optional[str] = None
    notes: Optional[str] = None

    corrected_root_cause: Optional[str] = None
    corrected_osi_layer: Optional[str] = None
    corrected_category: Optional[str] = None
    corrected_rule_ids: list[str] = Field(
        default_factory=list,
        description="Optionally narrow the simulated fix to these findings. Must be rule "
        "ids the engine actually reported on this diagnosis.",
    )
    corrected_fix_steps: list[str] = Field(default_factory=list)


class ApplyFixRequestBody(BaseModel):
    """Which human approval to act on.

    ``review_id`` is the normal path. ``diagnosis_id`` is accepted as an alternative and the
    server looks the review up itself — which is what makes "apply a fix to something nobody
    reviewed" answerable with a 409 rather than a confusing 404 about a review id the caller
    never had. Either way the client names a record, never a change.
    """

    model_config = ConfigDict(extra="forbid")

    review_id: Optional[str] = None
    diagnosis_id: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ApplyFixRequestBody":
        if bool(self.review_id) == bool(self.diagnosis_id):
            raise ValueError("supply exactly one of review_id or diagnosis_id")
        return self
