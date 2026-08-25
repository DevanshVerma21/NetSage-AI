"""The Fix Simulator.

A "fix" here is a set of typed mutations applied to a **deep copy** of a case's
:class:`~backend.app.models.lab_state.LabState`. The original case object is never
touched, and nothing in this module can reach a device: there is no SSH, no Telnet, no
Netmiko, no command execution. Verification means re-running the deterministic rule engine
against the mutated copy and diffing the findings.

Two design decisions worth stating:

**Mutations come from the deterministic findings, never from the caller.** Each rule that
can propose a remedy attaches a typed ``suggested_mutation`` to its finding. The simulator
consumes those. That is what makes "the client cannot specify an arbitrary fix" a property
of the data flow rather than a validation rule someone could forget.

**The fix is minimised.** Mutations are applied in dependency order, and before each one
the engine is re-run: a mutation whose finding has already been resolved by an earlier step
is skipped with a recorded reason. On CASE-001 that is what stops the simulator from adding
a pointless static route after bringing up the Vlan30 SVI already produced the connected
route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.app.models.enums import AdminState, OperState, RouteProtocol
from backend.app.models.lab_state import IntendedFlow, LabState, Route, Vlan
from backend.app.models.records import AppliedMutation
from backend.app.rules.engine import Finding, run_rules

SUPPORTED_MUTATIONS = (
    "add_vlan",
    "enable_ip_routing",
    "set_interface_admin_state",
    "set_host_gateway",
    "set_host_mask",
    "add_static_route",
)

_ORDER: dict[str, int] = {
    # A VLAN must exist before an SVI for it can come up, and IP routing must be on
    # before any route matters. Host-side corrections come last: they depend on the
    # network side being right, not the other way round.
    "add_vlan": 0,
    "enable_ip_routing": 1,
    "set_interface_admin_state": 2,
    "set_host_gateway": 3,
    "set_host_mask": 4,
    "add_static_route": 5,
}


class MutationError(Exception):
    """A mutation named a device, interface or host that does not exist."""


@dataclass
class SimulationOutcome:
    """The result of one simulated fix. Contains no claim about real hardware."""

    findings_before: list[Finding]
    findings_after: list[Finding]
    mutations: list[AppliedMutation] = field(default_factory=list)
    state_after: Optional[LabState] = None

    # --- the diff ----------------------------------------------------------------------

    @property
    def before_ids(self) -> list[str]:
        return sorted({finding.rule_id for finding in self.findings_before})

    @property
    def after_ids(self) -> list[str]:
        return sorted({finding.rule_id for finding in self.findings_after})

    @property
    def resolved_rule_ids(self) -> list[str]:
        return sorted(set(self.before_ids) - set(self.after_ids))

    @property
    def new_rule_ids(self) -> list[str]:
        """Rules that were not firing before and are firing now — a regression."""
        return sorted(set(self.after_ids) - set(self.before_ids))

    @property
    def remaining_rule_ids(self) -> list[str]:
        return sorted(set(self.before_ids) & set(self.after_ids))

    @property
    def verification_result(self) -> str:
        """``verified`` · ``partial`` · ``failed``.

        A fix that introduces a new finding is never ``verified``, even if it resolved
        everything it targeted — a remedy that breaks something else has not worked.
        """
        if self.new_rule_ids:
            return "partial" if self.resolved_rule_ids else "failed"
        if not self.before_ids:
            return "verified" if not self.after_ids else "failed"
        if not self.after_ids:
            return "verified"
        return "partial" if self.resolved_rule_ids else "failed"

    def summary(self) -> str:
        parts = [
            f"{len(self.findings_before)} finding(s) before, "
            f"{len(self.findings_after)} after"
        ]
        if self.resolved_rule_ids:
            parts.append(f"resolved {', '.join(self.resolved_rule_ids)}")
        if self.remaining_rule_ids:
            parts.append(f"still firing {', '.join(self.remaining_rule_ids)}")
        if self.new_rule_ids:
            parts.append(f"NEWLY INTRODUCED {', '.join(self.new_rule_ids)}")
        skipped = [m for m in self.mutations if not m.applied]
        if skipped:
            parts.append(f"{len(skipped)} mutation(s) skipped")
        return "; ".join(parts) + "."


# --- the individual mutations -------------------------------------------------------------
#
# Each returns a one-line human-readable description of what it changed. Each operates on
# the copy it is handed and nothing else.


def _require_device(state: LabState, name: str):
    device = state.device(name)
    if device is None:
        raise MutationError(f"no device named '{name}' in the lab state")
    return device


def _require_host(state: LabState, name: str):
    host = state.host(name)
    if host is None:
        raise MutationError(f"no host named '{name}' in the lab state")
    return host


def add_vlan(state: LabState, device: str, vlan_id: int, name: Optional[str] = None) -> str:
    dev = _require_device(state, device)
    if dev.has_vlan(int(vlan_id)):
        return f"VLAN {vlan_id} already present on {dev.name}"
    dev.vlans.append(Vlan(vlan_id=int(vlan_id), name=name or f"VLAN{vlan_id}", status="active"))
    dev.vlans.sort(key=lambda v: v.vlan_id)
    return f"created VLAN {vlan_id} ({name or f'VLAN{vlan_id}'}) on {dev.name}"


def enable_ip_routing(state: LabState, device: str) -> str:
    dev = _require_device(state, device)
    dev.ip_routing_enabled = True
    return f"enabled IP routing on {dev.name}"


def set_interface_admin_state(
    state: LabState, device: str, interface: str, admin_state: str = "up"
) -> str:
    dev = _require_device(state, device)
    iface = dev.interface(interface)
    if iface is None:
        raise MutationError(f"no interface '{interface}' on device '{device}'")
    iface.admin_state = AdminState(admin_state)
    return f"set {dev.name} {iface.name} admin state to {iface.admin_state.value}"


def set_host_gateway(state: LabState, host: str, gateway: str) -> str:
    target = _require_host(state, host)
    if not gateway:
        raise MutationError(f"no corrected gateway available for host '{host}'")
    previous = target.gateway
    target.gateway = gateway
    return f"set {target.name} default gateway {previous} -> {gateway}"


def set_host_mask(state: LabState, host: str, mask: str) -> str:
    target = _require_host(state, host)
    if not mask:
        raise MutationError(f"no corrected mask available for host '{host}'")
    previous = target.mask
    target.mask = mask
    return f"set {target.name} subnet mask {previous} -> {mask}"


def add_static_route(
    state: LabState,
    device: str,
    prefix: str,
    mask: str,
    next_hop: Optional[str] = None,
    out_interface: Optional[str] = None,
) -> str:
    dev = _require_device(state, device)
    if not (next_hop or out_interface):
        raise MutationError(
            f"a static route to {prefix}/{mask} on {dev.name} needs a next hop or an exit "
            "interface, and the supplied topology does not determine one. A human must "
            "supply it."
        )
    dev.routes.append(
        Route(
            prefix=prefix,
            mask=mask,
            next_hop=next_hop,
            out_interface=out_interface,
            protocol=RouteProtocol.STATIC,
        )
    )
    target = next_hop or out_interface
    return f"added static route {prefix}/{mask} via {target} on {dev.name}"


_HANDLERS = {
    "add_vlan": add_vlan,
    "enable_ip_routing": enable_ip_routing,
    "set_interface_admin_state": set_interface_admin_state,
    "set_host_gateway": set_host_gateway,
    "set_host_mask": set_host_mask,
    "add_static_route": add_static_route,
}


def settle(state: LabState) -> None:
    """Recompute the interface line-protocol states a configuration change implies.

    Only one implication is modelled, and only because the rule engine reads it: an SVI is
    operationally up when it is administratively up **and** its VLAN exists in the device's
    VLAN database. Without this, "no shutdown on Vlan30" would leave the SVI admin-up but
    line-protocol-down forever, and the verification diff would be wrong for a reason that
    has nothing to do with the fix.

    Physical interfaces are left alone: whether a cable is plugged in is not something a
    configuration change can decide.
    """
    for device in state.devices:
        for iface in device.interfaces:
            if not iface.is_svi or iface.vlan is None:
                continue
            if iface.admin_state == AdminState.SHUTDOWN:
                iface.oper_state = OperState.DOWN
            elif device.has_vlan(iface.vlan):
                iface.oper_state = OperState.UP
            else:
                iface.oper_state = OperState.DOWN


# --- orchestration ------------------------------------------------------------------------


def _describe_target(mutation: dict) -> str:
    for key in ("device", "host"):
        if mutation.get(key):
            base = str(mutation[key])
            if mutation.get("interface"):
                return f"{base} / {mutation['interface']}"
            return base
    return ""


def apply_mutations(
    state: LabState,
    mutations: list[dict],
    intended_flows: Optional[list[IntendedFlow]] = None,
) -> SimulationOutcome:
    """Apply mutations to a **copy** of ``state`` and verify the result deterministically.

    The caller's ``state`` is guaranteed unchanged: the first thing this does is take a
    deep copy, and every mutation operates on that copy.
    """
    flows = list(intended_flows or [])
    findings_before = run_rules(state, flows)

    working = state.model_copy(deep=True)
    applied: list[AppliedMutation] = []

    ordered = sorted(
        mutations, key=lambda m: (_ORDER.get(str(m.get("type", "")), 99), str(m.get("type")))
    )

    for mutation in ordered:
        kind = str(mutation.get("type", ""))
        rule_id = mutation.get("_rule_id")
        target = _describe_target(mutation)

        handler = _HANDLERS.get(kind)
        if handler is None:
            applied.append(
                AppliedMutation(
                    type=kind or "(missing type)",
                    rule_id=rule_id,
                    target=target,
                    applied=False,
                    skipped_reason=(
                        f"'{kind}' is not a mutation this simulator supports. Supported: "
                        f"{', '.join(SUPPORTED_MUTATIONS)}. A human must apply this change."
                    ),
                )
            )
            continue

        # Minimal change: if the finding that proposed this mutation no longer fires,
        # an earlier step already dealt with it.
        if rule_id is not None:
            current = {finding.rule_id for finding in run_rules(working, flows)}
            if rule_id not in current:
                applied.append(
                    AppliedMutation(
                        type=kind,
                        rule_id=rule_id,
                        target=target,
                        applied=False,
                        skipped_reason=(
                            f"not needed — {rule_id} was already resolved by an earlier "
                            "step in this fix."
                        ),
                    )
                )
                continue

        kwargs = {
            key: value
            for key, value in mutation.items()
            if key not in ("type", "_rule_id")
        }
        try:
            detail = handler(working, **kwargs)
        except (MutationError, TypeError, ValueError) as exc:
            applied.append(
                AppliedMutation(
                    type=kind,
                    rule_id=rule_id,
                    target=target,
                    applied=False,
                    skipped_reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        settle(working)
        applied.append(
            AppliedMutation(
                type=kind, rule_id=rule_id, target=target, detail=detail, applied=True
            )
        )

    findings_after = run_rules(working, flows)
    return SimulationOutcome(
        findings_before=findings_before,
        findings_after=findings_after,
        mutations=applied,
        state_after=working,
    )
