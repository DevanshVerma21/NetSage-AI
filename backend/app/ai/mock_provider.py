"""Deterministic offline provider.

Purpose: make the entire AI pipeline — schema validation, evidence verification,
reconciliation, confidence capping — testable and demonstrable with **no API key and no
network**. Every stored record is stamped ``provider="mock"`` and every diagnosis says so
in ``notes_for_reviewer``, so a mock answer can never be mistaken for a real model answer.

It is not a stub that returns a fixed blob. It reasons from the deterministic rule findings
and extracts **real excerpts from the supplied show output**, so the citations it produces
genuinely pass the evidence verifier — which means the offline happy path exercises the same
code the live path does.
"""

from __future__ import annotations

import re
import time
from typing import Iterable, Optional

from backend.app.ai.base import DiagnoseRequest, ProviderResult
from backend.app.models.diagnosis import (
    AIDiagnosis,
    AlternativeHypothesis,
    Evidence,
    FixStep,
    VerificationStep,
)
from backend.app.rules.engine import Finding

MOCK_NOTE = (
    "Produced by the deterministic MOCK provider (provider=\"mock\"), not by a language "
    "model. It is derived mechanically from the deterministic rule findings and the "
    "supplied show output so the pipeline can be demonstrated and tested offline. Treat its "
    "wording as a stand-in, not as model reasoning. Human review is still required."
)

MAX_EVIDENCE_ITEMS = 3
MAX_ALTERNATIVES = 3

# Dependency order for remediation, lowest first. Creating Layer 2 objects must precede
# bringing interfaces up, which must precede routing, and end-host changes come last.
_MUTATION_ORDER: dict[str, int] = {
    "add_vlan": 10,
    "enable_ip_routing": 20,
    "set_interface_admin_state": 30,
    "add_static_route": 40,
    "set_host_mask": 50,
    "set_host_gateway": 60,
    "resolve_duplicate_ip": 70,
}

# Lines that carry no citable content.
_NOISE = re.compile(
    r"^\s*$|^[-=\s]+$|^Building configuration|^Current configuration|^!+$|^end$",
    re.IGNORECASE,
)

# Lines that state a fault condition outright. These are what a competent engineer would
# actually quote, so they are weighted far above a mere keyword match.
_FAULT_SIGNALS = (
    re.compile(r"administratively\s+down", re.IGNORECASE),
    re.compile(r"\bdown\b[\s\S]*?\bdown\b", re.IGNORECASE),
    re.compile(r"\(inactive\)|\binactive\b", re.IGNORECASE),
    re.compile(r"^\s*shutdown\s*$", re.IGNORECASE),
    re.compile(r"request timed out", re.IGNORECASE),
    re.compile(r"100%\s*loss|\(100% loss\)", re.IGNORECASE),
    re.compile(r"gateway of last resort is not set", re.IGNORECASE),
    re.compile(r"err-disabled|errdisable", re.IGNORECASE),
    re.compile(r"^\s*deny\b", re.IGNORECASE),
)

# Command echoes, banners and table headers: real text, but not evidence of anything.
_LOW_VALUE = (
    re.compile(r"^\s*[\w][\w.-]*\s*>"),           # "PC-HR> ping ..."
    re.compile(r"^Pinging\b", re.IGNORECASE),
    re.compile(r"^Ping statistics", re.IGNORECASE),
    re.compile(r"^\s*Codes:", re.IGNORECASE),
    re.compile(r"^\s*Packets:\s*Sent", re.IGNORECASE),
    re.compile(r"^\s*(Approximate|Minimum)\b", re.IGNORECASE),
    re.compile(r"^Interface\s+IP-Address\s+OK\?", re.IGNORECASE),
    re.compile(r"^VLAN\s+Name\s+Status", re.IGNORECASE),
    re.compile(r"^Protocol\s+Address\s+Age", re.IGNORECASE),
    re.compile(r":\s*$"),                          # a bare label line
)



class MockProvider:
    """Offline provider. Requires nothing and reaches nothing."""

    def __init__(self, model: str = "deterministic-rules-v1") -> None:
        self.name = "mock"
        self.model = model

    def is_available(self) -> bool:
        """Always available — that is the entire point of this provider."""
        return True

    def diagnose(self, request: DiagnoseRequest) -> ProviderResult:
        started = time.perf_counter()
        diagnosis = self._build(request)
        latency_ms = int((time.perf_counter() - started) * 1000)

        return ProviderResult(
            diagnosis=diagnosis,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            token_usage=None,  # No tokens are consumed; reporting a number would be a lie.
            raw_text=None,
            repair_attempts=0,
        )

    # --- construction ------------------------------------------------------------------

    def _build(self, request: DiagnoseRequest) -> AIDiagnosis:
        findings = list(request.rule_findings)
        if not findings:
            return self._insufficient_evidence_diagnosis(request)
        return self._finding_based_diagnosis(request, findings)

    def _insufficient_evidence_diagnosis(self, request: DiagnoseRequest) -> AIDiagnosis:
        """With no deterministic findings there is nothing to ground a cause in.

        Declining is the correct behaviour here, and it exercises the insufficient-evidence
        branch of the pipeline offline.
        """
        evidence = self._extract_evidence(request, tokens=[], limit=1)
        return AIDiagnosis(
            root_cause=(
                "Cannot be established from the supplied evidence. The deterministic "
                "checker found no configuration fault it is able to detect, and the "
                "supplied show output does not isolate a cause for the reported symptom."
            ),
            confidence="low",
            confidence_score=0.15,
            osi_layer="L3",
            category=self._category_hint(request),
            evidence=evidence,
            insufficient_evidence=True,
            next_command=self._next_command(request, None),
            alternative_hypotheses=[
                AlternativeHypothesis(
                    cause="A fault outside the scope of the implemented deterministic rules.",
                    why_less_likely=(
                        "No rule matched, but the rule catalogue is not exhaustive, so this "
                        "cannot be excluded."
                    ),
                ),
                AlternativeHypothesis(
                    cause="A fault visible only in output that was not captured.",
                    why_less_likely=(
                        "Consistent with the symptom, but unverifiable from the supplied "
                        "evidence."
                    ),
                ),
            ],
            fix_steps=[],  # Nothing is proposed without a grounded cause.
            verification_steps=[
                VerificationStep(
                    command=self._next_command(request, None),
                    expected_result=(
                        "Output that either confirms or excludes a fault on the path "
                        "described in the symptom."
                    ),
                )
            ],
            notes_for_reviewer=(
                "No root cause is proposed and no fix steps are offered, because the "
                f"evidence does not support either. {MOCK_NOTE}"
            ),
        )

    def _finding_based_diagnosis(
        self, request: DiagnoseRequest, findings: list[Finding]
    ) -> AIDiagnosis:
        primary = self._select_primary(findings)
        corroborating = [
            f for f in findings if f is not primary and f.category == primary.category
        ]

        tokens = self._tokens_for(findings)
        evidence = self._extract_evidence(request, tokens, limit=MAX_EVIDENCE_ITEMS)

        confidence, score = self._calibrate(findings, corroborating, evidence)

        return AIDiagnosis(
            root_cause=self._root_cause_text(primary, findings),
            confidence=confidence,
            confidence_score=score,
            osi_layer=primary.osi_layer.value,
            category=primary.category.value,
            evidence=evidence,
            insufficient_evidence=False,
            next_command=self._next_command(request, primary),
            alternative_hypotheses=self._alternatives(primary, findings),
            fix_steps=self._fix_steps(findings),
            verification_steps=self._verification_steps(findings),
            notes_for_reviewer=self._notes(primary, findings),
        )

    def _select_primary(self, findings: list[Finding]) -> Finding:
        """Choose which finding to treat as the root cause.

        Severity alone is not enough. A compound fault typically produces one underlying
        cause plus several consequences at equal severity — a shut-down SVI and a
        never-created VLAN are both Critical, but only one of them is the reason for the
        other. Among the most severe findings, this prefers the fault *family* with the most
        corroborating findings, on the reasoning that the cause generating the most
        downstream symptoms is the more likely root.

        Fully deterministic: ties break on rule_id, then message.
        """
        severity_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        best_rank = min(severity_rank[f.severity.value] for f in findings)
        top = [f for f in findings if severity_rank[f.severity.value] == best_rank]

        category_counts: dict[str, int] = {}
        for finding in findings:
            key = finding.category.value
            category_counts[key] = category_counts.get(key, 0) + 1

        return sorted(
            top,
            key=lambda f: (
                -category_counts[f.category.value],
                f.rule_id,
                f.message,
            ),
        )[0]


    # --- evidence extraction -----------------------------------------------------------

    def _tokens_for(self, findings: Iterable[Finding]) -> list[str]:
        """Search terms drawn from the findings: affected object names plus any IPs."""
        tokens: list[str] = []
        for finding in findings:
            tokens.extend(finding.affected)
            for item in finding.evidence:
                tokens.extend(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", item.detail))
        seen: set[str] = set()
        ordered: list[str] = []
        for token in tokens:
            key = token.lower()
            if key in seen or len(key) < 3:
                continue
            seen.add(key)
            ordered.append(token)
        return ordered

    def _extract_evidence(
        self, request: DiagnoseRequest, tokens: list[str], limit: int
    ) -> list[Evidence]:
        """Pick the most diagnostic real lines out of the supplied output.

        Every excerpt is a verbatim line from a named command, so these citations pass the
        evidence verifier for the same reason a careful model's would. Selection prefers
        lines that *state a fault* over lines that merely mention a matched name, and spreads
        citations across different commands so the diagnosis is corroborated rather than
        quoting one output three times.
        """
        lowered = [t.lower() for t in tokens]
        preferred = self._commands_referenced_by_findings(request)

        candidates: list[tuple[int, int, int, str, str]] = []
        for output_index, entry in enumerate(request.show_outputs):
            for line_index, raw_line in enumerate(entry.output.splitlines()):
                line = raw_line.rstrip()
                if _NOISE.match(line) or len(line.strip()) < 8:
                    continue
                score = self._score_line(line, lowered, entry.command, preferred)
                # Negative score first so a plain ascending sort is best-first, with
                # document order as a deterministic tie-break.
                candidates.append((-score, output_index, line_index, entry.command, line))

        if not candidates:
            return []

        candidates.sort()
        return self._select_diverse(candidates, tokens, limit)

    def _score_line(
        self, line: str, lowered_tokens: list[str], command: str, preferred: set[str]
    ) -> int:
        score = 0

        for pattern in _FAULT_SIGNALS:
            if pattern.search(line):
                score += 6

        score += 2 * sum(1 for token in lowered_tokens if token in line.lower())

        if command.strip().lower() in preferred:
            score += 3

        for pattern in _LOW_VALUE:
            if pattern.search(line):
                score -= 5
                break

        return score

    def _commands_referenced_by_findings(self, request: DiagnoseRequest) -> set[str]:
        """Commands the rule engine itself nominated as the way to confirm its findings."""
        referenced: set[str] = set()
        for finding in request.rule_findings:
            if not finding.suggested_check:
                continue
            for part in finding.suggested_check.split("/"):
                referenced.add(part.strip().lower())
        return referenced

    def _select_diverse(
        self,
        candidates: list[tuple[int, int, int, str, str]],
        tokens: list[str],
        limit: int,
    ) -> list[Evidence]:
        """Greedy best-first selection, at most one citation per command on the first pass."""
        chosen: list[Evidence] = []
        seen_excerpts: set[str] = set()
        used_commands: set[str] = set()

        for allow_repeat_command in (False, True):
            for negative_score, _oi, _li, command, line in candidates:
                if len(chosen) >= limit:
                    return chosen
                if negative_score >= 0:
                    # Score of zero or below means nothing about this line is diagnostic.
                    continue
                excerpt = line.strip()
                if excerpt in seen_excerpts:
                    continue
                if not allow_repeat_command and command in used_commands:
                    continue
                seen_excerpts.add(excerpt)
                used_commands.add(command)
                chosen.append(
                    Evidence(
                        source_command=command,
                        excerpt=excerpt,
                        why_it_matters=self._why_it_matters(excerpt, tokens),
                    )
                )

        # Nothing scored as diagnostic: cite the single best available line so the diagnosis
        # is still grounded in something real rather than in nothing.
        if not chosen and candidates:
            _score, _oi, _li, command, line = candidates[0]
            chosen.append(
                Evidence(
                    source_command=command,
                    excerpt=line.strip(),
                    why_it_matters=self._why_it_matters(line.strip(), tokens),
                )
            )

        return chosen


    def _why_it_matters(self, excerpt: str, tokens: list[str]) -> str:
        matched = [t for t in tokens if t.lower() in excerpt.lower()]
        lowered = excerpt.lower()

        if "administratively down" in lowered:
            return (
                "The interface is shut down in configuration, so the subnet it terminates "
                "has no active gateway and produces no connected route."
            )
        if "down" in lowered and "up" not in lowered:
            return "The interface is not forwarding, so traffic through it cannot be delivered."
        if "inactive" in lowered:
            return (
                "The port's access VLAN is marked Inactive, which happens when that VLAN "
                "does not exist in the switch's VLAN database."
            )
        if "request timed out" in lowered:
            return (
                "The destination does not answer, confirming the reported symptom is a real "
                "loss of reachability rather than an application-level problem."
            )
        if "reply from" in lowered:
            return (
                "This path does answer, which narrows the fault to somewhere beyond this hop."
            )
        if matched:
            return (
                f"Directly references {', '.join(matched[:3])}, which the deterministic "
                "checker implicated in this fault."
            )
        return (
            "Supplied context for the reported symptom. It does not on its own isolate the "
            "cause, which is why further output is requested."
        )

    # --- calibration -------------------------------------------------------------------

    def _calibrate(
        self,
        findings: list[Finding],
        corroborating: list[Finding],
        evidence: list[Evidence],
    ) -> tuple[str, float]:
        """Confidence follows corroboration, exactly as the prompt requires of a model.

        The capping layer will re-check this independently; agreeing with it here is what
        makes the offline happy path realistic.
        """
        if len(evidence) >= 2 and corroborating:
            return "high", 0.85
        if evidence:
            return "medium", 0.6
        return "low", 0.3

    # --- text construction -------------------------------------------------------------

    def _root_cause_text(self, primary: Finding, findings: list[Finding]) -> str:
        text = primary.message.rstrip(".")
        others = len(findings) - 1
        if others > 0:
            text += (
                f". The deterministic checker reported {others} further finding"
                f"{'s' if others != 1 else ''} that are consistent with this as the single "
                "underlying cause"
            )
        return text + "."

    def _next_command(self, request: DiagnoseRequest, primary: Optional[Finding]) -> str:
        if primary and primary.suggested_check:
            # suggested_check may list alternatives separated by '/'; take the first.
            return primary.suggested_check.split("/")[0].strip()
        if request.show_outputs:
            return request.show_outputs[0].command
        return "show running-config"

    def _alternatives(
        self, primary: Finding, findings: list[Finding]
    ) -> list[AlternativeHypothesis]:
        alternatives: list[AlternativeHypothesis] = []
        seen: set[str] = {primary.rule_id}

        for finding in findings:
            if finding.rule_id in seen or len(alternatives) >= MAX_ALTERNATIVES:
                continue
            seen.add(finding.rule_id)
            alternatives.append(
                AlternativeHypothesis(
                    cause=f"{finding.rule_name}: {finding.message.rstrip('.')}.",
                    why_less_likely=(
                        "Also detected deterministically, but it is more likely a "
                        f"consequence of {primary.rule_id} ({primary.rule_name}) than an "
                        "independent fault."
                    ),
                )
            )

        if not alternatives:
            alternatives.append(
                AlternativeHypothesis(
                    cause="A second, independent fault on the same path.",
                    why_less_likely=(
                        "Only one deterministic finding was reported, so there is no "
                        "evidence of a second fault."
                    ),
                )
            )
        return alternatives

    def _fix_steps(self, findings: list[Finding]) -> list[FixStep]:
        """Turn the findings' suggested mutations into recommended CLI, in a runnable order.

        Ordering matters and is not the same as severity order: a VLAN must exist before
        ``no shutdown`` on its SVI will bring the interface up, and IP routing must be on
        before a route is of any use. Steps are therefore sequenced by dependency, not by
        how serious the finding was.

        Phrased in the imperative throughout: recommendations for a human to run after
        approving the diagnosis, never a record of anything performed.
        """
        ordered = sorted(
            (f for f in findings if f.suggested_mutation),
            key=lambda f: (
                _MUTATION_ORDER.get(f.suggested_mutation.get("type", ""), 99),
                f.rule_id,
                f.message,
            ),
        )

        steps: list[FixStep] = []
        seen: set[str] = set()

        for finding in ordered:
            mutation = finding.suggested_mutation
            commands, rationale, risk = self._mutation_to_cli(mutation, finding)
            if not commands:
                continue
            key = "|".join(commands)
            if key in seen:
                continue
            seen.add(key)
            steps.append(
                FixStep(
                    order=len(steps) + 1,
                    device=mutation.get("device") or mutation.get("host") or "unknown",
                    cli_commands=commands,
                    rationale=rationale,
                    risk=risk,
                )
            )

        return steps

    def _mutation_to_cli(
        self, mutation: dict, finding: Finding
    ) -> tuple[list[str], str, str]:
        """Map a typed LabState mutation to the IOS a human would type for it."""
        kind = mutation.get("type")

        if kind == "add_vlan":
            vlan_id = mutation.get("vlan_id")
            name = mutation.get("name") or f"VLAN{vlan_id}"
            return (
                ["configure terminal", f"vlan {vlan_id}", f"name {name}", "end"],
                (
                    f"Create VLAN {vlan_id} in the VLAN database so ports and any SVI "
                    f"referencing it can become active. Reversible with 'no vlan {vlan_id}'."
                ),
                "low",
            )

        if kind == "set_interface_admin_state":
            interface = mutation.get("interface")
            if mutation.get("admin_state") == "up":
                return (
                    ["configure terminal", f"interface {interface}", "no shutdown", "end"],
                    (
                        f"Bring {interface} out of the shutdown state so its subnet has an "
                        "active gateway and a connected route. Reversible with 'shutdown'."
                    ),
                    "low",
                )
            return ([], "", "low")

        if kind == "enable_ip_routing":
            return (
                ["configure terminal", "ip routing", "end"],
                (
                    "Enable IP routing so the switch forwards between VLANs. Without it the "
                    "routing table is irrelevant. Reversible with 'no ip routing'."
                ),
                "medium",
            )

        if kind == "add_static_route":
            prefix = mutation.get("prefix")
            mask = mutation.get("mask")
            return (
                [
                    "configure terminal",
                    f"ip route {prefix} {mask} <next-hop-or-exit-interface>",
                    "end",
                ],
                (
                    f"Add a route to {prefix} {mask}. The next hop must be confirmed by the "
                    "reviewer against the topology before this is run."
                ),
                "medium",
            )

        if kind == "set_host_gateway":
            host = mutation.get("host")
            gateway = mutation.get("gateway")
            if not gateway:
                return ([], "", "low")
            return (
                [f"# On {host}: set the default gateway to {gateway}"],
                (
                    f"Point {host} at a gateway that exists in its own subnet. This is an "
                    "end-host setting, not a switch command."
                ),
                "low",
            )

        if kind == "set_host_mask":
            host = mutation.get("host")
            mask = mutation.get("mask")
            return (
                [f"# On {host}: set the subnet mask to {mask}"],
                (
                    f"Align {host}'s mask with its gateway's so local and remote "
                    "destinations are classified the same way at both ends."
                ),
                "low",
            )

        if kind == "resolve_duplicate_ip":
            ip = mutation.get("ip")
            reassign = ", ".join(mutation.get("reassign") or [])
            return (
                [f"# Reassign a unique address to: {reassign} (currently all claim {ip})"],
                (
                    f"Only one owner may hold {ip}. The reviewer must decide which owner "
                    "keeps it before any change is made."
                ),
                "medium",
            )

        return ([], "", "low")

    def _verification_steps(self, findings: list[Finding]) -> list[VerificationStep]:
        """One verification per distinct rule, so every finding has a way to be closed out."""
        steps: list[VerificationStep] = []
        seen: set[str] = set()

        for finding in findings:
            if finding.rule_id in seen or not finding.suggested_check:
                continue
            seen.add(finding.rule_id)
            command = finding.suggested_check.split("/")[0].strip()
            steps.append(
                VerificationStep(
                    command=command,
                    expected_result=(
                        f"The condition detected by {finding.rule_id} "
                        f"({finding.rule_name}) should no longer be present."
                    ),
                )
            )

        return steps

    def _notes(self, primary: Finding, findings: list[Finding]) -> str:
        rule_ids = ", ".join(sorted({f.rule_id for f in findings}))
        return (
            f"This diagnosis is grounded in {len(findings)} deterministic finding(s) "
            f"({rule_ids}), with {primary.rule_id} treated as the primary cause because it "
            f"carries the highest severity ({primary.severity.value}). Every citation above "
            f"is a verbatim line from the supplied output. {MOCK_NOTE}"
        )

    def _category_hint(self, request: DiagnoseRequest) -> str:
        """Category to use when no finding supplies one."""
        if request.concept_tag_hint:
            return request.concept_tag_hint
        return "INTERFACE_CONFIG"

