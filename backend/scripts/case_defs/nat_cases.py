"""NAT cases (CASE-029 .. CASE-032)."""

from __future__ import annotations

from backend.scripts.case_builders import (
    ace,
    acl,
    build_case,
    capture,
    dev,
    flow,
    host,
    ifc,
    link,
    nat,
    ping,
    route,
    state,
)

_MASK = "255.255.255.0"
_P30 = "255.255.255.252"


def _nat_lab(inside_net: str, *, inside_side, outside_side, acls, nats) -> tuple:
    edge = dev(
        "R-NAT",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", f"{inside_net}.1", _MASK, nat=inside_side,
                description="INSIDE LAN"),
            ifc("GigabitEthernet0/1", "203.0.113.2", _P30, nat=outside_side,
                description="TO ISP"),
        ],
        routes=[route("0.0.0.0", "0.0.0.0", "203.0.113.1")],
        acls=acls,
        nats=nats,
    )
    isp = dev(
        "R-ISP",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "203.0.113.1", _P30, description="TO CUSTOMER"),
            ifc("GigabitEthernet0/1", "198.51.100.1", _MASK, description="HOSTING LAN"),
        ],
        routes=[route("0.0.0.0", "0.0.0.0", "203.0.113.2")],
    )
    hosts = [
        host("PC-INSIDE", f"{inside_net}.20", _MASK, f"{inside_net}.1", on="R-NAT",
             port="GigabitEthernet0/0"),
        host("SRV-PUBLIC", "198.51.100.10", _MASK, "198.51.100.1", on="R-ISP",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-INSIDE", "FastEthernet0", "R-NAT", "GigabitEthernet0/0"),
        link("SRV-PUBLIC", "FastEthernet0", "R-ISP", "GigabitEthernet0/1"),
        link("R-NAT", "GigabitEthernet0/1", "R-ISP", "GigabitEthernet0/0", mode="routed"),
    ]
    return state([edge, isp], hosts, links)


def _nat_acl(name: str, network: str) -> object:
    return acl(name, ace(10, "permit", "ip", network, "0.0.0.255"))


def case_029() -> dict:
    lab = _nat_lab(
        "192.168.240",
        inside_side="inside",
        outside_side=None,
        acls=[_nat_acl("NAT-INSIDE", "192.168.240.0")],
        nats=[nat("overload", acl_name="NAT-INSIDE", out_interface="GigabitEthernet0/1")],
    )
    return build_case(
        "CASE-029",
        title="Inside hosts cannot reach the internet because no NAT outside interface is marked",
        severity="High",
        symptom=(
            "PC-INSIDE reaches the ISP link address but nothing beyond it. show ip nat "
            "translations is empty and the translation counters never increase, even though "
            "the overload rule and its access list are present."
        ),
        topology_note=(
            "Internet edge lab (simulated). R-NAT Gi0/0 = 192.168.240.1/24 is the inside LAN "
            "and Gi0/1 = 203.0.113.2/30 faces the ISP. Inside hosts must be translated to the "
            "Gi0/1 address by an overload rule. NAT requires ip nat inside on the inside "
            "interface and ip nat outside on the outside interface."
        ),
        concept="NAT",
        osi="L3",
        fault=(
            "Gi0/1 is missing ip nat outside, so R-NAT has an inside interface but no outside "
            "interface and performs no translation at all."
        ),
        keywords=["ip nat outside missing", "gi0/1", "overload", "no translations"],
        rules=["R013"],
        fixes=[
            "On R-NAT: interface GigabitEthernet0/1",
            "Mark the outside interface: ip nat outside",
            "Confirm both sides appear in show ip nat statistics",
            "Re-test: PC-INSIDE ping 198.51.100.10 and confirm a translation is created",
        ],
        lab=lab,
        flows=[flow("PC-INSIDE", "SRV-PUBLIC", "tcp", 443, note="Inside users to a public site")],
        extra=[
            ping("PC-INSIDE", "203.0.113.1", ok=True),
            ping("PC-INSIDE", "198.51.100.10", ok=False, note="Request timed out."),
            capture("R-NAT", "show ip nat translations",
                    "! the translation table is empty"),
        ],
    )


def case_030() -> dict:
    lab = _nat_lab(
        "192.168.241",
        inside_side="inside",
        outside_side="outside",
        acls=[_nat_acl("NAT_INSIDE", "192.168.241.0")],
        nats=[nat("overload", acl_name="NAT-INSIDE", out_interface="GigabitEthernet0/1")],
    )
    return build_case(
        "CASE-030",
        title="NAT rule references an access list that does not exist on the router",
        severity="High",
        symptom=(
            "Inside hosts get no internet access. Both NAT interfaces are marked correctly and "
            "an overload rule is configured, but no traffic is ever matched for translation."
        ),
        topology_note=(
            "Internet edge lab (simulated). R-NAT Gi0/0 = 192.168.241.1/24 is the inside LAN "
            "(ip nat inside) and Gi0/1 = 203.0.113.2/30 faces the ISP (ip nat outside). The "
            "overload rule selects the traffic to translate by access list name; the access "
            "list that exists on the router is called NAT_INSIDE."
        ),
        concept="NAT",
        osi="L3",
        fault=(
            "The NAT rule matches access list NAT-INSIDE, but the router only has NAT_INSIDE "
            "(underscore), so the rule selects no traffic and nothing is translated."
        ),
        keywords=["nat acl missing", "NAT-INSIDE", "NAT_INSIDE", "name mismatch"],
        rules=["R013"],
        fixes=[
            "On R-NAT: no ip nat inside source list NAT-INSIDE interface "
            "GigabitEthernet0/1 overload",
            "Re-apply it with the existing list: ip nat inside source list NAT_INSIDE "
            "interface GigabitEthernet0/1 overload",
            "Confirm the dynamic mapping in show ip nat statistics",
            "Re-test: PC-INSIDE ping 198.51.100.10",
        ],
        lab=lab,
        flows=[flow("PC-INSIDE", "SRV-PUBLIC", "tcp", 443, note="Inside users to a public site")],
        extra=[
            capture("R-NAT", "show running-config | include ip nat inside source",
                    "ip nat inside source list NAT-INSIDE interface GigabitEthernet0/1 "
                    "overload\n! the referenced list NAT-INSIDE is not defined; the router "
                    "only has NAT_INSIDE"),
            ping("PC-INSIDE", "198.51.100.10", ok=False, note="Request timed out."),
        ],
    )


def case_031() -> dict:
    lab = _nat_lab(
        "192.168.242",
        inside_side="inside",
        outside_side="outside",
        acls=[_nat_acl("NAT-INSIDE", "192.168.242.0")],
        nats=[nat("dynamic", acl_name="NAT-INSIDE")],
    )
    return build_case(
        "CASE-031",
        title="Dynamic NAT rule has neither a pool nor an overload interface",
        severity="High",
        symptom=(
            "Internet access fails for all inside hosts. The NAT interfaces and the access "
            "list are correct, but show ip nat statistics lists a dynamic mapping with no pool "
            "and no interface to translate to."
        ),
        topology_note=(
            "Internet edge lab (simulated). R-NAT Gi0/0 = 192.168.242.1/24 is the inside LAN "
            "(ip nat inside) and Gi0/1 = 203.0.113.2/30 faces the ISP (ip nat outside). This "
            "site has a single public address, so inside hosts must be translated with "
            "interface overload rather than an address pool."
        ),
        concept="NAT",
        osi="L3",
        fault=(
            "The dynamic NAT rule names access list NAT-INSIDE but specifies neither an "
            "address pool nor an overload interface, so there is no outside address to "
            "translate inside hosts to."
        ),
        keywords=["missing overload", "dynamic nat", "no pool", "NAT-INSIDE"],
        rules=["R013"],
        fixes=[
            "On R-NAT: no ip nat inside source list NAT-INSIDE",
            "Add the overload form: ip nat inside source list NAT-INSIDE interface "
            "GigabitEthernet0/1 overload",
            "Confirm the mapping shows the outside interface in show ip nat statistics",
            "Re-test: PC-INSIDE ping 198.51.100.10 and confirm a translation appears",
        ],
        lab=lab,
        flows=[flow("PC-INSIDE", "SRV-PUBLIC", "tcp", 443, note="Inside users to a public site")],
        extra=[
            ping("PC-INSIDE", "198.51.100.10", ok=False, note="Request timed out."),
        ],
    )


def case_032() -> dict:
    lab = _nat_lab(
        "192.168.243",
        inside_side="inside",
        outside_side="outside",
        acls=[_nat_acl("NAT-INSIDE", "192.168.24.0")],
        nats=[nat("overload", acl_name="NAT-INSIDE", out_interface="GigabitEthernet0/1")],
    )
    return build_case(
        "CASE-032",
        title="NAT access list selects an inside network that does not exist at this site",
        severity="High",
        symptom=(
            "No inside host is ever translated. The NAT interfaces, the rule and the access "
            "list are all present, and the access list even permits a 192.168 network — but it "
            "is not the network the inside hosts are on."
        ),
        topology_note=(
            "Internet edge lab (simulated). R-NAT Gi0/0 = 192.168.243.1/24 is the inside LAN "
            "(ip nat inside) and Gi0/1 = 203.0.113.2/30 faces the ISP (ip nat outside). The "
            "NAT access list must match the inside network 192.168.243.0/24."
        ),
        concept="NAT",
        osi="L3",
        fault=(
            "Access list NAT-INSIDE permits 192.168.24.0/24, which is not on any inside "
            "interface (the inside LAN is 192.168.243.0/24), so no inside traffic matches the "
            "translation rule."
        ),
        keywords=["wrong inside network", "192.168.24.0", "192.168.243.0/24", "NAT-INSIDE"],
        rules=["R013"],
        fixes=[
            "On R-NAT: ip access-list extended NAT-INSIDE",
            "Remove the wrong entry: no 10",
            "Add the correct inside network: 10 permit ip 192.168.243.0 0.0.0.255 any",
            "Confirm the entry in show ip access-lists NAT-INSIDE",
            "Re-test: PC-INSIDE ping 198.51.100.10 and confirm a translation is created",
        ],
        lab=lab,
        flows=[flow("PC-INSIDE", "SRV-PUBLIC", "tcp", 443, note="Inside users to a public site")],
        extra=[
            ping("PC-INSIDE", "198.51.100.10", ok=False,
                 note="Request timed out (no translation is created)."),
        ],
    )


CASES = [case_029, case_030, case_031, case_032]
