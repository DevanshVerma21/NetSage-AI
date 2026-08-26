# Phase 5 coverage matrix

Generated from `data/cases.json` — 40 simulated-lab troubleshooting cases and the
deterministic rules each one is expected to fire. Every row is verified by
`tests/test_golden_expected_faults.py` (expected rule ids must match fired rule ids
exactly) and by `python -m backend.app.rules.cli --all --format table`.

| Case | Category | Severity | OSI | Expected rules | Expected root cause | Fix type |
| --- | --- | --- | --- | --- | --- | --- |
| CASE-001 | VLAN | High | L2 | R004, R005, R006 | VLAN 30, vlan database, not created | On SW1, create the missing VLAN: configure terminal / vlan 30 / name SERVERS / exit |
| CASE-002 | VLAN | High | L3 | R003, R006, R015 | missing svi, vlan 30, no gateway | On SW1, create the missing SVI: interface Vlan30 |
| CASE-003 | VLAN | High | L2 | R007 | wrong access vlan, gi0/2, vlan 10 | On SW1: interface GigabitEthernet0/2 |
| CASE-004 | VLAN | High | L2 | R008 | trunk, allowed vlan, vlan 20 pruned | On SW2: interface GigabitEthernet0/24 |
| CASE-005 | VLAN | Medium | L2 | R008 | native vlan mismatch, native vlan 99, trunk | On SW2: interface GigabitEthernet0/24 |
| CASE-006 | GATEWAY | High | L3 | R003 | wrong default gateway, 192.168.50.254, no first hop | On PC-ACC, set the default gateway to the documented router address 192.168.50.1 |
| CASE-007 | GATEWAY | High | L3 | R003 | gateway outside subnet, 192.168.7.1, 192.168.70.0/24 | On PC-BRANCH, correct the default gateway to 192.168.70.1 |
| CASE-008 | GATEWAY | High | L3 | R003 | missing default gateway, PC-LAB, static configuration | On PC-LAB, set the default gateway to 192.168.41.1 |
| CASE-009 | GATEWAY | High | L3 | R003 | gateway wrong device, 192.168.80.50, print server | On PC-FIN, set the default gateway to the router address 192.168.80.1 |
| CASE-010 | GATEWAY | Medium | L3 | R002 | subnet mask mismatch, 255.255.255.128, vlan 90 | On PC-SUP, set the subnet mask to 255.255.255.0 to match the Vlan90 SVI |
| CASE-011 | DHCP | High | L3 | R010 | dhcp pool network, 192.168.10.0, 192.168.100.0/24 | On SW-DHCP: ip dhcp pool STAFF-POOL |
| CASE-012 | DHCP | High | L3 | R003, R010 | default-router, 192.168.111.1, wrong gateway from dhcp | On R-CAMPUS: ip dhcp pool LAB-POOL |
| CASE-013 | DHCP | Critical | L3 | R001, R010 | excluded address, 192.168.12.1, duplicate ip | On SW-BR: no ip dhcp excluded-address 192.168.12.1 |
| CASE-014 | DHCP | High | L3 | R010 | ip helper-address, dhcp relay missing, vlan 130 | On SW-CAMP: interface Vlan130 |
| CASE-015 | DHCP | High | L3 | R010 | dhcp dns-server, 192.168.140.253, wrong dns handed out | On SW-RETAIL: ip dhcp pool TILL-POOL |
| CASE-016 | DNS | High | L7 | R011 | wrong dns server, 192.168.150.1, 192.168.150.50 | On PC-USER, set the DNS server to 192.168.150.50 |
| CASE-017 | DNS | High | L7 | R011 | unreachable dns, 10.10.10.53, stale configuration | On PC-USER, replace the DNS server with 192.168.160.50 |
| CASE-018 | DNS | High | L7 | R011 | no dns configured, empty resolver, PC-USER | On PC-USER, configure the DNS server 192.168.170.50 |
| CASE-019 | DNS | Critical | L7 | R004, R011 | dns unreachable, gi0/2 shutdown, 192.168.180.50 | On SW-DEPOT: interface GigabitEthernet0/2 |
| CASE-020 | ROUTING | High | L3 | R006 | missing route, 192.168.191.0/24, R-BR | On R-BR: ip route 192.168.191.0 255.255.255.0 10.0.0.2 |
| CASE-021 | ROUTING | High | L3 | R006 | wrong network in static route, 192.168.20.0, 192.168.201.0/24 | On R-BR: no ip route 192.168.20.0 255.255.255.0 10.0.0.2 |
| CASE-022 | ROUTING | Critical | L3 | R006 | ip routing disabled, inter-vlan routing, SW-L3 | On SW-L3, enter global configuration and run: ip routing |
| CASE-023 | ROUTING | Critical | L3 | R006 | missing default route, gateway of last resort, 203.0.113.1 | On R-EDGE: ip route 0.0.0.0 0.0.0.0 203.0.113.1 |
| CASE-024 | ROUTING | High | L3 | R009 | overlapping subnets, 255.255.0.0, 192.168.30.0/24 | On R-DC: interface GigabitEthernet0/1 |
| CASE-025 | ACL | High | L4 | R012 | acl deny, tcp 445, BLOCK-SMB | Confirm with the security owner that SMB to 192.168.231.10 is now permitted |
| CASE-026 | ACL | Critical | L4 | R012 | acl wrong interface, GUEST-FILTER, gi0/2 | On R-GW: interface GigabitEthernet0/2 |
| CASE-027 | ACL | High | L4 | R012 | wrong source address, 192.168.235.20, 192.168.235.21 | On R-APP: ip access-list extended PERMIT-DB |
| CASE-028 | ACL | High | L4 | R012 | implicit deny, tcp 8443, WEB-ONLY | On R-CAMPUS2: ip access-list extended WEB-ONLY |
| CASE-029 | NAT | High | L3 | R013 | ip nat outside missing, gi0/1, overload | On R-NAT: interface GigabitEthernet0/1 |
| CASE-030 | NAT | High | L3 | R013 | nat acl missing, NAT-INSIDE, NAT_INSIDE | On R-NAT: no ip nat inside source list NAT-INSIDE interface GigabitEthernet0/1 overload |
| CASE-031 | NAT | High | L3 | R013 | missing overload, dynamic nat, no pool | On R-NAT: no ip nat inside source list NAT-INSIDE |
| CASE-032 | NAT | High | L3 | R013 | wrong inside network, 192.168.24.0, 192.168.243.0/24 | On R-NAT: ip access-list extended NAT-INSIDE |
| CASE-033 | WIRELESS | Critical | L2 | R014 | guest isolation, GUEST-WIFI, no isolation acl | Agree the guest policy with the security owner before changing the SSID |
| CASE-034 | WIRELESS | High | L2 | R014 | wrong ssid, CORP-WIFI, CORP_WIFI | On PC-SALES, remove the CORP-WIFI wireless profile |
| CASE-035 | WIRELESS | High | L2 | R014 | ssid vlan mapping, ENG-WIFI, vlan 60 | On AP-ENG, map the SSID ENG-WIFI to VLAN 70 |
| CASE-036 | WIRELESS | Critical | L2 | R004, R014 | ap uplink down, gi0/1 shutdown, AP-WARE | On AP-WARE: interface GigabitEthernet0/1 |
| CASE-037 | INTERFACE_CONFIG | Critical | L1 | R004 | shutdown interface, gi0/1, administratively down | On R-WAN: interface GigabitEthernet0/1 |
| CASE-038 | INTERFACE_CONFIG | High | L1 | R004, R015 | line protocol down, vlan85 svi, svi down | On SW-FLOOR, confirm VLAN 85 is active in show vlan brief |
| CASE-039 | INTERFACE_CONFIG | High | L3 | R005, R015 | wrong interface, vlan87 svi, vlan 88 has no svi | On SW-OPS: no interface Vlan87 |
| CASE-040 | INTERFACE_CONFIG | High | L3 | R002 | invalid subnet mask, 255.255.0.255, vlan91 | On SW-ADMIN: interface Vlan91 |

## Category summary

| Category | Cases |
| --- | --- |
| ACL | 4 |
| DHCP | 5 |
| DNS | 4 |
| GATEWAY | 5 |
| INTERFACE_CONFIG | 4 |
| NAT | 4 |
| ROUTING | 5 |
| VLAN | 5 |
| WIRELESS | 4 |
| **total** | **40** |

## Severity summary

| Severity | Cases |
| --- | --- |
| Critical | 8 |
| High | 30 |
| Medium | 2 |

## OSI layer summary

| OSI layer | Cases |
| --- | --- |
| L1 | 2 |
| L2 | 8 |
| L3 | 22 |
| L4 | 4 |
| L7 | 4 |

## Rule coverage

| Rule | Cases expecting it |
| --- | --- |
| R001 | 1 |
| R002 | 2 |
| R003 | 6 |
| R004 | 5 |
| R005 | 2 |
| R006 | 6 |
| R007 | 1 |
| R008 | 2 |
| R009 | 1 |
| R010 | 5 |
| R011 | 4 |
| R012 | 4 |
| R013 | 4 |
| R014 | 4 |
| R015 | 3 |

Security-relevant cases: 5.
Every case carries `source_label: simulated-lab` — no Packet Tracer or real-device
execution is claimed.
