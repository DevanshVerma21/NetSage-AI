"""Structured model of a lab network.

This is the source of truth the deterministic rule engine reasons over, and the object
the Fix Simulator mutates. The Cisco ``show`` text stored on a case is a human-readable
*rendering* of this state, not the other way round — which is what keeps the rule checks
deterministic and testable.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.app.models.enums import (
    AclAction,
    AdminState,
    DeviceKind,
    FlowExpect,
    LinkMode,
    NatSide,
    OperState,
    RouteProtocol,
    SwitchportMode,
)


class Interface(BaseModel):
    """A device interface: physical, sub-interface, or SVI."""

    name: str = Field(description="Cisco interface name, e.g. GigabitEthernet0/1, Vlan30")
    ip: Optional[str] = None
    mask: Optional[str] = None
    admin_state: AdminState = AdminState.UP
    oper_state: OperState = OperState.UP
    is_svi: bool = False
    vlan: Optional[int] = Field(
        default=None,
        description="For an SVI, the VLAN it serves. For an access port, its access VLAN.",
    )
    switchport_mode: Optional[SwitchportMode] = None
    allowed_vlans: list[int] = Field(default_factory=list)
    native_vlan: Optional[int] = None
    nat_side: Optional[NatSide] = None
    helper_addresses: list[str] = Field(
        default_factory=list, description="ip helper-address entries (DHCP relay)"
    )
    description: Optional[str] = None

    @property
    def is_shutdown(self) -> bool:
        return self.admin_state == AdminState.SHUTDOWN

    @property
    def is_down(self) -> bool:
        """Down for any reason — administratively or operationally."""
        return self.admin_state == AdminState.SHUTDOWN or self.oper_state == OperState.DOWN


class Vlan(BaseModel):
    """An entry in a switch's VLAN database."""

    vlan_id: int
    name: str
    status: str = "active"


class Route(BaseModel):
    """One entry in a routing table."""

    prefix: str = Field(description="Network address, e.g. 192.168.30.0")
    mask: str = Field(description="Dotted-quad netmask, e.g. 255.255.255.0")
    next_hop: Optional[str] = None
    out_interface: Optional[str] = None
    protocol: RouteProtocol = RouteProtocol.STATIC

    @property
    def is_default(self) -> bool:
        return self.prefix == "0.0.0.0" and self.mask == "0.0.0.0"


class AclEntry(BaseModel):
    seq: int
    action: AclAction
    protocol: str = "ip"
    src: str = "any"
    src_wildcard: Optional[str] = None
    dst: str = "any"
    dst_wildcard: Optional[str] = None
    port_op: Optional[str] = Field(default=None, description="eq | neq | gt | lt | range")
    port: Optional[int] = None


class Acl(BaseModel):
    name: str = Field(description="ACL number or name, e.g. '101' or 'GUEST_ISOLATION'")
    entries: list[AclEntry] = Field(default_factory=list)


class AclBinding(BaseModel):
    """Where an ACL is actually applied. A correct ACL bound to the wrong interface or
    direction is a distinct fault from a wrong ACL."""

    acl_name: str
    interface: str
    direction: str = Field(description="in | out")


class DhcpPool(BaseModel):
    name: str
    network: Optional[str] = None
    mask: Optional[str] = None
    default_router: Optional[str] = None
    dns_servers: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


class NatRule(BaseModel):
    kind: str = Field(description="static | dynamic | overload")
    acl_name: Optional[str] = None
    pool_name: Optional[str] = None
    inside_local: Optional[str] = None
    inside_global: Optional[str] = None
    out_interface: Optional[str] = None


class Ssid(BaseModel):
    name: str
    vlan: Optional[int] = None
    is_guest: bool = False
    isolation_acl: Optional[str] = None
    security: Optional[str] = Field(default=None, description="open | wpa2-psk | wpa2-ent")


class Device(BaseModel):
    name: str
    kind: DeviceKind
    ip_routing_enabled: bool = True
    interfaces: list[Interface] = Field(default_factory=list)
    vlans: list[Vlan] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    acls: list[Acl] = Field(default_factory=list)
    acl_bindings: list[AclBinding] = Field(default_factory=list)
    dhcp_pools: list[DhcpPool] = Field(default_factory=list)
    nat_rules: list[NatRule] = Field(default_factory=list)
    ssids: list[Ssid] = Field(default_factory=list)

    def interface(self, name: str) -> Optional[Interface]:
        for iface in self.interfaces:
            if iface.name.lower() == name.lower():
                return iface
        return None

    def has_vlan(self, vlan_id: int) -> bool:
        return any(v.vlan_id == vlan_id for v in self.vlans)

    def acl(self, name: str) -> Optional[Acl]:
        for acl in self.acls:
            if acl.name == name:
                return acl
        return None


class Host(BaseModel):
    """An end station — PC, server, or wireless client."""

    name: str
    ip: Optional[str] = None
    mask: Optional[str] = None
    gateway: Optional[str] = None
    dns_servers: list[str] = Field(default_factory=list)
    vlan: Optional[int] = None
    connected_device: Optional[str] = None
    connected_interface: Optional[str] = None
    dhcp_enabled: bool = False
    ssid: Optional[str] = Field(default=None, description="Set for wireless clients")


class Link(BaseModel):
    a_device: str
    a_interface: str
    b_device: str
    b_interface: str
    mode: LinkMode = LinkMode.ACCESS
    access_vlan: Optional[int] = None
    allowed_vlans: list[int] = Field(default_factory=list)
    native_vlan: Optional[int] = None


class IntendedFlow(BaseModel):
    """What the network is *supposed* to do.

    Without a declared intent, "is this ACL wrong?" is not a decidable question. With it,
    rules R006 / R012 / R013 become deterministic pass-fail checks.
    """

    src: str = Field(description="Host name, e.g. PC-HR")
    dst: str = Field(description="Host name, e.g. SRV-FILES")
    proto: str = "ip"
    port: Optional[int] = None
    expect: FlowExpect = FlowExpect.PERMIT
    note: Optional[str] = None


class LabState(BaseModel):
    """A complete, self-contained snapshot of one lab topology."""

    devices: list[Device] = Field(default_factory=list)
    hosts: list[Host] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)

    def device(self, name: str) -> Optional[Device]:
        for dev in self.devices:
            if dev.name.lower() == name.lower():
                return dev
        return None

    def host(self, name: str) -> Optional[Host]:
        for host in self.hosts:
            if host.name.lower() == name.lower():
                return host
        return None

    def l3_interfaces(self) -> list[tuple[Device, Interface]]:
        """Every interface that owns an IP address, paired with its device."""
        return [
            (dev, iface)
            for dev in self.devices
            for iface in dev.interfaces
            if iface.ip
        ]

    def owner_of_ip(self, ip: str) -> Optional[tuple[Device, Interface]]:
        """Which device interface, if any, owns this address."""
        for dev, iface in self.l3_interfaces():
            if iface.ip == ip:
                return dev, iface
        return None

    def links_for(self, device_name: str) -> list[Link]:
        lowered = device_name.lower()
        return [
            link
            for link in self.links
            if link.a_device.lower() == lowered or link.b_device.lower() == lowered
        ]
