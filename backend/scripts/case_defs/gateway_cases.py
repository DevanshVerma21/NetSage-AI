"""Gateway cases (CASE-006 .. CASE-010)."""

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
    state,
    vlan,
)

_MASK = "255.255.255.0"


def case_006() -> dict:
    r1 = dev(
        "R1",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.50.1", _MASK, description="ACCOUNTING LAN"),
            ifc("GigabitEthernet0/1", "192.168.60.1", _MASK, description="SERVER LAN"),
        ],
    )
    hosts = [
        host("PC-ACC", "192.168.50.20", _MASK, "192.168.50.254", on="R1",
             port="GigabitEthernet0/0"),
        host("SRV-FILE", "192.168.60.10", _MASK, "192.168.60.1", on="R1",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-ACC", "FastEthernet0", "R1", "GigabitEthernet0/0"),
        link("SRV-FILE", "FastEthernet0", "R1", "GigabitEthernet0/1"),
    ]
    lab = state([r1], hosts, links)
    return build_case(
        "CASE-006",
        title="Accounting PC reaches its own subnet but nothing beyond it",
        severity="High",
        symptom=(
            "PC-ACC can ping other hosts in 192.168.50.0/24 but every ping to the server LAN "
            "fails immediately with 'Destination host unreachable'. Its ARP table has no "
            "entry for a router."
        ),
        topology_note=(
            "Single router lab (simulated). R1 Gi0/0 = 192.168.50.1/24 serves the accounting "
            "LAN and Gi0/1 = 192.168.60.1/24 serves the server LAN. The documented default "
            "gateway for the accounting LAN is 192.168.50.1. Both router interfaces are up."
        ),
        concept="GATEWAY",
        osi="L3",
        fault=(
            "PC-ACC's default gateway is 192.168.50.254, an address inside its own subnet "
            "that no device in the topology owns, so it has no working first hop."
        ),
        keywords=["wrong default gateway", "192.168.50.254", "no first hop", "PC-ACC"],
        rules=["R003"],
        fixes=[
            "On PC-ACC, set the default gateway to the documented router address 192.168.50.1",
            "Confirm ipconfig /all shows Default Gateway 192.168.50.1",
            "Re-test: PC-ACC ping 192.168.50.1, then ping 192.168.60.10",
        ],
        lab=lab,
        flows=[flow("PC-ACC", "SRV-FILE", "tcp", 445, note="Accounting file share")],
        extra=[
            ping("PC-ACC", "192.168.50.254", ok=False, note="Destination host unreachable."),
            ping("PC-ACC", "192.168.60.10", ok=False, note="Destination host unreachable."),
            ping("SRV-FILE", "192.168.60.1", ok=True),
        ],
    )


def _branch_lab(pc_ip: str, pc_mask: str, pc_gw, lan: str = "192.168.70") -> tuple:
    r1 = dev(
        "R2",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", f"{lan}.1", _MASK, description="BRANCH LAN"),
            ifc("GigabitEthernet0/1", "10.20.0.1", "255.255.255.252", description="TO DC"),
        ],
        routes=[],
    )
    hosts = [
        host("PC-BRANCH", pc_ip, pc_mask, pc_gw, on="R2", port="GigabitEthernet0/0"),
        host("PC-DESK", f"{lan}.30", _MASK, f"{lan}.1", on="R2", port="GigabitEthernet0/0"),
    ]
    links = [
        link("PC-BRANCH", "FastEthernet0", "R2", "GigabitEthernet0/0"),
        link("PC-DESK", "FastEthernet0", "R2", "GigabitEthernet0/0"),
    ]
    return state([r1], hosts, links)


def case_007() -> dict:
    lab = _branch_lab("192.168.70.20", _MASK, "192.168.7.1")
    return build_case(
        "CASE-007",
        title="Branch PC has a gateway address that is not on its own network",
        severity="High",
        symptom=(
            "PC-BRANCH cannot leave the branch LAN. PC-DESK on the same switchport range works "
            "normally. PC-BRANCH's ping to its configured gateway fails without ever leaving "
            "the host."
        ),
        topology_note=(
            "Branch router lab (simulated). R2 Gi0/0 = 192.168.70.1/24 is the branch LAN "
            "gateway and Gi0/1 = 10.20.0.1/30 is the link toward the data centre. Both PCs "
            "sit in 192.168.70.0/24 and must use 192.168.70.1 as their default gateway."
        ),
        concept="GATEWAY",
        osi="L3",
        fault=(
            "PC-BRANCH's default gateway 192.168.7.1 is outside its own 192.168.70.0/24 "
            "network (a mistyped octet), so the host cannot ARP for it at all."
        ),
        keywords=["gateway outside subnet", "192.168.7.1", "192.168.70.0/24", "PC-BRANCH"],
        rules=["R003"],
        fixes=[
            "On PC-BRANCH, correct the default gateway to 192.168.70.1",
            "Confirm the gateway is inside 192.168.70.0/24 in ipconfig /all",
            "Re-test: PC-BRANCH ping 192.168.70.1, then ping 10.20.0.1",
        ],
        lab=lab,
        flows=[flow("PC-BRANCH", "PC-DESK", note="Branch peer-to-peer print sharing")],
        extra=[
            ping("PC-BRANCH", "192.168.7.1", ok=False,
                 note="Destination host unreachable (no route on the local host)."),
            ping("PC-DESK", "192.168.70.1", ok=True),
        ],
    )


def case_008() -> dict:
    core = dev(
        "SW-CORE",
        ifaces=[
            ifc("GigabitEthernet1/0/1", vlan=40, mode="access"),
            ifc("GigabitEthernet1/0/2", vlan=41, mode="access"),
            ifc("Vlan40", "192.168.40.1", _MASK, vlan=40),
            ifc("Vlan41", "192.168.41.1", _MASK, vlan=41),
        ],
        vlans=[vlan(1, "default"), vlan(40, "HR"), vlan(41, "LAB")],
    )
    hosts = [
        host("PC-LAB", "192.168.41.25", _MASK, None, vlan_id=41, on="SW-CORE",
             port="GigabitEthernet1/0/2"),
        host("SRV-HR", "192.168.40.10", _MASK, "192.168.40.1", vlan_id=40, on="SW-CORE",
             port="GigabitEthernet1/0/1"),
    ]
    links = [
        link("PC-LAB", "FastEthernet0", "SW-CORE", "GigabitEthernet1/0/2", vlan_id=41),
        link("SRV-HR", "FastEthernet0", "SW-CORE", "GigabitEthernet1/0/1", vlan_id=40),
    ]
    lab = state([core], hosts, links)
    return build_case(
        "CASE-008",
        title="Freshly imaged lab PC has an address and mask but no default gateway",
        severity="High",
        symptom=(
            "PC-LAB was given a static address during imaging. It reaches other hosts in the "
            "lab VLAN, but every attempt to reach the HR server 192.168.40.10 fails at once. "
            "ipconfig shows an empty Default Gateway line."
        ),
        topology_note=(
            "Campus core lab (simulated). SW-CORE is a multilayer switch with ip routing "
            "enabled. VLAN 40 HR = 192.168.40.0/24 and VLAN 41 LAB = 192.168.41.0/24 each "
            "have an up SVI; 192.168.41.1 is the documented gateway for the lab VLAN."
        ),
        concept="GATEWAY",
        osi="L3",
        fault=(
            "PC-LAB has no default gateway configured at all, so it can only reach its own "
            "subnet even though the Vlan41 SVI is up and routing works."
        ),
        keywords=["missing default gateway", "PC-LAB", "static configuration", "192.168.41.1"],
        rules=["R003"],
        fixes=[
            "On PC-LAB, set the default gateway to 192.168.41.1",
            "Confirm ipconfig /all now lists a default gateway",
            "Re-test: PC-LAB ping 192.168.41.1, then ping 192.168.40.10",
        ],
        lab=lab,
        flows=[flow("PC-LAB", "SRV-HR", "tcp", 443, note="Lab access to the HR portal")],
        extra=[
            ping("PC-LAB", "192.168.40.10", ok=False, note="Destination host unreachable."),
            capture("PC-LAB", "route print | include 0.0.0.0",
                    "! no default route is present in the host routing table"),
        ],
    )


def case_009() -> dict:
    r3 = dev(
        "R3",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.80.1", _MASK, description="FINANCE LAN"),
            ifc("GigabitEthernet0/1", "192.168.81.1", _MASK, description="DC LAN"),
        ],
    )
    hosts = [
        host("PC-FIN", "192.168.80.20", _MASK, "192.168.80.50", on="R3",
             port="GigabitEthernet0/0"),
        host("SRV-PRINT", "192.168.80.50", _MASK, "192.168.80.1", on="R3",
             port="GigabitEthernet0/0"),
        host("SRV-PAY", "192.168.81.10", _MASK, "192.168.81.1", on="R3",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-FIN", "FastEthernet0", "R3", "GigabitEthernet0/0"),
        link("SRV-PRINT", "FastEthernet0", "R3", "GigabitEthernet0/0"),
        link("SRV-PAY", "FastEthernet0", "R3", "GigabitEthernet0/1"),
    ]
    lab = state([r3], hosts, links)
    return build_case(
        "CASE-009",
        title="Finance PC uses the print server as its default gateway",
        severity="High",
        symptom=(
            "PC-FIN can print and can reach every host on the finance LAN, but the payroll "
            "server on 192.168.81.0/24 is unreachable. Its gateway pings successfully, which "
            "makes the fault look like a routing problem at first."
        ),
        topology_note=(
            "Single router lab (simulated). R3 Gi0/0 = 192.168.80.1/24 is the finance LAN "
            "gateway; Gi0/1 = 192.168.81.1/24 serves the data centre LAN. 192.168.80.50 is "
            "SRV-PRINT, an end host that does not route. The documented finance gateway is "
            "192.168.80.1."
        ),
        concept="GATEWAY",
        osi="L3",
        fault=(
            "PC-FIN's default gateway 192.168.80.50 is the print server, not a routed "
            "interface, so the gateway answers ICMP but forwards nothing off-subnet."
        ),
        keywords=["gateway wrong device", "192.168.80.50", "print server", "not a router"],
        rules=["R003"],
        fixes=[
            "On PC-FIN, set the default gateway to the router address 192.168.80.1",
            "Confirm 192.168.80.1 is owned by R3 Gi0/0 in show ip interface brief",
            "Re-test: PC-FIN ping 192.168.81.10",
        ],
        lab=lab,
        flows=[flow("PC-FIN", "SRV-PAY", "tcp", 443, note="Payroll web application")],
        extra=[
            ping("PC-FIN", "192.168.80.50", ok=True, note="The gateway address answers."),
            ping("PC-FIN", "192.168.81.10", ok=False, note="Request timed out."),
        ],
    )


def case_010() -> dict:
    edge = dev(
        "SW-EDGE",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=90, mode="access"),
            ifc("GigabitEthernet0/2", vlan=91, mode="access"),
            ifc("Vlan90", "192.168.90.1", _MASK, vlan=90),
            ifc("Vlan91", "192.168.91.1", _MASK, vlan=91),
        ],
        vlans=[vlan(1, "default"), vlan(90, "SUPPORT"), vlan(91, "APPS")],
    )
    hosts = [
        host("PC-SUP", "192.168.90.20", "255.255.255.128", "192.168.90.1", vlan_id=90,
             on="SW-EDGE", port="GigabitEthernet0/1"),
        host("SRV-APP", "192.168.91.10", _MASK, "192.168.91.1", vlan_id=91, on="SW-EDGE",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-SUP", "FastEthernet0", "SW-EDGE", "GigabitEthernet0/1", vlan_id=90),
        link("SRV-APP", "FastEthernet0", "SW-EDGE", "GigabitEthernet0/2", vlan_id=91),
    ]
    lab = state([edge], hosts, links)
    return build_case(
        "CASE-010",
        title="Support PC reaches its gateway but only half of its own VLAN",
        severity="Medium",
        symptom=(
            "PC-SUP pings its gateway and the apps server, but cannot reach support hosts "
            "numbered above 192.168.90.127 — those it tries to send via the router instead of "
            "directly, and the returning traffic is dropped."
        ),
        topology_note=(
            "Edge switch lab (simulated). SW-EDGE is a multilayer switch. VLAN 90 SUPPORT = "
            "192.168.90.0/24 with gateway 192.168.90.1 and VLAN 91 APPS = 192.168.91.0/24 "
            "with gateway 192.168.91.1. Every host in VLAN 90 is documented as /24."
        ),
        concept="GATEWAY",
        osi="L3",
        fault=(
            "PC-SUP's subnet mask is 255.255.255.128 while its gateway interface Vlan90 uses "
            "255.255.255.0, so the host and its gateway disagree about the size of the "
            "segment."
        ),
        keywords=["subnet mask mismatch", "255.255.255.128", "vlan 90", "PC-SUP"],
        rules=["R002"],
        fixes=[
            "On PC-SUP, set the subnet mask to 255.255.255.0 to match the Vlan90 SVI",
            "Confirm the host mask and the gateway interface mask agree",
            "Re-test: PC-SUP ping a host above 192.168.90.127 in the same VLAN",
        ],
        lab=lab,
        flows=[flow("PC-SUP", "SRV-APP", "tcp", 8080, note="Support tooling to the apps server")],
        extra=[
            ping("PC-SUP", "192.168.90.1", ok=True),
            ping("PC-SUP", "192.168.90.200", ok=False, note="Request timed out."),
        ],
    )


CASES = [case_006, case_007, case_008, case_009, case_010]
