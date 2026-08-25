"""Shared enumerations for NetSage AI.

Every value that appears in stored data or in an API response is defined here so the
dataset, the rule engine, the AI schema and the frontend all agree on one vocabulary.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """str-valued enum so instances serialise to plain JSON strings."""

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


class OSILayer(StrEnum):
    """OSI layer. Required on every case and every AI diagnosis."""

    L1 = "L1"  # Physical
    L2 = "L2"  # Data link
    L3 = "L3"  # Network
    L4 = "L4"  # Transport
    L5 = "L5"  # Session
    L6 = "L6"  # Presentation
    L7 = "L7"  # Application


class Severity(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class ConceptTag(StrEnum):
    """The eight fault families the company document mandates, plus the reviewer's
    ninth category for pure interface/configuration faults."""

    VLAN = "VLAN"
    GATEWAY = "GATEWAY"
    DHCP = "DHCP"
    DNS = "DNS"
    ROUTING = "ROUTING"
    ACL = "ACL"
    NAT = "NAT"
    WIRELESS = "WIRELESS"
    INTERFACE_CONFIG = "INTERFACE_CONFIG"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DeviceKind(StrEnum):
    ROUTER = "router"
    SWITCH = "switch"
    MULTILAYER_SWITCH = "multilayer_switch"
    WLC = "wlc"
    ACCESS_POINT = "access_point"
    SERVER = "server"
    FIREWALL = "firewall"


class AdminState(StrEnum):
    """Administrative state — what the config says."""

    UP = "up"
    SHUTDOWN = "shutdown"


class OperState(StrEnum):
    """Operational state — what the line protocol actually reports."""

    UP = "up"
    DOWN = "down"


class SwitchportMode(StrEnum):
    ACCESS = "access"
    TRUNK = "trunk"
    ROUTED = "routed"


class NatSide(StrEnum):
    INSIDE = "inside"
    OUTSIDE = "outside"


class RouteProtocol(StrEnum):
    CONNECTED = "connected"
    STATIC = "static"
    OSPF = "ospf"
    EIGRP = "eigrp"
    RIP = "rip"
    BGP = "bgp"


class LinkMode(StrEnum):
    ACCESS = "access"
    TRUNK = "trunk"
    ROUTED = "routed"


class FlowExpect(StrEnum):
    """What the network is *supposed* to do with a flow.

    Declaring intent is what makes ACL / routing / NAT checks decidable rather than
    a matter of opinion.
    """

    PERMIT = "permit"
    DENY = "deny"


class AclAction(StrEnum):
    PERMIT = "permit"
    DENY = "deny"


class SourceLabel(StrEnum):
    """Provenance of a case. The prototype never claims real hardware capture."""

    SIMULATED_LAB = "simulated-lab"
