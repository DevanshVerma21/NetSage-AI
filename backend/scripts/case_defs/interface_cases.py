"""Interface configuration cases (CASE-037 .. CASE-040)."""

from __future__ import annotations

from backend.scripts.case_builders import (
    build_case,
    capture,
    dev,
    flow,
    host,
    ifc,
    link,
    ping,
    route,
    state,
    vlan,
)

_MASK = "255.255.255.0"
_P30 = "255.255.255.252"


def case_037() -> dict:
    wan = dev(
        "R-WAN",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "172.16.10.1", _MASK, description="SITE LAN"),
            ifc("GigabitEthernet0/1", "172.16.0.1", _P30, admin="shutdown", oper="down",
                description="WAN TO DC"),
        ],
        routes=[route("172.16.20.0", _MASK, "172.16.0.2")],
    )
    dc = dev(
        "R-DC",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "172.16.20.1", _MASK, description="DC LAN"),
            ifc("GigabitEthernet0/1", "172.16.0.2", _P30, description="WAN TO SITE"),
        ],
        routes=[route("172.16.10.0", _MASK, "172.16.0.1")],
    )
    hosts = [
        host("PC-SITE", "172.16.10.20", _MASK, "172.16.10.1", on="R-WAN",
             port="GigabitEthernet0/0"),
        host("SRV-DC", "172.16.20.10", _MASK, "172.16.20.1", on="R-DC",
             port="GigabitEthernet0/0"),
    ]
    links = [
        link("PC-SITE", "FastEthernet0", "R-WAN", "GigabitEthernet0/0"),
        link("SRV-DC", "FastEthernet0", "R-DC", "GigabitEthernet0/0"),
        link("R-WAN", "GigabitEthernet0/1", "R-DC", "GigabitEthernet0/1", mode="routed"),
    ]
    lab = state([wan, dc], hosts, links)
    return build_case(
        "CASE-037",
        title="Site lost the data centre after the WAN interface was left shut down",
        severity="Critical",
        symptom=(
            "Nothing at the site can reach the data centre since last night's maintenance "
            "window. The static route for 172.16.20.0/24 is still in the configuration, but "
            "the WAN interface reports administratively down and the neighbour is not visible."
        ),
        topology_note=(
            "Two-router WAN lab (simulated). R-WAN Gi0/0 = 172.16.10.1/24 serves the site LAN "
            "and Gi0/1 = 172.16.0.1/30 is the WAN link to R-DC 172.16.0.2. Each router carries "
            "a static route for the other site's LAN. The WAN interface must be up for those "
            "routes to be usable."
        ),
        concept="INTERFACE_CONFIG",
        osi="L1",
        fault=(
            "R-WAN Gi0/1 is administratively down (shutdown was left in place after "
            "maintenance), so the only path toward 172.16.20.0/24 is unusable."
        ),
        keywords=["shutdown interface", "gi0/1", "administratively down", "wan link"],
        rules=["R004"],
        fixes=[
            "On R-WAN: interface GigabitEthernet0/1",
            "Bring the interface up: no shutdown",
            "Confirm Gi0/1 is up/up in show ip interface brief",
            "Re-test: PC-SITE ping 172.16.0.2, then ping 172.16.20.10",
        ],
        lab=lab,
        flows=[flow("PC-SITE", "SRV-DC", "tcp", 443, note="Site users to the data centre app")],
        extra=[
            ping("PC-SITE", "172.16.20.10", ok=False, note="Destination host unreachable."),
            ping("PC-SITE", "172.16.10.1", ok=True),
        ],
    )


def _switch_lab(name: str, ifaces, vlans_, hosts_spec) -> tuple:
    sw = dev(name, ifaces=ifaces, vlans=vlans_)
    hosts = [h for h, _ in hosts_spec]
    links = [
        link(h.name, "FastEthernet0", name, port, vlan_id=h.vlan) for h, port in hosts_spec
    ]
    return state([sw], hosts, links)


def case_038() -> dict:
    lab = _switch_lab(
        "SW-FLOOR",
        [
            ifc("GigabitEthernet0/1", vlan=85, mode="access"),
            ifc("GigabitEthernet0/2", vlan=86, mode="access"),
            ifc("Vlan85", "172.16.85.1", _MASK, vlan=85, oper="down"),
            ifc("Vlan86", "172.16.86.1", _MASK, vlan=86),
        ],
        [vlan(1, "default"), vlan(85, "FLOOR-USERS"), vlan(86, "FLOOR-SERVERS")],
        [
            (host("PC-FLOOR", "172.16.85.20", _MASK, "172.16.85.1", vlan_id=85, on="SW-FLOOR",
                  port="GigabitEthernet0/1"), "GigabitEthernet0/1"),
            (host("SRV-FLOOR", "172.16.86.10", _MASK, "172.16.86.1", vlan_id=86, on="SW-FLOOR",
                  port="GigabitEthernet0/2"), "GigabitEthernet0/2"),
        ],
    )
    return build_case(
        "CASE-038",
        title="Floor users lose their gateway while the SVI is configured up",
        severity="High",
        symptom=(
            "PC-FLOOR cannot reach its gateway 172.16.85.1 or anything beyond it. The SVI is "
            "not shut down in the configuration, but show ip interface brief reports its line "
            "protocol as down."
        ),
        topology_note=(
            "Access switch lab (simulated). SW-FLOOR is a multilayer switch routing between "
            "VLAN 85 FLOOR-USERS = 172.16.85.0/24 and VLAN 86 FLOOR-SERVERS = 172.16.86.0/24. "
            "Both VLANs exist in the database with member access ports, and each SVI is the "
            "gateway for its VLAN."
        ),
        concept="INTERFACE_CONFIG",
        osi="L1",
        fault=(
            "The Vlan85 SVI is administratively up but its line protocol is down, so VLAN 85 "
            "has no working gateway even though the configuration looks correct."
        ),
        keywords=["line protocol down", "vlan85 svi", "svi down", "172.16.85.1"],
        rules=["R004", "R015"],
        fixes=[
            "On SW-FLOOR, confirm VLAN 85 is active in show vlan brief",
            "Confirm at least one access port in VLAN 85 is up — an SVI stays down while every "
            "member port is down",
            "Bounce the SVI: interface Vlan85, shutdown, then no shutdown",
            "Confirm Vlan85 is up/up in show ip interface brief",
            "Re-test: PC-FLOOR ping 172.16.85.1",
        ],
        lab=lab,
        flows=[flow("PC-FLOOR", "SRV-FLOOR", "tcp", 443, note="Floor users to the floor server")],
        extra=[
            ping("PC-FLOOR", "172.16.85.1", ok=False, note="Request timed out."),
            ping("SRV-FLOOR", "172.16.86.1", ok=True),
        ],
    )


def case_039() -> dict:
    lab = _switch_lab(
        "SW-OPS",
        [
            ifc("GigabitEthernet0/1", vlan=88, mode="access"),
            ifc("GigabitEthernet0/2", vlan=89, mode="access"),
            ifc("Vlan87", "172.16.88.1", _MASK, vlan=87),
            ifc("Vlan89", "172.16.89.1", _MASK, vlan=89),
        ],
        [vlan(1, "default"), vlan(88, "OPS-USERS"), vlan(89, "OPS-SERVERS")],
        [
            (host("PC-OPS", "172.16.88.20", _MASK, "172.16.88.1", vlan_id=88, on="SW-OPS",
                  port="GigabitEthernet0/1"), "GigabitEthernet0/1"),
            (host("SRV-OPS", "172.16.89.10", _MASK, "172.16.89.1", vlan_id=89, on="SW-OPS",
                  port="GigabitEthernet0/2"), "GigabitEthernet0/2"),
        ],
    )
    return build_case(
        "CASE-039",
        title="Gateway address was configured on an interface for a VLAN that does not exist",
        severity="High",
        symptom=(
            "PC-OPS cannot reach its gateway 172.16.88.1 even though that address is present on "
            "the switch and shows as up. The operations VLAN has no gateway of its own, and the "
            "switch has an interface for a VLAN that appears nowhere in show vlan brief."
        ),
        topology_note=(
            "Operations switch lab (simulated). SW-OPS is a multilayer switch. VLAN 88 "
            "OPS-USERS = 172.16.88.0/24 with documented gateway 172.16.88.1 and VLAN 89 "
            "OPS-SERVERS = 172.16.89.0/24 with gateway 172.16.89.1. Only VLANs 1, 88 and 89 "
            "exist in the VLAN database."
        ),
        concept="INTERFACE_CONFIG",
        osi="L3",
        fault=(
            "The users' gateway address 172.16.88.1 was configured on an SVI for VLAN 87, a "
            "VLAN that does not exist on the switch, so VLAN 88 has no SVI and the configured "
            "interface serves no VLAN."
        ),
        keywords=["wrong interface", "vlan87 svi", "vlan 88 has no svi", "missing vlan"],
        rules=["R005", "R015"],
        fixes=[
            "On SW-OPS: no interface Vlan87",
            "Create the correct interface: interface Vlan88",
            "Assign the documented gateway: ip address 172.16.88.1 255.255.255.0",
            "Bring it up: no shutdown",
            "Confirm Vlan88 is up/up and 172.16.88.0/24 is a connected route",
            "Re-test: PC-OPS ping 172.16.88.1",
        ],
        lab=lab,
        flows=[flow("PC-OPS", "SRV-OPS", "tcp", 443, note="Operations users to the ops server")],
        extra=[
            ping("PC-OPS", "172.16.88.1", ok=False, note="Request timed out."),
        ],
    )


def case_040() -> dict:
    lab = _switch_lab(
        "SW-ADMIN",
        [
            ifc("GigabitEthernet0/1", vlan=91, mode="access"),
            ifc("GigabitEthernet0/2", vlan=92, mode="access"),
            ifc("Vlan91", "172.16.91.1", "255.255.0.255", vlan=91),
            ifc("Vlan92", "172.16.92.1", _MASK, vlan=92),
        ],
        [vlan(1, "default"), vlan(91, "ADMIN-USERS"), vlan(92, "ADMIN-SERVERS")],
        [
            (host("PC-ADMIN", "172.16.91.20", _MASK, "172.16.91.1", vlan_id=91, on="SW-ADMIN",
                  port="GigabitEthernet0/1"), "GigabitEthernet0/1"),
            (host("SRV-ADMIN", "172.16.92.10", _MASK, "172.16.92.1", vlan_id=92, on="SW-ADMIN",
                  port="GigabitEthernet0/2"), "GigabitEthernet0/2"),
        ],
    )
    return build_case(
        "CASE-040",
        title="Admin VLAN gateway was configured with an unusable subnet mask",
        severity="High",
        symptom=(
            "PC-ADMIN cannot use its gateway. The Vlan91 interface is up and carries the "
            "expected address, but the mask printed by the switch is 255.255.0.255 and the "
            "connected network it derives from it is nonsense."
        ),
        topology_note=(
            "Administration switch lab (simulated). SW-ADMIN is a multilayer switch. VLAN 91 "
            "ADMIN-USERS = 172.16.91.0/24 with gateway 172.16.91.1 and VLAN 92 ADMIN-SERVERS = "
            "172.16.92.0/24 with gateway 172.16.92.1. Every segment in this lab is a /24."
        ),
        concept="INTERFACE_CONFIG",
        osi="L3",
        fault=(
            "The Vlan91 SVI is configured with the non-contiguous mask 255.255.0.255 instead of "
            "255.255.255.0, so the gateway interface has no valid network and cannot serve the "
            "admin VLAN."
        ),
        keywords=["invalid subnet mask", "255.255.0.255", "vlan91", "incorrect addressing"],
        rules=["R002"],
        fixes=[
            "On SW-ADMIN: interface Vlan91",
            "Re-apply the correct mask: ip address 172.16.91.1 255.255.255.0",
            "Confirm the mask in show ip interface brief and show running-config interface "
            "Vlan91",
            "Re-test: PC-ADMIN ping 172.16.91.1, then reach 172.16.92.10",
        ],
        lab=lab,
        flows=[flow("PC-ADMIN", "SRV-ADMIN", "tcp", 443, note="Admin users to the admin server")],
        extra=[
            capture("SW-ADMIN", "show running-config interface Vlan91",
                    "interface Vlan91\n ip address 172.16.91.1 255.255.0.255"),
            ping("PC-ADMIN", "172.16.91.1", ok=False, note="Request timed out."),
        ],
    )


CASES = [case_037, case_038, case_039, case_040]
