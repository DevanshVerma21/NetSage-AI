"""Wireless cases (CASE-033 .. CASE-036)."""

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
    ssid,
    state,
    vlan,
)

_MASK = "255.255.255.0"


def _wifi_lab(*, ap_name, ssids, ap_vlans, client, uplink_down=False, extra_hosts=(),
              sw_vlans, sw_ifaces):
    admin = "shutdown" if uplink_down else "up"
    oper = "down" if uplink_down else "up"
    allowed = tuple(sorted(ap_vlans))
    ap = dev(
        ap_name,
        kind="access_point",
        routing=False,
        ifaces=[
            ifc("GigabitEthernet0/1", mode="trunk", allowed=allowed, native=1,
                admin=admin, oper=oper, description="UPLINK TO SW-WIFI"),
            ifc("Dot11Radio0", description="WIRELESS RADIO"),
        ],
        vlans=[vlan(v, f"WLAN{v}") for v in allowed],
        ssids=ssids,
    )
    sw = dev(
        "SW-WIFI",
        ifaces=[
            *sw_ifaces,
            ifc("GigabitEthernet0/24", mode="trunk", allowed=allowed, native=1,
                description=f"UPLINK TO {ap_name}"),
        ],
        vlans=sw_vlans,
    )
    hosts = [client, *extra_hosts]
    links = [
        link(ap_name, "GigabitEthernet0/1", "SW-WIFI", "GigabitEthernet0/24", mode="trunk",
             allowed=allowed, native=1),
    ]
    for extra in extra_hosts:
        if extra.connected_device and extra.connected_interface:
            links.append(
                link(extra.name, "FastEthernet0", extra.connected_device,
                     extra.connected_interface, vlan_id=extra.vlan)
            )
    return state([ap, sw], hosts, links)


def case_033() -> dict:
    lab = _wifi_lab(
        ap_name="AP-GUEST",
        ssids=[ssid("GUEST-WIFI", 50, guest=True, security="wpa2-psk")],
        ap_vlans=(20, 50),
        sw_vlans=[vlan(1, "default"), vlan(20, "INTERNAL"), vlan(50, "GUEST")],
        sw_ifaces=[
            ifc("GigabitEthernet0/1", vlan=20, mode="access", description="SRV-HR"),
            ifc("Vlan20", "192.168.20.1", _MASK, vlan=20),
            ifc("Vlan50", "192.168.50.1", _MASK, vlan=50),
        ],
        client=host("PC-GUEST", "192.168.50.30", _MASK, "192.168.50.1", vlan_id=50,
                    on="AP-GUEST", port="Dot11Radio0", wifi="GUEST-WIFI"),
        extra_hosts=[
            host("SRV-HR", "192.168.20.10", _MASK, "192.168.20.1", vlan_id=20, on="SW-WIFI",
                 port="GigabitEthernet0/1"),
        ],
    )
    return build_case(
        "CASE-033",
        title="Guest wireless clients can reach the internal HR server",
        severity="Critical",
        symptom=(
            "A laptop associated to the guest SSID browsed straight to the internal HR server "
            "and opened it. Guests receive addresses in the guest VLAN as designed, but nothing "
            "stops their traffic from being routed into the internal VLAN."
        ),
        topology_note=(
            "Wireless lab (simulated). AP-GUEST broadcasts the guest SSID GUEST-WIFI mapped to "
            "VLAN 50 and trunks VLANs 20 and 50 to SW-WIFI, which routes between VLAN 20 "
            "INTERNAL = 192.168.20.0/24 and VLAN 50 GUEST = 192.168.50.0/24. Policy: guest "
            "clients must never reach the internal VLAN, which requires client isolation or an "
            "isolation access list on the guest SSID."
        ),
        concept="WIRELESS",
        osi="L2",
        security_relevant=True,
        fault=(
            "The guest SSID GUEST-WIFI has no client isolation and no isolation access list, "
            "so guest traffic is routed into the internal VLAN exactly like staff traffic."
        ),
        keywords=["guest isolation", "GUEST-WIFI", "no isolation acl", "internal vlan"],
        rules=["R014"],
        fixes=[
            "Agree the guest policy with the security owner before changing the SSID",
            "On AP-GUEST, apply client isolation to the SSID GUEST-WIFI",
            "On SW-WIFI, create an isolation access list that denies 192.168.50.0/24 to "
            "192.168.20.0/24 and permits the rest, then apply it inbound on Vlan50",
            "Confirm the isolation configuration in show wlan summary and show ip access-lists",
            "Re-test: PC-GUEST must fail to reach 192.168.20.10 and still reach its gateway",
        ],
        lab=lab,
        flows=[
            flow("PC-GUEST", "SRV-HR", "tcp", 443, expect="deny",
                 note="Guest wireless must never reach the internal HR server"),
        ],
        extra=[
            ping("PC-GUEST", "192.168.20.10", ok=True,
                 note="This traffic is supposed to be denied."),
        ],
    )


def case_034() -> dict:
    lab = _wifi_lab(
        ap_name="AP-SALES",
        ssids=[ssid("CORP_WIFI", 60, security="wpa2-ent")],
        ap_vlans=(60,),
        sw_vlans=[vlan(1, "default"), vlan(60, "CORP-WIRELESS")],
        sw_ifaces=[
            ifc("GigabitEthernet0/1", vlan=60, mode="access", description="SRV-CORP"),
            ifc("Vlan60", "192.168.60.1", _MASK, vlan=60),
        ],
        client=host("PC-SALES", "192.168.60.30", _MASK, "192.168.60.1", vlan_id=60,
                    on="AP-SALES", port="Dot11Radio0", wifi="CORP-WIFI"),
        extra_hosts=[
            host("SRV-CORP", "192.168.60.10", _MASK, "192.168.60.1", vlan_id=60, on="SW-WIFI",
                 port="GigabitEthernet0/1"),
        ],
    )
    return build_case(
        "CASE-034",
        title="Re-imaged laptop never associates because its SSID name does not exist",
        severity="High",
        symptom=(
            "PC-SALES shows no wireless association at all: it keeps searching for the network "
            "CORP-WIFI. Other laptops in the same office associate normally and the access "
            "point reports no failed authentication attempts."
        ),
        topology_note=(
            "Wireless lab (simulated). AP-SALES broadcasts a single corporate SSID mapped to "
            "VLAN 60 CORP-WIRELESS = 192.168.60.0/24, whose gateway is the Vlan60 SVI "
            "192.168.60.1 on SW-WIFI. The SSID broadcast by the access point is the only one in "
            "the topology."
        ),
        concept="WIRELESS",
        osi="L2",
        fault=(
            "PC-SALES is configured for the SSID CORP-WIFI while the access point broadcasts "
            "CORP_WIFI (underscore), so the client never associates and its wireless adapter "
            "stays unassociated."
        ),
        keywords=["wrong ssid", "CORP-WIFI", "CORP_WIFI", "never associates"],
        rules=["R014"],
        fixes=[
            "On PC-SALES, remove the CORP-WIFI wireless profile",
            "Join the broadcast SSID CORP_WIFI with the WPA2-Enterprise credentials",
            "Confirm the client appears in show wlan summary on AP-SALES",
            "Re-test: PC-SALES ping 192.168.60.1",
        ],
        lab=lab,
        flows=[flow("PC-SALES", "SRV-CORP", note="Sales laptops to the corporate share")],
        extra=[
            capture("PC-SALES", "netsh wlan show interfaces",
                    "    Name       : Wireless0\n    State      : disconnected\n"
                    "    Profile    : CORP-WIFI\n    Reason     : the network was not found"),
        ],
    )


def case_035() -> dict:
    lab = _wifi_lab(
        ap_name="AP-ENG",
        ssids=[ssid("ENG-WIFI", 60, security="wpa2-psk")],
        ap_vlans=(60, 70),
        sw_vlans=[vlan(1, "default"), vlan(60, "GENERAL"), vlan(70, "ENGINEERING")],
        sw_ifaces=[
            ifc("GigabitEthernet0/1", vlan=70, mode="access", description="SRV-CAD"),
            ifc("Vlan60", "192.168.60.1", _MASK, vlan=60),
            ifc("Vlan70", "192.168.70.1", _MASK, vlan=70),
        ],
        client=host("PC-ENG", "192.168.70.30", _MASK, "192.168.70.1", vlan_id=70,
                    on="AP-ENG", port="Dot11Radio0", wifi="ENG-WIFI"),
        extra_hosts=[
            host("SRV-CAD", "192.168.70.10", _MASK, "192.168.70.1", vlan_id=70, on="SW-WIFI",
                 port="GigabitEthernet0/1"),
        ],
    )
    return build_case(
        "CASE-035",
        title="Engineering wireless clients associate but land in the wrong VLAN",
        severity="High",
        symptom=(
            "PC-ENG associates to ENG-WIFI and shows full signal, but it never reaches its "
            "gateway 192.168.70.1 and cannot open the CAD server. A capture on the trunk shows "
            "its frames tagged with VLAN 60."
        ),
        topology_note=(
            "Wireless lab (simulated). AP-ENG trunks VLANs 60 and 70 to SW-WIFI, which routes "
            "between VLAN 60 GENERAL = 192.168.60.0/24 and VLAN 70 ENGINEERING = "
            "192.168.70.0/24. Engineering wireless clients are addressed in 192.168.70.0/24, so "
            "the ENG-WIFI SSID must be mapped to VLAN 70."
        ),
        concept="WIRELESS",
        osi="L2",
        fault=(
            "The SSID ENG-WIFI is mapped to VLAN 60 while its clients are members of VLAN 70, "
            "so associated clients are bridged into the wrong subnet and never reach their "
            "gateway."
        ),
        keywords=["ssid vlan mapping", "ENG-WIFI", "vlan 60", "vlan 70"],
        rules=["R014"],
        fixes=[
            "On AP-ENG, map the SSID ENG-WIFI to VLAN 70",
            "Confirm the mapping in show wlan summary",
            "Confirm VLAN 70 is allowed on the AP uplink trunk",
            "Re-test: PC-ENG ping 192.168.70.1, then reach 192.168.70.10",
        ],
        lab=lab,
        flows=[flow("PC-ENG", "SRV-CAD", "tcp", 445, note="Engineering laptops to the CAD share")],
        extra=[
            ping("PC-ENG", "192.168.70.1", ok=False, note="Request timed out."),
        ],
    )


def case_036() -> dict:
    lab = _wifi_lab(
        ap_name="AP-WARE",
        ssids=[ssid("WARE-WIFI", 80, security="wpa2-psk")],
        ap_vlans=(80,),
        uplink_down=True,
        sw_vlans=[vlan(1, "default"), vlan(80, "WAREHOUSE")],
        sw_ifaces=[
            ifc("GigabitEthernet0/1", vlan=80, mode="access", description="SRV-WMS"),
            ifc("Vlan80", "192.168.80.1", _MASK, vlan=80),
        ],
        client=host("PC-SCAN", "192.168.80.30", _MASK, "192.168.80.1", vlan_id=80,
                    on="AP-WARE", port="Dot11Radio0", wifi="WARE-WIFI"),
        extra_hosts=[
            host("SRV-WMS", "192.168.80.10", _MASK, "192.168.80.1", vlan_id=80, on="SW-WIFI",
                 port="GigabitEthernet0/1"),
        ],
    )
    return build_case(
        "CASE-036",
        title="Warehouse scanners associate to the access point but reach nothing behind it",
        severity="Critical",
        symptom=(
            "Every handheld scanner shows a good wireless connection to WARE-WIFI, yet none can "
            "reach the warehouse management server or its gateway. Wired hosts in the same VLAN "
            "work normally."
        ),
        topology_note=(
            "Wireless lab (simulated). AP-WARE broadcasts WARE-WIFI mapped to VLAN 80 "
            "WAREHOUSE = 192.168.80.0/24 and reaches the rest of the network only through its "
            "single uplink Gi0/1 to SW-WIFI Gi0/24. SW-WIFI holds the Vlan80 SVI 192.168.80.1."
        ),
        concept="WIRELESS",
        osi="L2",
        fault=(
            "AP-WARE's only uplink Gi0/1 is administratively down, so associated clients can "
            "talk to the access point but no traffic leaves it toward the VLAN 80 gateway."
        ),
        keywords=["ap uplink down", "gi0/1 shutdown", "AP-WARE", "clients associate"],
        rules=["R004", "R014"],
        fixes=[
            "On AP-WARE: interface GigabitEthernet0/1",
            "Bring the uplink up: no shutdown",
            "Confirm Gi0/1 is up/up and trunking VLAN 80",
            "Re-test: PC-SCAN ping 192.168.80.1, then reach 192.168.80.10",
        ],
        lab=lab,
        flows=[flow("PC-SCAN", "SRV-WMS", "tcp", 443, note="Scanners to the warehouse system")],
        extra=[
            ping("PC-SCAN", "192.168.80.1", ok=False, note="Request timed out."),
            ping("SRV-WMS", "192.168.80.1", ok=True),
        ],
    )


CASES = [case_033, case_034, case_035, case_036]
