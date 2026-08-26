"""VLAN cases (CASE-002 .. CASE-005). CASE-001 is preserved verbatim from the dataset."""

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


def case_002() -> dict:
    sw1 = dev(
        "SW1",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=10, mode="access"),
            ifc("GigabitEthernet0/2", vlan=20, mode="access"),
            ifc("GigabitEthernet0/3", vlan=30, mode="access"),
            ifc("Vlan10", "192.168.10.1", _MASK, vlan=10),
            ifc("Vlan20", "192.168.20.1", _MASK, vlan=20),
        ],
        vlans=[vlan(1, "default"), vlan(10, "STAFF"), vlan(20, "VOICE"), vlan(30, "SERVERS")],
    )
    hosts = [
        host("PC-STAFF", "192.168.10.20", _MASK, "192.168.10.1", vlan_id=10, on="SW1",
             port="GigabitEthernet0/1"),
        host("SRV-ERP", "192.168.30.10", _MASK, "192.168.30.1", vlan_id=30, on="SW1",
             port="GigabitEthernet0/3"),
    ]
    links = [
        link("PC-STAFF", "FastEthernet0", "SW1", "GigabitEthernet0/1", vlan_id=10),
        link("SRV-ERP", "FastEthernet0", "SW1", "GigabitEthernet0/3", vlan_id=30),
    ]
    lab = state([sw1], hosts, links)
    return build_case(
        "CASE-002",
        title="New SERVERS VLAN was created but nobody can reach the ERP server",
        symptom=(
            "VLAN 30 was created on SW1 last night and SRV-ERP was moved into it. The server "
            "answers on the local segment but no staff PC can reach 192.168.30.10, and the "
            "server itself cannot reach anything outside its own VLAN."
        ),
        topology_note=(
            "Single multilayer switch lab (simulated). SW1 does inter-VLAN routing with ip "
            "routing enabled. VLAN 10 STAFF = 192.168.10.0/24, VLAN 20 VOICE = "
            "192.168.20.0/24, VLAN 30 SERVERS = 192.168.30.0/24. Every VLAN is supposed to "
            "have an SVI on SW1 as its gateway; 192.168.30.1 is the documented gateway for "
            "the SERVERS VLAN. PC-STAFF is on Gi0/1, SRV-ERP on Gi0/3."
        ),
        concept="VLAN",
        osi="L3",
        severity="High",
        fault=(
            "VLAN 30 exists and has a member, but no Vlan30 SVI was ever created on SW1, so "
            "192.168.30.0/24 has no gateway and no connected route."
        ),
        keywords=["missing svi", "vlan 30", "no gateway", "inter-vlan routing", "SW1"],
        rules=["R003", "R006", "R015"],
        fixes=[
            "On SW1, create the missing SVI: interface Vlan30",
            "Assign the documented gateway address: ip address 192.168.30.1 255.255.255.0",
            "Bring it up: no shutdown",
            "Confirm Vlan30 is up/up in show ip interface brief",
            "Confirm 192.168.30.0/24 now appears as a connected route in show ip route",
            "Re-test: PC-STAFF ping 192.168.30.10",
        ],
        lab=lab,
        flows=[
            flow("PC-STAFF", "SRV-ERP", "tcp", 443, note="ERP web front end"),
            flow("SRV-ERP", "PC-STAFF", note="ERP push notifications"),
        ],
        extra=[
            ping("PC-STAFF", "192.168.10.1", ok=True),
            ping("PC-STAFF", "192.168.30.10", ok=False),
            ping("SRV-ERP", "192.168.30.1", ok=False, note="Destination host unreachable."),
            capture(
                "SW1",
                "show running-config | include interface Vlan",
                "interface Vlan10\ninterface Vlan20",
            ),
        ],
    )


def case_003() -> dict:
    sw1 = dev(
        "SW1",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=10, mode="access", description="PC-SALES"),
            ifc("GigabitEthernet0/2", vlan=10, mode="access", description="PC-HR"),
            ifc("Vlan10", "192.168.10.1", _MASK, vlan=10),
            ifc("Vlan20", "192.168.20.1", _MASK, vlan=20),
        ],
        vlans=[vlan(1, "default"), vlan(10, "SALES"), vlan(20, "HR")],
    )
    hosts = [
        host("PC-SALES", "192.168.10.30", _MASK, "192.168.10.1", vlan_id=10, on="SW1",
             port="GigabitEthernet0/1"),
        host("PC-HR", "192.168.20.30", _MASK, "192.168.20.1", vlan_id=20, on="SW1",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-SALES", "FastEthernet0", "SW1", "GigabitEthernet0/1", vlan_id=10),
        link("PC-HR", "FastEthernet0", "SW1", "GigabitEthernet0/2", vlan_id=20),
    ]
    lab = state([sw1], hosts, links)
    return build_case(
        "CASE-003",
        title="Re-patched HR PC lands in the SALES VLAN and never reaches its gateway",
        severity="High",
        symptom=(
            "PC-HR was moved to a new port after a desk move. It has its documented HR "
            "address 192.168.20.30 but cannot ping its gateway 192.168.20.1, and a packet "
            "capture shows its ARP requests arriving in the SALES broadcast domain."
        ),
        topology_note=(
            "Single multilayer switch lab (simulated). VLAN 10 SALES = 192.168.10.0/24 on "
            "Gi0/1, VLAN 20 HR = 192.168.20.0/24. The cabling record says Gi0/2 is an HR "
            "access port, so PC-HR on Gi0/2 must be in VLAN 20. Both SVIs exist and are up."
        ),
        concept="VLAN",
        osi="L2",
        fault=(
            "SW1 Gi0/2 is configured switchport access vlan 10, but the port serves the HR "
            "segment, so PC-HR's frames are switched into VLAN 10 instead of VLAN 20."
        ),
        keywords=["wrong access vlan", "gi0/2", "vlan 10", "vlan 20", "access port"],
        rules=["R007"],
        fixes=[
            "On SW1: interface GigabitEthernet0/2",
            "Correct the access VLAN: switchport access vlan 20",
            "Confirm Gi0/2 is listed under VLAN 20 in show vlan brief",
            "Re-test: PC-HR ping 192.168.20.1",
        ],
        lab=lab,
        flows=[flow("PC-HR", "PC-SALES", note="HR file share access")],
        extra=[
            ping("PC-HR", "192.168.20.1", ok=False, note="Request timed out."),
            capture(
                "SW1",
                "show running-config interface GigabitEthernet0/2",
                "interface GigabitEthernet0/2\n switchport mode access\n switchport access vlan 10",
            ),
        ],
    )


def _two_switch_hosts() -> tuple[list, list]:
    hosts = [
        host("PC-ENG", "192.168.10.40", _MASK, "192.168.10.1", vlan_id=10, on="SW1",
             port="GigabitEthernet0/1"),
        host("PC-FIN", "192.168.20.40", _MASK, "192.168.20.1", vlan_id=20, on="SW2",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-ENG", "FastEthernet0", "SW1", "GigabitEthernet0/1", vlan_id=10),
        link("PC-FIN", "FastEthernet0", "SW2", "GigabitEthernet0/1", vlan_id=20),
    ]
    return hosts, links


def case_004() -> dict:
    sw1 = dev(
        "SW1",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=10, mode="access"),
            ifc("GigabitEthernet0/24", mode="trunk", allowed=(10, 20), native=1),
            ifc("Vlan10", "192.168.10.1", _MASK, vlan=10),
            ifc("Vlan20", "192.168.20.1", _MASK, vlan=20),
        ],
        vlans=[vlan(1, "default"), vlan(10, "ENG"), vlan(20, "FIN")],
    )
    sw2 = dev(
        "SW2",
        kind="switch",
        routing=False,
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=20, mode="access"),
            ifc("GigabitEthernet0/24", mode="trunk", allowed=(10,), native=1),
        ],
        vlans=[vlan(1, "default"), vlan(10, "ENG"), vlan(20, "FIN")],
    )
    hosts, links = _two_switch_hosts()
    links.append(
        link("SW1", "GigabitEthernet0/24", "SW2", "GigabitEthernet0/24", mode="trunk",
             allowed=(10, 20), native=1)
    )
    lab = state([sw1, sw2], hosts, links)
    return build_case(
        "CASE-004",
        title="Finance PCs on the access switch lost their gateway after a trunk change",
        severity="High",
        symptom=(
            "After maintenance on the SW1-SW2 uplink, every PC in VLAN 20 behind SW2 stopped "
            "reaching its gateway 192.168.20.1. VLAN 10 users on the same uplink are fine, "
            "and PC-FIN can still see other VLAN 20 hosts on SW2 itself."
        ),
        topology_note=(
            "Two-switch lab (simulated). SW1 is the multilayer switch and holds the SVIs for "
            "VLAN 10 ENG = 192.168.10.0/24 and VLAN 20 FIN = 192.168.20.0/24. SW2 is a Layer "
            "2 access switch. The documented uplink Gi0/24 <-> Gi0/24 is an 802.1Q trunk that "
            "must carry VLANs 10 and 20 with native VLAN 1."
        ),
        concept="VLAN",
        osi="L2",
        fault=(
            "SW2's trunk Gi0/24 permits only VLAN 10 (switchport trunk allowed vlan 10), so "
            "VLAN 20 frames are pruned on the uplink and never reach the Vlan20 SVI on SW1."
        ),
        keywords=["trunk", "allowed vlan", "vlan 20 pruned", "gi0/24", "SW2"],
        rules=["R008"],
        fixes=[
            "On SW2: interface GigabitEthernet0/24",
            "Restore the documented VLAN list: switchport trunk allowed vlan 10,20",
            "Verify both VLANs are listed in show interfaces trunk on SW1 and SW2",
            "Re-test: PC-FIN ping 192.168.20.1",
        ],
        lab=lab,
        flows=[flow("PC-FIN", "PC-ENG", note="Finance access to the engineering share")],
        extra=[
            ping("PC-FIN", "192.168.20.1", ok=False, note="Request timed out."),
            ping("PC-ENG", "192.168.10.1", ok=True),
        ],
    )


def case_005() -> dict:
    sw1 = dev(
        "SW1",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=10, mode="access"),
            ifc("GigabitEthernet0/24", mode="trunk", allowed=(10, 20), native=1),
            ifc("Vlan10", "192.168.10.1", _MASK, vlan=10),
            ifc("Vlan20", "192.168.20.1", _MASK, vlan=20),
        ],
        vlans=[vlan(1, "default"), vlan(10, "ENG"), vlan(20, "FIN")],
    )
    sw2 = dev(
        "SW2",
        kind="switch",
        routing=False,
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=20, mode="access"),
            ifc("GigabitEthernet0/24", mode="trunk", allowed=(10, 20), native=99),
        ],
        vlans=[vlan(1, "default"), vlan(10, "ENG"), vlan(20, "FIN"), vlan(99, "MGMT-OLD")],
    )
    hosts, links = _two_switch_hosts()
    links.append(
        link("SW1", "GigabitEthernet0/24", "SW2", "GigabitEthernet0/24", mode="trunk",
             allowed=(10, 20), native=1)
    )
    lab = state([sw1, sw2], hosts, links)
    return build_case(
        "CASE-005",
        title="Untagged management traffic crosses into the wrong VLAN on the SW1-SW2 trunk",
        severity="Medium",
        symptom=(
            "The switches log a native VLAN mismatch on the uplink every few minutes. "
            "Untagged frames sent by SW2 land in VLAN 1 on SW1, management reachability to "
            "SW2 is intermittent, and the CDP neighbour entry keeps flapping."
        ),
        topology_note=(
            "Two-switch lab (simulated). The documented uplink Gi0/24 <-> Gi0/24 is an 802.1Q "
            "trunk carrying VLANs 10 and 20 with native VLAN 1 on both ends. SW1 holds the "
            "SVIs; SW2 is a Layer 2 access switch that still has a legacy VLAN 99 MGMT-OLD in "
            "its database from a previous management design."
        ),
        concept="VLAN",
        osi="L2",
        fault=(
            "SW2's trunk uses switchport trunk native vlan 99 while SW1 and the documented "
            "design use native VLAN 1, so untagged traffic is placed in a different VLAN at "
            "each end of the same trunk."
        ),
        keywords=["native vlan mismatch", "native vlan 99", "trunk", "gi0/24", "untagged"],
        rules=["R008"],
        fixes=[
            "On SW2: interface GigabitEthernet0/24",
            "Match the documented native VLAN: switchport trunk native vlan 1",
            "Confirm both ends report native VLAN 1 in show interfaces trunk",
            "Confirm the native VLAN mismatch log messages stop",
        ],
        lab=lab,
        flows=[flow("PC-FIN", "PC-ENG", note="Finance access to the engineering share")],
        extra=[
            capture(
                "SW1",
                "show logging | include CDP-4-NATIVE_VLAN_MISMATCH",
                "%CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered on "
                "GigabitEthernet0/24 (1), with SW2 GigabitEthernet0/24 (99).",
            ),
        ],
    )


CASES = [case_002, case_003, case_004, case_005]
