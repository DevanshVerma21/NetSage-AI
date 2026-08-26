"""ACL cases (CASE-025 .. CASE-028). Every fault is decided against a declared intended flow."""

from __future__ import annotations

from backend.scripts.case_builders import (
    ace,
    acl,
    bind,
    build_case,
    capture,
    dev,
    flow,
    host,
    ifc,
    link,
    ping,
    state,
)

_MASK = "255.255.255.0"


def case_025() -> dict:
    fw = dev(
        "R-FW",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.230.1", _MASK, description="USER LAN"),
            ifc("GigabitEthernet0/1", "192.168.231.1", _MASK, description="SERVER LAN"),
        ],
        acls=[
            acl(
                "BLOCK-SMB",
                ace(10, "deny", "tcp", "192.168.230.0", "0.0.0.255", "192.168.231.10",
                    port_op="eq", port=445),
                ace(20, "permit"),
            )
        ],
        bindings=[bind("BLOCK-SMB", "GigabitEthernet0/0", "in")],
    )
    hosts = [
        host("PC-USER", "192.168.230.20", _MASK, "192.168.230.1", on="R-FW",
             port="GigabitEthernet0/0"),
        host("SRV-FILE", "192.168.231.10", _MASK, "192.168.231.1", on="R-FW",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-USER", "FastEthernet0", "R-FW", "GigabitEthernet0/0"),
        link("SRV-FILE", "FastEthernet0", "R-FW", "GigabitEthernet0/1"),
    ]
    lab = state([fw], hosts, links)
    return build_case(
        "CASE-025",
        title="File share access is blocked by an access list left over from an incident",
        severity="High",
        symptom=(
            "PC-USER can ping SRV-FILE and reach it over HTTPS, but every attempt to open the "
            "SMB file share fails. The router increments deny counters on Gi0/0 whenever the "
            "share is opened."
        ),
        topology_note=(
            "Single router lab (simulated). R-FW Gi0/0 = 192.168.230.1/24 serves the user LAN "
            "and Gi0/1 = 192.168.231.1/24 serves the server LAN. Access list BLOCK-SMB is "
            "applied inbound on Gi0/0. Users are required to reach the file share on "
            "192.168.231.10 over TCP 445."
        ),
        concept="ACL",
        osi="L4",
        security_relevant=True,
        fault=(
            "BLOCK-SMB entry 10 explicitly denies tcp from 192.168.230.0/24 to host "
            "192.168.231.10 eq 445, so the required file-share flow is dropped inbound on "
            "Gi0/0."
        ),
        keywords=["acl deny", "tcp 445", "BLOCK-SMB", "gi0/0 inbound"],
        rules=["R012"],
        fixes=[
            "Confirm with the security owner that SMB to 192.168.231.10 is now permitted",
            "On R-FW: ip access-list extended BLOCK-SMB",
            "Remove the obsolete entry: no 10",
            "Confirm show ip access-lists no longer lists the deny for tcp eq 445",
            "Re-test: open the share on 192.168.231.10 from PC-USER",
        ],
        lab=lab,
        flows=[flow("PC-USER", "SRV-FILE", "tcp", 445, note="Departmental file share")],
        extra=[
            ping("PC-USER", "192.168.231.10", ok=True),
            capture("R-FW", "show ip access-lists BLOCK-SMB | include matches",
                    "    10 deny tcp 192.168.230.0 0.0.0.255 host 192.168.231.10 eq 445 "
                    "(148 matches)"),
        ],
    )


def case_026() -> dict:
    gw = dev(
        "R-GW",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.232.1", _MASK, description="GUEST LAN"),
            ifc("GigabitEthernet0/1", "192.168.233.1", _MASK, description="INTERNAL LAN"),
            ifc("GigabitEthernet0/2", "192.168.234.1", _MASK, description="DMZ"),
        ],
        acls=[
            acl(
                "GUEST-FILTER",
                ace(10, "deny", "ip", "192.168.232.0", "0.0.0.255", "192.168.233.0",
                    "0.0.0.255"),
                ace(20, "permit"),
            )
        ],
        bindings=[bind("GUEST-FILTER", "GigabitEthernet0/2", "in")],
    )
    hosts = [
        host("PC-GUEST", "192.168.232.30", _MASK, "192.168.232.1", on="R-GW",
             port="GigabitEthernet0/0"),
        host("SRV-HR", "192.168.233.10", _MASK, "192.168.233.1", on="R-GW",
             port="GigabitEthernet0/1"),
        host("SRV-WEB", "192.168.234.10", _MASK, "192.168.234.1", on="R-GW",
             port="GigabitEthernet0/2"),
    ]
    links = [
        link("PC-GUEST", "FastEthernet0", "R-GW", "GigabitEthernet0/0"),
        link("SRV-HR", "FastEthernet0", "R-GW", "GigabitEthernet0/1"),
        link("SRV-WEB", "FastEthernet0", "R-GW", "GigabitEthernet0/2"),
    ]
    lab = state([gw], hosts, links)
    return build_case(
        "CASE-026",
        title="Guest network can still reach HR because the filter sits on the wrong interface",
        severity="Critical",
        symptom=(
            "A guest laptop can open the HR server directly. The GUEST-FILTER access list "
            "exists and looks correct, but its counters never increment for guest traffic."
        ),
        topology_note=(
            "Single router lab (simulated). R-GW Gi0/0 = 192.168.232.1/24 serves the guest "
            "LAN, Gi0/1 = 192.168.233.1/24 the internal LAN, Gi0/2 = 192.168.234.1/24 the DMZ. "
            "Policy: guests may reach the DMZ web server but must never reach the internal "
            "LAN. The filter therefore has to be applied inbound on the guest interface Gi0/0."
        ),
        concept="ACL",
        osi="L4",
        security_relevant=True,
        fault=(
            "GUEST-FILTER is applied inbound on Gi0/2 (the DMZ), an interface guest traffic "
            "never enters, so nothing evaluates the deny and guest-to-internal traffic is "
            "forwarded."
        ),
        keywords=["acl wrong interface", "GUEST-FILTER", "gi0/2", "guest to internal"],
        rules=["R012"],
        fixes=[
            "On R-GW: interface GigabitEthernet0/2",
            "Remove the misplaced binding: no ip access-group GUEST-FILTER in",
            "On R-GW: interface GigabitEthernet0/0",
            "Apply the filter where guest traffic enters: ip access-group GUEST-FILTER in",
            "Confirm the binding in show running-config | include access-group",
            "Re-test: PC-GUEST must fail to reach 192.168.233.10 and still reach "
            "192.168.234.10",
        ],
        lab=lab,
        flows=[
            flow("PC-GUEST", "SRV-HR", "tcp", 443, expect="deny",
                 note="Guests must never reach the internal HR server"),
            flow("PC-GUEST", "SRV-WEB", "tcp", 443, note="Guests may use the DMZ web server"),
        ],
        extra=[
            ping("PC-GUEST", "192.168.233.10", ok=True,
                 note="This traffic is supposed to be denied."),
        ],
    )


def case_027() -> dict:
    r = dev(
        "R-APP",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.235.1", _MASK, description="HR LAN"),
            ifc("GigabitEthernet0/1", "192.168.236.1", _MASK, description="DB LAN"),
        ],
        acls=[
            acl(
                "PERMIT-DB",
                ace(10, "permit", "tcp", "192.168.235.20", None, "192.168.236.10",
                    port_op="eq", port=1433),
                ace(20, "deny"),
            )
        ],
        bindings=[bind("PERMIT-DB", "GigabitEthernet0/0", "in")],
    )
    hosts = [
        host("PC-HR", "192.168.235.21", _MASK, "192.168.235.1", on="R-APP",
             port="GigabitEthernet0/0"),
        host("SRV-DB", "192.168.236.10", _MASK, "192.168.236.1", on="R-APP",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-HR", "FastEthernet0", "R-APP", "GigabitEthernet0/0"),
        link("SRV-DB", "FastEthernet0", "R-APP", "GigabitEthernet0/1"),
    ]
    lab = state([r], hosts, links)
    return build_case(
        "CASE-027",
        title="Database access list permits the wrong host address",
        severity="High",
        symptom=(
            "The HR workstation cannot open the payroll database. The access list was written "
            "for this project and the permit entry looks right at a glance, but the deny "
            "counter at the end of the list increments on every attempt."
        ),
        topology_note=(
            "Single router lab (simulated). R-APP Gi0/0 = 192.168.235.1/24 serves the HR LAN "
            "and Gi0/1 = 192.168.236.1/24 the database LAN. Access list PERMIT-DB is applied "
            "inbound on Gi0/0 and must permit the HR workstation 192.168.235.21 to reach "
            "192.168.236.10 on TCP 1433."
        ),
        concept="ACL",
        osi="L4",
        security_relevant=True,
        fault=(
            "PERMIT-DB entry 10 permits host 192.168.235.20 instead of the actual workstation "
            "192.168.235.21, so the intended flow falls through to the explicit deny at entry "
            "20."
        ),
        keywords=["wrong source address", "192.168.235.20", "192.168.235.21", "PERMIT-DB"],
        rules=["R012"],
        fixes=[
            "On R-APP: ip access-list extended PERMIT-DB",
            "Remove the incorrect entry: no 10",
            "Add the correct one: 10 permit tcp host 192.168.235.21 host 192.168.236.10 eq 1433",
            "Confirm the entry in show ip access-lists PERMIT-DB",
            "Re-test: open the database from PC-HR",
        ],
        lab=lab,
        flows=[flow("PC-HR", "SRV-DB", "tcp", 1433, note="HR workstation to the payroll database")],
        extra=[
            ping("PC-HR", "192.168.236.10", ok=False, note="Request timed out."),
            capture("R-APP", "show ip access-lists PERMIT-DB | include matches",
                    "    20 deny ip any any (312 matches)"),
        ],
    )


def case_028() -> dict:
    r = dev(
        "R-CAMPUS2",
        kind="router",
        ifaces=[
            ifc("GigabitEthernet0/0", "192.168.237.1", _MASK, description="STUDENT LAN"),
            ifc("GigabitEthernet0/1", "192.168.238.1", _MASK, description="SERVICES LAN"),
        ],
        acls=[
            acl(
                "WEB-ONLY",
                ace(10, "permit", "tcp", "192.168.237.0", "0.0.0.255", port_op="eq", port=80),
                ace(20, "permit", "tcp", "192.168.237.0", "0.0.0.255", port_op="eq", port=443),
            )
        ],
        bindings=[bind("WEB-ONLY", "GigabitEthernet0/0", "in")],
    )
    hosts = [
        host("PC-STUDENT", "192.168.237.40", _MASK, "192.168.237.1", on="R-CAMPUS2",
             port="GigabitEthernet0/0"),
        host("SRV-EXAM", "192.168.238.10", _MASK, "192.168.238.1", on="R-CAMPUS2",
             port="GigabitEthernet0/1"),
    ]
    links = [
        link("PC-STUDENT", "FastEthernet0", "R-CAMPUS2", "GigabitEthernet0/0"),
        link("SRV-EXAM", "FastEthernet0", "R-CAMPUS2", "GigabitEthernet0/1"),
    ]
    lab = state([r], hosts, links)
    return build_case(
        "CASE-028",
        title="Exam application on TCP 8443 was never permitted by the student access list",
        severity="High",
        symptom=(
            "Students can browse normal web sites but the new exam client, which connects on "
            "TCP 8443, times out for everyone. Nothing in the access list mentions 8443 and "
            "there is no explicit deny entry to point at."
        ),
        topology_note=(
            "Campus router lab (simulated). R-CAMPUS2 Gi0/0 = 192.168.237.1/24 serves the "
            "student LAN and Gi0/1 = 192.168.238.1/24 the services LAN. Access list WEB-ONLY "
            "is applied inbound on Gi0/0. The exam service on 192.168.238.10 must be reachable "
            "on TCP 8443."
        ),
        concept="ACL",
        osi="L4",
        security_relevant=True,
        fault=(
            "WEB-ONLY permits only TCP 80 and TCP 443, so the required TCP 8443 flow matches no "
            "entry and is dropped by the implicit deny at the end of the list."
        ),
        keywords=["implicit deny", "tcp 8443", "WEB-ONLY", "traffic not permitted"],
        rules=["R012"],
        fixes=[
            "On R-CAMPUS2: ip access-list extended WEB-ONLY",
            "Permit the exam service: 30 permit tcp 192.168.237.0 0.0.0.255 host "
            "192.168.238.10 eq 8443",
            "Confirm the new entry in show ip access-lists WEB-ONLY",
            "Re-test: launch the exam client from PC-STUDENT",
        ],
        lab=lab,
        flows=[flow("PC-STUDENT", "SRV-EXAM", "tcp", 8443, note="Exam client to the exam service")],
        extra=[
            capture("PC-STUDENT", "telnet 192.168.238.10 8443",
                    "Trying 192.168.238.10...\n% Connection timed out; remote host not "
                    "responding"),
        ],
    )


CASES = [case_025, case_026, case_027, case_028]
