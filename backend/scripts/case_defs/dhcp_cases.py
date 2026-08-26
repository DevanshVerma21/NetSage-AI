"""DHCP cases (CASE-011 .. CASE-015)."""

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
    pool,
    state,
    vlan,
)

_MASK = "255.255.255.0"


def case_011() -> dict:
    sw = dev(
        "SW-DHCP",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=100, mode="access"),
            ifc("GigabitEthernet0/2", vlan=100, mode="access"),
            ifc("GigabitEthernet0/3", vlan=101, mode="access"),
            ifc("Vlan100", "192.168.100.1", _MASK, vlan=100),
            ifc("Vlan101", "192.168.101.1", _MASK, vlan=101),
        ],
        vlans=[vlan(1, "default"), vlan(100, "STAFF"), vlan(101, "SERVERS")],
        pools=[
            pool("STAFF-POOL", "192.168.10.0", _MASK, router="192.168.100.1",
                 dns=["192.168.101.10"]),
        ],
    )
    hosts = [
        host("PC-NEW", None, _MASK, None, vlan_id=100, on="SW-DHCP",
             port="GigabitEthernet0/1", dhcp=True),
        host("PC-STATIC", "192.168.100.30", _MASK, "192.168.100.1", vlan_id=100, on="SW-DHCP",
             port="GigabitEthernet0/2"),
        host("SRV-DNS", "192.168.101.10", _MASK, "192.168.101.1", vlan_id=101, on="SW-DHCP",
             port="GigabitEthernet0/3"),
    ]
    links = [
        link("PC-NEW", "FastEthernet0", "SW-DHCP", "GigabitEthernet0/1", vlan_id=100),
        link("PC-STATIC", "FastEthernet0", "SW-DHCP", "GigabitEthernet0/2", vlan_id=100),
        link("SRV-DNS", "FastEthernet0", "SW-DHCP", "GigabitEthernet0/3", vlan_id=101),
    ]
    lab = state([sw], hosts, links)
    return build_case(
        "CASE-011",
        title="New staff PCs get no address while statically addressed PCs work",
        severity="High",
        symptom=(
            "PC-NEW never receives a lease and ends up with 0.0.0.0. PC-STATIC in the same "
            "VLAN, configured by hand, works normally. The DHCP pool exists on SW-DHCP and the "
            "service is running."
        ),
        topology_note=(
            "Multilayer switch lab (simulated). SW-DHCP routes between VLAN 100 STAFF = "
            "192.168.100.0/24 and VLAN 101 SERVERS = 192.168.101.0/24 and is also the DHCP "
            "server for the staff VLAN. Staff clients must receive addresses out of "
            "192.168.100.0/24 with gateway 192.168.100.1."
        ),
        concept="DHCP",
        osi="L3",
        fault=(
            "The STAFF-POOL network is 192.168.10.0/24, which matches none of SW-DHCP's "
            "attached subnets, so no pool serves the 192.168.100.0/24 staff segment and its "
            "clients get nothing."
        ),
        keywords=["dhcp pool network", "192.168.10.0", "192.168.100.0/24", "no lease"],
        rules=["R010"],
        fixes=[
            "On SW-DHCP: ip dhcp pool STAFF-POOL",
            "Correct the pool network: network 192.168.100.0 255.255.255.0",
            "Confirm default-router 192.168.100.1 is now inside the pool network",
            "Release and renew on PC-NEW, then confirm it leases an address in "
            "192.168.100.0/24",
        ],
        lab=lab,
        flows=[flow("PC-NEW", "SRV-DNS", "tcp", 443, note="Staff intranet portal")],
        extra=[
            ping("PC-STATIC", "192.168.100.1", ok=True),
            capture("SW-DHCP", "show ip dhcp binding",
                    "Bindings from all pools not associated with VRF:\n"
                    "IP address    Client-ID/Hardware address    Lease expiration    Type\n"
                    "! no bindings"),
        ],
    )


def case_012() -> dict:
    r1 = dev(
        "R-CAMPUS",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.110.1", _MASK, description="LAB LAN"),
            ifc("GigabitEthernet0/1", "192.168.112.1", _MASK, description="SERVER LAN"),
        ],
        pools=[
            pool("LAB-POOL", "192.168.110.0", _MASK, router="192.168.111.1",
                 excluded=["192.168.110.1", "192.168.110.10"]),
        ],
    )
    hosts = [
        host("PC-LEASED", "192.168.110.25", _MASK, "192.168.111.1", on="R-CAMPUS",
             port="GigabitEthernet0/0", dhcp=True),
        host("SRV-LMS", "192.168.112.10", _MASK, "192.168.112.1", on="R-CAMPUS",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-LEASED", "FastEthernet0", "R-CAMPUS", "GigabitEthernet0/0"),
        link("SRV-LMS", "FastEthernet0", "R-CAMPUS", "GigabitEthernet0/1"),
    ]
    lab = state([r1], hosts, links)
    return build_case(
        "CASE-012",
        title="DHCP clients lease a correct address but hand back an unusable gateway",
        severity="High",
        symptom=(
            "PC-LEASED receives 192.168.110.25/24 from DHCP and can reach other lab hosts, but "
            "nothing off-subnet works. Its default gateway shows as 192.168.111.1, which is "
            "not an address on the lab network."
        ),
        topology_note=(
            "Campus router lab (simulated). R-CAMPUS Gi0/0 = 192.168.110.1/24 serves the lab "
            "LAN and is its DHCP server; Gi0/1 = 192.168.112.1/24 serves the server LAN. Lab "
            "clients must be handed the gateway 192.168.110.1."
        ),
        concept="DHCP",
        osi="L3",
        fault=(
            "LAB-POOL hands out default-router 192.168.111.1, which is outside the pool's own "
            "192.168.110.0/24 network and belongs to no interface, so every client installs an "
            "unreachable gateway."
        ),
        keywords=["default-router", "192.168.111.1", "wrong gateway from dhcp", "LAB-POOL"],
        rules=["R003", "R010"],
        fixes=[
            "On R-CAMPUS: ip dhcp pool LAB-POOL",
            "Correct the option: default-router 192.168.110.1",
            "Release and renew on PC-LEASED",
            "Confirm ipconfig /all shows Default Gateway 192.168.110.1",
            "Re-test: PC-LEASED ping 192.168.112.10",
        ],
        lab=lab,
        flows=[flow("PC-LEASED", "SRV-LMS", "tcp", 443, note="Lab access to the LMS")],
        extra=[
            ping("PC-LEASED", "192.168.111.1", ok=False, note="Request timed out."),
            ping("PC-LEASED", "192.168.112.10", ok=False, note="Request timed out."),
        ],
    )


def case_013() -> dict:
    sw = dev(
        "SW-BR",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=120, mode="access"),
            ifc("GigabitEthernet0/2", vlan=120, mode="access"),
            ifc("Vlan120", "192.168.120.1", _MASK, vlan=120),
        ],
        vlans=[vlan(1, "default"), vlan(120, "BRANCH")],
        pools=[
            pool("BRANCH-POOL", "192.168.120.0", _MASK, router="192.168.120.1",
                 excluded=["192.168.12.1"]),
        ],
    )
    hosts = [
        host("SRV-APP", "192.168.120.50", _MASK, "192.168.120.1", vlan_id=120, on="SW-BR",
             port="GigabitEthernet0/1"),
        host("PC-TEMP", "192.168.120.50", _MASK, "192.168.120.1", vlan_id=120, on="SW-BR",
             port="GigabitEthernet0/2", dhcp=True),
    ]
    links = [
        link("SRV-APP", "FastEthernet0", "SW-BR", "GigabitEthernet0/1", vlan_id=120),
        link("PC-TEMP", "FastEthernet0", "SW-BR", "GigabitEthernet0/2", vlan_id=120),
    ]
    lab = state([sw], hosts, links)
    return build_case(
        "CASE-013",
        title="Branch application server drops off the network whenever a laptop leases an address",
        severity="Critical",
        symptom=(
            "SRV-APP becomes unreachable minutes after PC-TEMP is plugged in. Both hosts log "
            "an address conflict, and the branch switch shows two MAC addresses claiming "
            "192.168.120.50."
        ),
        topology_note=(
            "Branch switch lab (simulated). SW-BR is the multilayer switch and the DHCP server "
            "for VLAN 120 BRANCH = 192.168.120.0/24, gateway 192.168.120.1. The statically "
            "addressed server SRV-APP owns 192.168.120.50 and that address is supposed to be "
            "excluded from the pool."
        ),
        concept="DHCP",
        osi="L3",
        fault=(
            "The exclusion was typed as 192.168.12.1, an address outside the pool network, so "
            "192.168.120.50 was never excluded and DHCP leased the server's address to "
            "PC-TEMP."
        ),
        keywords=["excluded address", "192.168.12.1", "duplicate ip", "192.168.120.50"],
        rules=["R001", "R010"],
        fixes=[
            "On SW-BR: no ip dhcp excluded-address 192.168.12.1",
            "Add the correct exclusion: ip dhcp excluded-address 192.168.120.1 192.168.120.60",
            "Release the incorrect lease: clear ip dhcp binding 192.168.120.50",
            "Renew on PC-TEMP and confirm it receives a different address",
            "Confirm SRV-APP is reachable again on 192.168.120.50",
        ],
        lab=lab,
        flows=[flow("PC-TEMP", "SRV-APP", "tcp", 443, note="Branch staff to the application")],
        extra=[
            capture("SW-BR", "show ip dhcp conflict",
                    "IP address       Detection method   Detection time\n"
                    "192.168.120.50   Gratuitous ARP     Aug 24 2026 09:12 AM"),
            ping("PC-TEMP", "192.168.120.1", ok=True),
        ],
    )


def case_014() -> dict:
    sw = dev(
        "SW-CAMP",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=130, mode="access"),
            ifc("GigabitEthernet0/2", vlan=131, mode="access"),
            ifc("Vlan130", "192.168.130.1", _MASK, vlan=130),
            ifc("Vlan131", "192.168.131.1", _MASK, vlan=131, helpers=()),
        ],
        vlans=[vlan(1, "default"), vlan(130, "CLASSROOM"), vlan(131, "SERVERS")],
    )
    hosts = [
        host("PC-CLASS", None, _MASK, None, vlan_id=130, on="SW-CAMP",
             port="GigabitEthernet0/1", dhcp=True),
        host("SRV-DHCP", "192.168.131.10", _MASK, "192.168.131.1", vlan_id=131, on="SW-CAMP",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-CLASS", "FastEthernet0", "SW-CAMP", "GigabitEthernet0/1", vlan_id=130),
        link("SRV-DHCP", "FastEthernet0", "SW-CAMP", "GigabitEthernet0/2", vlan_id=131),
    ]
    lab = state([sw], hosts, links)
    return build_case(
        "CASE-014",
        title="Classroom VLAN gets no leases after the DHCP relay configuration was lost",
        severity="High",
        symptom=(
            "Every client in the classroom VLAN comes up with 0.0.0.0 after the switch was "
            "reloaded from an older configuration file. The central DHCP server SRV-DHCP is "
            "up and still leasing addresses to other VLANs."
        ),
        topology_note=(
            "Campus switch lab (simulated). SW-CAMP routes between VLAN 130 CLASSROOM = "
            "192.168.130.0/24 and VLAN 131 SERVERS = 192.168.131.0/24. DHCP is not served by "
            "the switch: the classroom SVI is supposed to relay requests to the central server "
            "192.168.131.10 with ip helper-address."
        ),
        concept="DHCP",
        osi="L3",
        fault=(
            "The classroom segment has no DHCP pool on any device and the Vlan130 SVI has no "
            "ip helper-address, so DHCP discovers from PC-CLASS are never answered or relayed."
        ),
        keywords=["ip helper-address", "dhcp relay missing", "vlan 130", "no lease"],
        rules=["R010"],
        fixes=[
            "On SW-CAMP: interface Vlan130",
            "Restore the relay: ip helper-address 192.168.131.10",
            "Confirm the helper address appears in show running-config interface Vlan130",
            "Release and renew on PC-CLASS and confirm it leases an address in "
            "192.168.130.0/24",
        ],
        lab=lab,
        flows=[flow("PC-CLASS", "SRV-DHCP", "tcp", 443, note="Classroom access to courseware")],
        extra=[
            capture("SW-CAMP", "show running-config interface Vlan130",
                    "interface Vlan130\n ip address 192.168.130.1 255.255.255.0\n"
                    "! no ip helper-address is configured"),
            ping("SRV-DHCP", "192.168.131.1", ok=True),
        ],
    )


def case_015() -> dict:
    sw = dev(
        "SW-RETAIL",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=140, mode="access"),
            ifc("GigabitEthernet0/2", vlan=141, mode="access"),
            ifc("Vlan140", "192.168.140.1", _MASK, vlan=140),
            ifc("Vlan141", "192.168.141.1", _MASK, vlan=141),
        ],
        vlans=[vlan(1, "default"), vlan(140, "TILLS"), vlan(141, "SERVERS")],
        pools=[
            pool("TILL-POOL", "192.168.140.0", _MASK, router="192.168.140.1",
                 dns=["192.168.140.253"], excluded=["192.168.140.1"]),
        ],
    )
    hosts = [
        host("PC-TILL", "192.168.140.30", _MASK, "192.168.140.1", dns=["192.168.140.253"],
             vlan_id=140, on="SW-RETAIL", port="GigabitEthernet0/1", dhcp=True),
        host("SRV-DNS", "192.168.141.53", _MASK, "192.168.141.1", vlan_id=141, on="SW-RETAIL",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-TILL", "FastEthernet0", "SW-RETAIL", "GigabitEthernet0/1", vlan_id=140),
        link("SRV-DNS", "FastEthernet0", "SW-RETAIL", "GigabitEthernet0/2", vlan_id=141),
    ]
    lab = state([sw], hosts, links)
    return build_case(
        "CASE-015",
        title="Till PCs lease correct addresses but cannot resolve any name",
        severity="High",
        symptom=(
            "PC-TILL leases 192.168.140.30/24 with the right gateway and can ping the server "
            "VLAN by address, but every name lookup times out. Its DNS server is listed as "
            "192.168.140.253."
        ),
        topology_note=(
            "Retail switch lab (simulated). SW-RETAIL routes between VLAN 140 TILLS = "
            "192.168.140.0/24 and VLAN 141 SERVERS = 192.168.141.0/24 and serves DHCP for the "
            "till VLAN. The only name server in this topology is SRV-DNS on 192.168.141.53."
        ),
        concept="DHCP",
        osi="L3",
        fault=(
            "TILL-POOL hands out dns-server 192.168.140.253, an address no device or host in "
            "the topology owns, so clients receive a resolver that does not exist."
        ),
        keywords=["dhcp dns-server", "192.168.140.253", "wrong dns handed out", "TILL-POOL"],
        rules=["R010"],
        fixes=[
            "On SW-RETAIL: ip dhcp pool TILL-POOL",
            "Correct the option: dns-server 192.168.141.53",
            "Release and renew on PC-TILL",
            "Confirm ipconfig /all lists 192.168.141.53 as the DNS server",
        ],
        lab=lab,
        flows=[flow("PC-TILL", "SRV-DNS", "tcp", 443, note="Till software to the retail server")],
        extra=[
            ping("PC-TILL", "192.168.140.253", ok=False, note="Request timed out."),
            ping("PC-TILL", "192.168.141.53", ok=True),
        ],
    )


CASES = [case_011, case_012, case_013, case_014, case_015]
