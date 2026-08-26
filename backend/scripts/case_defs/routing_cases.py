"""Routing cases (CASE-020 .. CASE-024)."""

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


def _wan_pair(br_lan: str, hq_lan: str, br_routes, hq_routes) -> tuple:
    br = dev(
        "R-BR",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", f"{br_lan}.1", _MASK, description="BRANCH LAN"),
            ifc("GigabitEthernet0/1", "10.0.0.1", _P30, description="WAN TO HQ"),
        ],
        routes=br_routes,
    )
    hq = dev(
        "R-HQ",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", f"{hq_lan}.1", _MASK, description="HQ LAN"),
            ifc("GigabitEthernet0/1", "10.0.0.2", _P30, description="WAN TO BRANCH"),
        ],
        routes=hq_routes,
    )
    hosts = [
        host("PC-BR", f"{br_lan}.20", _MASK, f"{br_lan}.1", on="R-BR",
             port="GigabitEthernet0/0"),
        host("SRV-HQ", f"{hq_lan}.10", _MASK, f"{hq_lan}.1", on="R-HQ",
             port="GigabitEthernet0/0"),
    ]
    links = [
        link("PC-BR", "FastEthernet0", "R-BR", "GigabitEthernet0/0"),
        link("SRV-HQ", "FastEthernet0", "R-HQ", "GigabitEthernet0/0"),
        link("R-BR", "GigabitEthernet0/1", "R-HQ", "GigabitEthernet0/1", mode="routed"),
    ]
    return state([br, hq], hosts, links)


def case_020() -> dict:
    lab = _wan_pair(
        "192.168.190", "192.168.191",
        br_routes=[],
        hq_routes=[route("192.168.190.0", _MASK, "10.0.0.1")],
    )
    return build_case(
        "CASE-020",
        title="Branch cannot reach the HQ server although the WAN link is up",
        severity="High",
        symptom=(
            "PC-BR pings its gateway and the WAN address 10.0.0.2 on R-HQ, but every attempt "
            "to reach 192.168.191.10 fails. HQ can reach the branch LAN in the other "
            "direction."
        ),
        topology_note=(
            "Two-router WAN lab (simulated). R-BR Gi0/0 = 192.168.190.1/24 serves the branch "
            "LAN; R-HQ Gi0/0 = 192.168.191.1/24 serves the HQ LAN. The routers are joined by "
            "10.0.0.0/30 (R-BR 10.0.0.1, R-HQ 10.0.0.2). Both routers run static routing only "
            "and each must carry a route for the other site's LAN."
        ),
        concept="ROUTING",
        osi="L3",
        fault=(
            "R-BR has no route for 192.168.191.0/24 at all — its routing table contains only "
            "connected networks — so HQ-bound traffic is dropped at the branch router."
        ),
        keywords=["missing route", "192.168.191.0/24", "R-BR", "static routing"],
        rules=["R006"],
        fixes=[
            "On R-BR: ip route 192.168.191.0 255.255.255.0 10.0.0.2",
            "Confirm the route appears in show ip route on R-BR",
            "Re-test: PC-BR ping 192.168.191.10",
        ],
        lab=lab,
        flows=[flow("PC-BR", "SRV-HQ", "tcp", 443, note="Branch staff to the HQ application")],
        extra=[
            ping("PC-BR", "10.0.0.2", ok=True),
            ping("PC-BR", "192.168.191.10", ok=False, note="Destination host unreachable."),
        ],
    )


def case_021() -> dict:
    lab = _wan_pair(
        "192.168.200", "192.168.201",
        br_routes=[route("192.168.20.0", _MASK, "10.0.0.2")],
        hq_routes=[route("192.168.200.0", _MASK, "10.0.0.1")],
    )
    return build_case(
        "CASE-021",
        title="Static route was entered for the wrong destination network",
        severity="High",
        symptom=(
            "The change record says a route to the HQ LAN was added on R-BR last week, and "
            "show ip route does list a static entry, yet PC-BR still cannot reach "
            "192.168.201.10. The next hop 10.0.0.2 responds to ping."
        ),
        topology_note=(
            "Two-router WAN lab (simulated). R-BR Gi0/0 = 192.168.200.1/24 serves the branch "
            "LAN; R-HQ Gi0/0 = 192.168.201.1/24 serves the HQ LAN, joined by 10.0.0.0/30. The "
            "route R-BR needs is 192.168.201.0/24 via 10.0.0.2."
        ),
        concept="ROUTING",
        osi="L3",
        fault=(
            "R-BR's static route was typed as 192.168.20.0/24 via 10.0.0.2 instead of "
            "192.168.201.0/24, so the destination the branch actually needs is still "
            "uncovered while the table looks populated."
        ),
        keywords=["wrong network in static route", "192.168.20.0", "192.168.201.0/24", "R-BR"],
        rules=["R006"],
        fixes=[
            "On R-BR: no ip route 192.168.20.0 255.255.255.0 10.0.0.2",
            "Add the correct route: ip route 192.168.201.0 255.255.255.0 10.0.0.2",
            "Confirm show ip route lists 192.168.201.0/24 via 10.0.0.2",
            "Re-test: PC-BR ping 192.168.201.10",
        ],
        lab=lab,
        flows=[flow("PC-BR", "SRV-HQ", "tcp", 443, note="Branch staff to the HQ application")],
        extra=[
            ping("PC-BR", "10.0.0.2", ok=True),
            ping("PC-BR", "192.168.201.10", ok=False, note="Destination host unreachable."),
        ],
    )


def case_022() -> dict:
    core = dev(
        "SW-L3",
        routing=False,
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=210, mode="access"),
            ifc("GigabitEthernet0/2", vlan=211, mode="access"),
            ifc("Vlan210", "192.168.210.1", _MASK, vlan=210),
            ifc("Vlan211", "192.168.211.1", _MASK, vlan=211),
        ],
        vlans=[vlan(1, "default"), vlan(210, "USERS"), vlan(211, "SERVERS")],
    )
    hosts = [
        host("PC-USER", "192.168.210.20", _MASK, "192.168.210.1", vlan_id=210, on="SW-L3",
             port="GigabitEthernet0/1"),
        host("SRV-INTRA", "192.168.211.10", _MASK, "192.168.211.1", vlan_id=211, on="SW-L3",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-USER", "FastEthernet0", "SW-L3", "GigabitEthernet0/1", vlan_id=210),
        link("SRV-INTRA", "FastEthernet0", "SW-L3", "GigabitEthernet0/2", vlan_id=211),
    ]
    lab = state([core], hosts, links)
    return build_case(
        "CASE-022",
        title="Inter-VLAN traffic stops after a switch reload although both SVIs are up",
        severity="Critical",
        symptom=(
            "Every host can reach its own gateway SVI but no VLAN can reach another. Both SVIs "
            "are up/up and correctly addressed, and show ip route prints only connected "
            "entries with no gateway of last resort."
        ),
        topology_note=(
            "Multilayer switch lab (simulated). SW-L3 is the only Layer 3 device: VLAN 210 "
            "USERS = 192.168.210.0/24 and VLAN 211 SERVERS = 192.168.211.0/24, each with an up "
            "SVI acting as the gateway. Inter-VLAN routing on this switch requires ip routing."
        ),
        concept="ROUTING",
        osi="L3",
        fault=(
            "ip routing is not enabled on SW-L3 after the reload, so the switch never forwards "
            "between its own SVIs even though both interfaces are up and addressed."
        ),
        keywords=["ip routing disabled", "inter-vlan routing", "SW-L3", "svi up"],
        rules=["R006"],
        fixes=[
            "On SW-L3, enter global configuration and run: ip routing",
            "Confirm show ip route no longer reports that routing is disabled",
            "Save the configuration so the setting survives the next reload",
            "Re-test: PC-USER ping 192.168.211.10",
        ],
        lab=lab,
        flows=[flow("PC-USER", "SRV-INTRA", "tcp", 443, note="Users to the intranet server")],
        extra=[
            ping("PC-USER", "192.168.210.1", ok=True),
            ping("PC-USER", "192.168.211.10", ok=False, note="Request timed out."),
        ],
    )


def case_023() -> dict:
    edge = dev(
        "R-EDGE",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.220.1", _MASK, description="OFFICE LAN"),
            ifc("GigabitEthernet0/1", "203.0.113.2", _P30, description="TO ISP"),
        ],
        routes=[],
    )
    isp = dev(
        "R-ISP",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "203.0.113.1", _P30, description="TO CUSTOMER"),
            ifc("GigabitEthernet0/1", "198.51.100.1", _MASK, description="HOSTING LAN"),
        ],
        routes=[route("192.168.220.0", _MASK, "203.0.113.2")],
    )
    hosts = [
        host("PC-OFFICE", "192.168.220.20", _MASK, "192.168.220.1", on="R-EDGE",
             port="GigabitEthernet0/0"),
        host("SRV-PORTAL", "198.51.100.10", _MASK, "198.51.100.1", on="R-ISP",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-OFFICE", "FastEthernet0", "R-EDGE", "GigabitEthernet0/0"),
        link("SRV-PORTAL", "FastEthernet0", "R-ISP", "GigabitEthernet0/1"),
        link("R-EDGE", "GigabitEthernet0/1", "R-ISP", "GigabitEthernet0/0", mode="routed"),
    ]
    lab = state([edge, isp], hosts, links)
    return build_case(
        "CASE-023",
        title="Office loses all external access after the default route is removed",
        severity="Critical",
        symptom=(
            "PC-OFFICE reaches everything inside the office and can ping the ISP's link "
            "address 203.0.113.1, but the hosted portal 198.51.100.10 is unreachable. "
            "show ip route on R-EDGE has no gateway of last resort."
        ),
        topology_note=(
            "Internet edge lab (simulated). R-EDGE Gi0/0 = 192.168.220.1/24 serves the office "
            "LAN and Gi0/1 = 203.0.113.2/30 connects to R-ISP 203.0.113.1. Externally hosted "
            "services live on 198.51.100.0/24 behind the ISP. R-EDGE reaches everything "
            "outside the office through a default route to 203.0.113.1."
        ),
        concept="ROUTING",
        osi="L3",
        fault=(
            "R-EDGE has no default route: the entry ip route 0.0.0.0 0.0.0.0 203.0.113.1 is "
            "missing, so any destination outside the two connected networks is dropped."
        ),
        keywords=["missing default route", "gateway of last resort", "203.0.113.1", "R-EDGE"],
        rules=["R006"],
        fixes=[
            "On R-EDGE: ip route 0.0.0.0 0.0.0.0 203.0.113.1",
            "Confirm show ip route reports the gateway of last resort as 203.0.113.1",
            "Re-test: PC-OFFICE ping 198.51.100.10",
        ],
        lab=lab,
        flows=[flow("PC-OFFICE", "SRV-PORTAL", "tcp", 443, note="Office access to the hosted portal")],
        extra=[
            ping("PC-OFFICE", "203.0.113.1", ok=True),
            ping("PC-OFFICE", "198.51.100.10", ok=False, note="Destination host unreachable."),
        ],
    )


def case_024() -> dict:
    dc = dev(
        "R-DC",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/1", "192.168.0.1", "255.255.0.0", description="CAMPUS LAN"),
            ifc("GigabitEthernet0/2", "192.168.30.1", _MASK, description="STORAGE LAN"),
        ],
    )
    hosts = [
        host("PC-CAMPUS", "192.168.5.20", "255.255.0.0", "192.168.0.1", on="R-DC",
             port="GigabitEthernet0/1"),
        host("SRV-STORE", "192.168.30.10", _MASK, "192.168.30.1", on="R-DC",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-CAMPUS", "FastEthernet0", "R-DC", "GigabitEthernet0/1"),
        link("SRV-STORE", "FastEthernet0", "R-DC", "GigabitEthernet0/2"),
    ]
    lab = state([dc], hosts, links)
    return build_case(
        "CASE-024",
        title="Storage LAN became unreachable after the campus interface mask was widened",
        severity="High",
        symptom=(
            "Since the campus interface was re-addressed, PC-CAMPUS treats the storage server "
            "as a local host and ARPs for it instead of routing to it. The storage server "
            "answers nothing, and R-DC has two connected networks that overlap."
        ),
        topology_note=(
            "Data centre router lab (simulated). R-DC Gi0/1 serves the campus LAN and Gi0/2 "
            "serves the storage LAN 192.168.30.0/24 with gateway 192.168.30.1. The campus LAN "
            "is documented as 192.168.0.0/24, not as a /16."
        ),
        concept="ROUTING",
        osi="L3",
        fault=(
            "R-DC Gi0/1 is configured 192.168.0.1 255.255.0.0, so its connected network "
            "192.168.0.0/16 swallows the storage network 192.168.30.0/24 on Gi0/2 — two "
            "interfaces claim overlapping address space."
        ),
        keywords=["overlapping subnets", "255.255.0.0", "192.168.30.0/24", "R-DC"],
        rules=["R009"],
        fixes=[
            "On R-DC: interface GigabitEthernet0/1",
            "Restore the documented mask: ip address 192.168.0.1 255.255.255.0",
            "Correct the mask on every campus host to 255.255.255.0",
            "Confirm show ip route no longer shows overlapping connected networks",
            "Re-test: PC-CAMPUS ping 192.168.30.10",
        ],
        lab=lab,
        flows=[flow("PC-CAMPUS", "SRV-STORE", "tcp", 445, note="Campus access to storage")],
        extra=[
            ping("PC-CAMPUS", "192.168.30.10", ok=False,
                 note="Destination host unreachable (the host ARPs locally)."),
        ],
    )


CASES = [case_020, case_021, case_022, case_023, case_024]
