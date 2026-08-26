"""Deterministic checks. Importing this package registers every rule."""

# Mandatory rules from the company document (R001-R006). These are imported first
# because they are the six checks the deliverable is graded on.
from backend.app.rules.checks import (  # noqa: F401
    gateway,
    interface,
    ip_addressing,
    routing,
    vlan,
)

# Optional Phase 5 rules (R007-R015). None of them is marked mandatory, so the health
# endpoint and the workbench's mandatory-rule rows are unchanged by their presence.
from backend.app.rules.checks import (  # noqa: F401
    acl,
    dhcp,
    dns,
    nat,
    subnets,
    svi,
    vlan_topology,
    wireless,
)

__all__ = [
    "ip_addressing",
    "gateway",
    "interface",
    "vlan",
    "routing",
    "vlan_topology",
    "subnets",
    "dhcp",
    "dns",
    "acl",
    "nat",
    "wireless",
    "svi",
]
