"""Provider abstraction for the AI diagnosis call.

The rest of the application depends only on what is in this module: ``DiagnoseRequest``
goes in, ``ProviderResult`` comes out. No caller imports ``google.genai`` — swapping or
adding a provider is a change to ``factory.py`` plus one new file, and nothing else.

The request serialisation lives here too, deliberately. Rendering the prompt is part of the
provider contract: every provider must be handed the *same* text, or comparing their
answers would be meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from backend.app.models.case import Case, ShowOutput
from backend.app.models.diagnosis import AIDiagnosis
from backend.app.rules.engine import Finding

# ---------------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------------


@dataclass
class DiagnoseRequest:
    """Exactly what the model is allowed to see.

    Nothing outside these fields reaches the prompt. In particular the ``lab_state`` is
    *not* included: the model reasons from show output the way a human engineer would, and
    the structured state is reserved for the deterministic engine. That separation is what
    makes the evidence verifier meaningful — the model cannot cite a fact it was only given
    in machine-readable form.
    """

    symptom: str
    topology_note: str
    show_outputs: list[ShowOutput]
    rule_findings: list[Finding] = field(default_factory=list)

    case_id: Optional[str] = None
    concept_tag_hint: Optional[str] = None
    """Only ever None in production. Present so a test can pin a category."""

    @classmethod
    def from_case(cls, case: Case, rule_findings: list[Finding]) -> "DiagnoseRequest":
        """Build a request from a stored case.

        Note what is *not* copied: ``expected_fault``, ``expected_rule_ids``,
        ``expected_root_cause_keywords`` and ``expected_fix_steps``. Leaking ground truth
        into the prompt would make every evaluation of the AI worthless.
        """
        return cls(
            symptom=case.symptom,
            topology_note=case.topology_note,
            show_outputs=list(case.show_outputs),
            rule_findings=rule_findings,
            case_id=case.case_id,
        )

    # --- serialisation ----------------------------------------------------------------

    def render(self) -> str:
        """The user-content half of the call, in five clearly delimited sections.

        Structured objects are formatted explicitly rather than repr'd, so the prompt never
        contains Python syntax and the model sees stable, readable text.
        """
        return "\n\n".join(
            [
                self._section_symptom(),
                self._section_topology(),
                self._section_evidence(),
                self._section_rule_findings(),
                self._section_task(),
            ]
        )

    def _section_symptom(self) -> str:
        return f"USER SYMPTOM\n{self.symptom.strip()}"

    def _section_topology(self) -> str:
        return f"TOPOLOGY\n{self.topology_note.strip()}"

    def _section_evidence(self) -> str:
        if not self.show_outputs:
            return (
                "OBSERVED EVIDENCE\n(no show-command output was supplied for this case)"
            )
        blocks = [
            f"[{entry.device}] {entry.command}\n{entry.output.strip()}"
            for entry in self.show_outputs
        ]
        return "OBSERVED EVIDENCE\n" + "\n\n".join(blocks)

    def _section_rule_findings(self) -> str:
        """Deterministic findings, presented as already-verified context.

        These come from the rule engine reading the real configuration, so the model is told
        it may rely on them — unlike the show text, which it must quote to use.
        """
        if not self.rule_findings:
            return (
                "RULE FINDINGS\n(none — the deterministic checker found no configuration "
                "faults it is able to detect. This does not prove the network is healthy.)"
            )
        lines = []
        for finding in self.rule_findings:
            lines.append(
                f"[{finding.rule_id}] {finding.rule_name} "
                f"({finding.severity.value} / {finding.osi_layer.value} / "
                f"{finding.category.value}): {finding.message}"
            )
            for item in finding.evidence:
                lines.append(f"    - {item.source}: {item.detail}")
        return "RULE FINDINGS\n" + "\n".join(lines)

    def _section_task(self) -> str:
        commands = ", ".join(
            sorted({f"{e.device}: {e.command}" for e in self.show_outputs})
        ) or "(none)"
        return (
            "TASK\n"
            "Diagnose the most probable root cause of the reported symptom and return the "
            "JSON object described in the system instruction.\n\n"
            "Reminders for this request:\n"
            "  - Cite only from OBSERVED EVIDENCE above. Copy excerpts verbatim.\n"
            "  - Set source_command to one of the exact commands supplied: "
            f"{commands}\n"
            "  - If the evidence cannot establish a root cause, set insufficient_evidence "
            "to true and name the next command to run.\n"
            "  - Your output is a proposal awaiting human review. Do not state that any "
            "change has been made or verified."
        )

    def evidence_corpus(self) -> dict[str, str]:
        """Map of normalised command -> output text, used by the evidence verifier."""
        corpus: dict[str, str] = {}
        for entry in self.show_outputs:
            corpus.setdefault(entry.command.strip().lower(), "")
            corpus[entry.command.strip().lower()] += entry.output + "\n"
        return corpus


# ---------------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------------


@dataclass
class ProviderResult:
    """What a provider returns. Metadata beyond provider/model/latency is best-effort."""

    diagnosis: AIDiagnosis
    provider: str
    model: str
    latency_ms: int
    token_usage: Optional[dict[str, int]] = None
    raw_text: Optional[str] = None
    """The unparsed response, kept for debugging. Never contains credentials."""
    repair_attempts: int = 0
    """How many times the provider had to ask the model to fix invalid output."""


class ProviderError(RuntimeError):
    """A provider failed in a way the caller must handle.

    Provider implementations must never let a credential reach this message.
    """


# ---------------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """The whole surface the application depends on."""

    name: str
    model: str

    def diagnose(self, request: DiagnoseRequest) -> ProviderResult:
        """Produce a validated diagnosis, or raise ``ProviderError``."""
        ...

    def is_available(self) -> bool:
        """Whether this provider can actually be called right now (credentials present)."""
        ...
