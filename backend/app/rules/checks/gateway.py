"""R003 gateway mismatch — a mandatory check from the company document.

Two distinct faults share this rule ID because both present identically to the user
("my PC has an IP but cannot reach anything off-subnet"), but they need different fixes:

* the configured gateway is not inside the host's own subnet, so the host can never ARP
  for it; or
* the gateway address is syntactically fine and in-subnet, but no device in the topology
  actually owns it, so nothing answers.
"""

from __future__ import annotations

from backend.app.models.enums import ConceptTag, OSILayer, Severity
from backend.app.netutils import is_valid_netmask, network_of, same_subnet
from backend.app.rules.engine import Finding, RuleContext, RuleEvidence, make_finding, rule


@rule(
    id="R003",
    name="Gateway mismatch",
    category=ConceptTag.GATEWAY,
    severity=Severity.HIGH,
    osi_layer=OSILayer.L3,
    description=(
        "A host's default gateway is outside its own subnet, or is not owned by any "
        "Layer 3 interface in the topology."
    ),
    mandatory=True,
    suggested_check="ipconfig /all on the host  /  show ip interface brief on the gateway",
)
def check_gateway_mismatch(ctx: RuleContext) -> list[Finding]:
    meta = check_gateway_mismatch.rule_meta  # type: ignore[attr-defined]
    findings: list[Finding] = []

    for host in ctx.state.hosts:
        if not host.gateway:
            # A host with no gateway at all cannot route off-subnet.
            if host.ip:
                findings.append(
                    make_finding(
                        meta,
                        message=(
                            f"Host {host.name} has an IP address but no default gateway "
                            "configured, so it cannot reach any other subnet."
                        ),
                        evidence=[
                            RuleEvidence(
                                source=host.name,
                                detail=f"address {host.ip} mask {host.mask} gateway <none>",
                            )
                        ],
                        affected=[host.name],
                    )
                )
            continue

        # (a) Gateway outside the host's own subnet.
        if host.ip and is_valid_netmask(host.mask):
            in_subnet = same_subnet(host.ip, host.gateway, host.mask)
            if in_subnet is False:
                net = network_of(host.ip, host.mask)
                findings.append(
                    make_finding(
                        meta,
                        message=(
                            f"Host {host.name} ({host.ip}/{host.mask}) has default gateway "
                            f"{host.gateway}, which is outside its own subnet "
                            f"{net}. The host can never ARP for that gateway."
                        ),
                        evidence=[
                            RuleEvidence(
                                source=host.name,
                                detail=(
                                    f"address {host.ip} mask {host.mask} "
                                    f"gateway {host.gateway} (subnet {net})"
                                ),
                            )
                        ],
                        affected=[host.name],
                        suggested_mutation={
                            "type": "set_host_gateway",
                            "host": host.name,
                            "gateway": _expected_gateway(ctx, host) or "",
                        },
                    )
                )
                continue  # Do not also report "unowned" for an out-of-subnet gateway.

        # (b) Gateway in-subnet but owned by nothing.
        if ctx.state.owner_of_ip(host.gateway) is None:
            findings.append(
                make_finding(
                    meta,
                    message=(
                        f"Host {host.name} points at gateway {host.gateway}, but no Layer 3 "
                        "interface in the topology owns that address, so nothing will "
                        "answer for it."
                    ),
                    evidence=[
                        RuleEvidence(
                            source=host.name,
                            detail=f"gateway {host.gateway}",
                        ),
                        RuleEvidence(
                            source="topology",
                            detail=(
                                "L3 interface addresses present: "
                                + (
                                    ", ".join(
                                        f"{d.name} {i.name}={i.ip}"
                                        for d, i in ctx.state.l3_interfaces()
                                    )
                                    or "none"
                                )
                            ),
                        ),
                    ],
                    affected=[host.name],
                )
            )

    return findings


def _expected_gateway(ctx, host) -> str | None:
    """Best in-subnet L3 address for this host, used to propose a corrected gateway.

    Returns None when nothing suitable exists — the Fix Simulator then has no mutation
    to offer, and the reviewer supplies the value.
    """
    if not (host.ip and is_valid_netmask(host.mask)):
        return None
    for _device, iface in ctx.state.l3_interfaces():
        if same_subnet(host.ip, iface.ip, host.mask) is True:
            return iface.ip
    return None
