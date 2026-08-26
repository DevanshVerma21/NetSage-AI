"""DNS cases (CASE-016 .. CASE-019). Every case declares a DNS flow: R011 is intent-driven."""

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


def _dns_lab(net: str, vlan_id: int, name: str, client_dns, server_ip_last: int = 50,
             server_port_down: bool = False) -> tuple:
    admin = "shutdown" if server_port_down else "up"
    sw = dev(
        f"SW-{name}",
        ifaces=[
            ifc("GigabitEthernet0/1", vlan=vlan_id, mode="access", description="CLIENT"),
            ifc("GigabitEthernet0/2", vlan=vlan_id, mode="access", description="DNS SERVER",
                admin=admin, oper="down" if server_port_down else "up"),
            ifc(f"Vlan{vlan_id}", f"{net}.1", _MASK, vlan=vlan_id),
        ],
        vlans=[vlan(1, "default"), vlan(vlan_id, name)],
    )
    hosts = [
        host("PC-USER", f"{net}.20", _MASK, f"{net}.1", dns=client_dns, vlan_id=vlan_id,
             on=f"SW-{name}", port="GigabitEthernet0/1"),
        host("SRV-DNS", f"{net}.{server_ip_last}", _MASK, f"{net}.1", dns=[f"{net}.{server_ip_last}"],
             vlan_id=vlan_id, on=f"SW-{name}", port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-USER", "FastEthernet0", f"SW-{name}", "GigabitEthernet0/1", vlan_id=vlan_id),
        link("SRV-DNS", "FastEthernet0", f"SW-{name}", "GigabitEthernet0/2", vlan_id=vlan_id),
    ]
    return state([sw], hosts, links)


def case_016() -> dict:
    lab = _dns_lab("192.168.150", 150, "OFFICE", ["192.168.150.1"])
    return build_case(
        "CASE-016",
        title="Office PCs resolve nothing because they query the switch instead of the DNS server",
        severity="High",
        symptom=(
            "PC-USER can ping every host by address, including the DNS server, but nslookup "
            "for any name times out. Its configured DNS server is 192.168.150.1."
        ),
        topology_note=(
            "Office switch lab (simulated). SW-OFFICE is a multilayer switch; VLAN 150 OFFICE "
            "= 192.168.150.0/24 with SVI 192.168.150.1 as the gateway. The only name server in "
            "the topology is SRV-DNS on 192.168.150.50; the SVI does not run DNS."
        ),
        concept="DNS",
        osi="L7",
        fault=(
            "PC-USER's resolver is set to the gateway address 192.168.150.1 instead of the DNS "
            "server 192.168.150.50, so lookups are sent to a device that answers no queries."
        ),
        keywords=["wrong dns server", "192.168.150.1", "192.168.150.50", "nslookup timeout"],
        rules=["R011"],
        fixes=[
            "On PC-USER, set the DNS server to 192.168.150.50",
            "Confirm ipconfig /all lists 192.168.150.50 as the DNS server",
            "Re-test: nslookup srv-dns.lab from PC-USER",
        ],
        lab=lab,
        flows=[flow("PC-USER", "SRV-DNS", "dns", 53, note="Name resolution for office clients")],
        extra=[
            ping("PC-USER", "192.168.150.50", ok=True),
            capture("PC-USER", "nslookup srv-dns.lab",
                    "Server:  192.168.150.1\nAddress: 192.168.150.1\n\n"
                    "DNS request timed out.\n*** Request to 192.168.150.1 timed-out"),
        ],
    )


def case_017() -> dict:
    lab = _dns_lab("192.168.160", 160, "PLANT", ["10.10.10.53"])
    return build_case(
        "CASE-017",
        title="Plant floor PCs point at a DNS address that exists nowhere in the network",
        severity="High",
        symptom=(
            "Name resolution fails on every plant PC. The configured DNS server 10.10.10.53 "
            "does not answer ping either, and no device in the topology uses that address."
        ),
        topology_note=(
            "Plant switch lab (simulated). SW-PLANT is a multilayer switch; VLAN 160 PLANT = "
            "192.168.160.0/24 with SVI 192.168.160.1 as the gateway. SRV-DNS on "
            "192.168.160.50 is the resolver for the plant clients. There is no 10.10.0.0/8 "
            "network in this topology."
        ),
        concept="DNS",
        osi="L7",
        fault=(
            "PC-USER's resolver 10.10.10.53 is an address no device or host owns — a leftover "
            "from a previous site design — so DNS queries leave for a destination that does "
            "not exist."
        ),
        keywords=["unreachable dns", "10.10.10.53", "stale configuration", "192.168.160.50"],
        rules=["R011"],
        fixes=[
            "On PC-USER, replace the DNS server with 192.168.160.50",
            "Confirm no host still references 10.10.10.53",
            "Re-test: nslookup srv-dns.lab from PC-USER",
        ],
        lab=lab,
        flows=[flow("PC-USER", "SRV-DNS", "dns", 53, note="Name resolution for plant clients")],
        extra=[
            ping("PC-USER", "10.10.10.53", ok=False, note="Request timed out."),
            ping("PC-USER", "192.168.160.50", ok=True),
        ],
    )


def case_018() -> dict:
    lab = _dns_lab("192.168.170", 170, "CLINIC", [])
    return build_case(
        "CASE-018",
        title="Clinic PC was configured with no DNS server at all",
        severity="High",
        symptom=(
            "PC-USER reaches every address it is given but no application that uses a hostname "
            "works. ipconfig /all shows no DNS server entry."
        ),
        topology_note=(
            "Clinic switch lab (simulated). SW-CLINIC is a multilayer switch; VLAN 170 CLINIC "
            "= 192.168.170.0/24 with SVI 192.168.170.1 as the gateway. SRV-DNS on "
            "192.168.170.50 must be configured as the resolver on every clinic host."
        ),
        concept="DNS",
        osi="L7",
        fault=(
            "PC-USER has an empty DNS server list, so it has no resolver to send queries to "
            "even though the DNS server is up and reachable."
        ),
        keywords=["no dns configured", "empty resolver", "PC-USER", "192.168.170.50"],
        rules=["R011"],
        fixes=[
            "On PC-USER, configure the DNS server 192.168.170.50",
            "Confirm ipconfig /all lists the DNS server",
            "Re-test: nslookup srv-dns.lab from PC-USER",
        ],
        lab=lab,
        flows=[flow("PC-USER", "SRV-DNS", "dns", 53, note="Name resolution for clinic clients")],
        extra=[
            ping("PC-USER", "192.168.170.50", ok=True),
            capture("PC-USER", "nslookup srv-dns.lab",
                    "*** Can't find server name: no DNS servers are configured"),
        ],
    )


def case_019() -> dict:
    lab = _dns_lab("192.168.180", 180, "DEPOT", ["192.168.180.50"], server_port_down=True)
    return build_case(
        "CASE-019",
        title="Depot name resolution stopped after the DNS server's switchport was shut down",
        severity="Critical",
        symptom=(
            "All depot clients lost name resolution at the same moment. Their DNS "
            "configuration is correct, but the server does not answer ping and the switch "
            "shows its port as administratively down."
        ),
        topology_note=(
            "Depot switch lab (simulated). SW-DEPOT is a multilayer switch; VLAN 180 DEPOT = "
            "192.168.180.0/24 with SVI 192.168.180.1 as the gateway. SRV-DNS on "
            "192.168.180.50 is cabled to Gi0/2 and is the only resolver in the topology."
        ),
        concept="DNS",
        osi="L7",
        fault=(
            "SW-DEPOT Gi0/2, the access port serving SRV-DNS, is administratively down, so the "
            "correctly configured resolver is unreachable and every lookup times out."
        ),
        keywords=["dns unreachable", "gi0/2 shutdown", "192.168.180.50", "access port down"],
        rules=["R004", "R011"],
        fixes=[
            "On SW-DEPOT: interface GigabitEthernet0/2",
            "Bring the port up: no shutdown",
            "Confirm Gi0/2 is up/up in show ip interface brief",
            "Re-test: PC-USER ping 192.168.180.50, then nslookup srv-dns.lab",
        ],
        lab=lab,
        flows=[flow("PC-USER", "SRV-DNS", "dns", 53, note="Name resolution for depot clients")],
        extra=[
            ping("PC-USER", "192.168.180.50", ok=False, note="Request timed out."),
            ping("PC-USER", "192.168.180.1", ok=True),
        ],
    )


CASES = [case_016, case_017, case_018, case_019]
