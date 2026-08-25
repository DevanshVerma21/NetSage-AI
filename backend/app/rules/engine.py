"""The deterministic rule engine.

Design constraints that make this testable and trustworthy:

* A rule is a **pure function** of a :class:`RuleContext`. No I/O, no AI, no globals.
* A rule declares its metadata once, via the :func:`rule` decorator, so the catalogue
  is self-describing and the frontend needs no hard-coded rule table.
* Findings are ordered deterministically, so golden tests and CLI output are stable.

This engine runs *before* the AI (its findings become verified prompt context) and again
*after* a simulated fix (the before/after diff is the verification).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from pydantic import BaseModel, Field

from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.models.lab_state import IntendedFlow, LabState

# ---------------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------------

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


class RuleEvidence(BaseModel):
    """A structured fact from the lab state that supports a finding.

    Deliberately *not* the same thing as an AI evidence citation: this describes a fact
    the engine read out of the machine-readable state, whereas an AI citation must quote
    supplied show-command text verbatim (and is checked by the evidence verifier).
    """

    source: str = Field(description="Where the fact lives, e.g. 'SW1 / vlan database'")
    detail: str = Field(description="The fact itself, in one line")


class Finding(BaseModel):
    """One deterministic detection. Never a guess."""

    rule_id: str
    rule_name: str
    category: ConceptTag
    severity: Severity
    osi_layer: OSILayer
    message: str = Field(description="What is wrong, in one sentence")
    evidence: list[RuleEvidence] = Field(default_factory=list)
    affected: list[str] = Field(
        default_factory=list,
        description="Objects implicated, e.g. ['SW1', 'Vlan30', 'PC-HR']",
    )
    suggested_check: Optional[str] = Field(
        default=None,
        description="The Cisco command a human would run to confirm this",
    )
    suggested_mutation: Optional[dict] = Field(
        default=None,
        description="A typed LabState mutation that would resolve this finding. Used by "
        "the Fix Simulator only after a human has approved the diagnosis.",
    )
    confidence: str = Field(
        default="deterministic",
        description="Always 'deterministic' — a rule either matched or it did not.",
    )

    @property
    def sort_key(self) -> tuple[int, str, str]:
        return (_SEVERITY_ORDER[self.severity], self.rule_id, ",".join(self.affected))


# ---------------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleMeta:
    id: str
    name: str
    category: ConceptTag
    severity: Severity
    osi_layer: OSILayer
    description: str
    mandatory: bool = False
    suggested_check: Optional[str] = None


@dataclass
class RuleContext:
    """Everything a rule is allowed to look at."""

    state: LabState
    intended_flows: list[IntendedFlow] = field(default_factory=list)


RuleFunc = Callable[[RuleContext], list[Finding]]

_REGISTRY: dict[str, tuple[RuleMeta, RuleFunc]] = {}


def rule(
    *,
    id: str,
    name: str,
    category: ConceptTag,
    severity: Severity,
    osi_layer: OSILayer,
    description: str,
    mandatory: bool = False,
    suggested_check: Optional[str] = None,
) -> Callable[[RuleFunc], RuleFunc]:
    """Register a rule function under its metadata."""

    meta = RuleMeta(
        id=id,
        name=name,
        category=category,
        severity=severity,
        osi_layer=osi_layer,
        description=description,
        mandatory=mandatory,
        suggested_check=suggested_check,
    )

    def decorator(func: RuleFunc) -> RuleFunc:
        if id in _REGISTRY:
            raise ValueError(f"duplicate rule id: {id}")
        _REGISTRY[id] = (meta, func)
        func.rule_meta = meta  # type: ignore[attr-defined]
        return func

    return decorator


def registry() -> dict[str, RuleMeta]:
    """The rule catalogue, id -> metadata. Powers the API and the frontend."""
    return {rid: meta for rid, (meta, _) in sorted(_REGISTRY.items())}


def mandatory_rule_ids() -> list[str]:
    """The six checks the company document names explicitly."""
    return sorted(rid for rid, (meta, _) in _REGISTRY.items() if meta.mandatory)


def make_finding(meta: RuleMeta, **kwargs) -> Finding:
    """Build a Finding, defaulting the fields that come from rule metadata.

    Individual findings may override severity (for example, a down interface that
    carries no IP is less serious than a down SVI).
    """
    kwargs.setdefault("severity", meta.severity)
    kwargs.setdefault("osi_layer", meta.osi_layer)
    kwargs.setdefault("category", meta.category)
    kwargs.setdefault("suggested_check", meta.suggested_check)
    return Finding(rule_id=meta.id, rule_name=meta.name, **kwargs)


# ---------------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------------


def run_rules(
    state: LabState,
    intended_flows: Optional[Iterable[IntendedFlow]] = None,
    only: Optional[Iterable[str]] = None,
) -> list[Finding]:
    """Run every registered rule (or just ``only``) and return sorted findings.

    A rule that raises is *not* allowed to take the whole engine down — it is reported
    as an engine error finding so the failure is visible rather than silent.
    """
    ctx = RuleContext(state=state, intended_flows=list(intended_flows or []))
    wanted = set(only) if only is not None else None

    findings: list[Finding] = []
    for rule_id, (meta, func) in _REGISTRY.items():
        if wanted is not None and rule_id not in wanted:
            continue
        try:
            findings.extend(func(ctx))
        except Exception as exc:  # pragma: no cover - defensive
            findings.append(
                Finding(
                    rule_id=meta.id,
                    rule_name=meta.name,
                    category=meta.category,
                    severity=Severity.LOW,
                    osi_layer=meta.osi_layer,
                    message=f"Rule {meta.id} failed to evaluate: {type(exc).__name__}: {exc}",
                    confidence="engine-error",
                )
            )

    findings.sort(key=lambda f: f.sort_key)
    return findings


def _import_checks() -> None:
    """Import the check modules so their decorators register.

    Imported at the bottom of the module to avoid a circular import: the check modules
    import ``rule``/``make_finding`` from here.
    """
    from backend.app.rules import checks  # noqa: F401


_import_checks()
