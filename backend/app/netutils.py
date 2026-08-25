"""Pure IPv4 helpers used by the deterministic rule engine.

Kept free of any model imports so they can be unit tested in isolation. Every function
is total: malformed input returns ``None``/``False`` rather than raising, because the
rule engine must be able to *report* a bad mask as a finding instead of crashing on it.
"""

from __future__ import annotations

import ipaddress
from typing import Optional


def parse_ip(ip: str | None) -> Optional[ipaddress.IPv4Address]:
    """Parse a dotted-quad address, or return None if it is not a valid IPv4 address."""
    if not ip:
        return None
    try:
        return ipaddress.IPv4Address(ip.strip())
    except (ipaddress.AddressValueError, ValueError):
        return None


def is_valid_netmask(mask: str | None) -> bool:
    """True only for a contiguous IPv4 netmask such as 255.255.255.0.

    A non-contiguous mask like 255.255.0.255 is a real and reasonably common
    Packet Tracer typo, and it is exactly what rule R002 exists to catch.
    """
    if not mask:
        return False
    addr = parse_ip(mask)
    if addr is None:
        return False
    bits = int(addr)
    # A contiguous mask is a run of 1s followed by a run of 0s. Inverting it and
    # adding one must therefore yield a power of two (or zero for 255.255.255.255).
    inverted = bits ^ 0xFFFFFFFF
    return (inverted + 1) & inverted == 0


def mask_to_prefix(mask: str | None) -> Optional[int]:
    """Return the prefix length for a contiguous netmask, else None."""
    if not is_valid_netmask(mask):
        return None
    addr = parse_ip(mask)
    assert addr is not None  # guarded by is_valid_netmask
    return bin(int(addr)).count("1")


def prefix_to_mask(prefix: int) -> str:
    """Return the dotted-quad netmask for a prefix length."""
    if not 0 <= prefix <= 32:
        raise ValueError(f"prefix out of range: {prefix}")
    bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    return str(ipaddress.IPv4Address(bits))


def network_of(ip: str | None, mask: str | None) -> Optional[ipaddress.IPv4Network]:
    """The network an address belongs to, or None if either value is malformed."""
    addr = parse_ip(ip)
    prefix = mask_to_prefix(mask)
    if addr is None or prefix is None:
        return None
    try:
        return ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False)
    except ValueError:
        return None


def same_subnet(ip_a: str | None, ip_b: str | None, mask: str | None) -> Optional[bool]:
    """Whether two addresses share a subnet under one mask.

    Returns None when the comparison cannot be made (malformed input), which callers
    must treat as "unknown", never as "no".
    """
    net_a = network_of(ip_a, mask)
    addr_b = parse_ip(ip_b)
    if net_a is None or addr_b is None:
        return None
    return addr_b in net_a


def ip_in_network(ip: str | None, prefix: str | None, mask: str | None) -> Optional[bool]:
    """Whether an address falls inside the network described by prefix + mask."""
    net = network_of(prefix, mask)
    addr = parse_ip(ip)
    if net is None or addr is None:
        return None
    return addr in net


def is_host_usable(ip: str | None, mask: str | None) -> Optional[bool]:
    """Whether an address is a usable host address in its own subnet.

    False for the network address or the broadcast address of a subnet wider than /31.
    """
    net = network_of(ip, mask)
    addr = parse_ip(ip)
    if net is None or addr is None:
        return None
    if net.prefixlen >= 31:
        return True  # /31 and /32 have no network/broadcast convention to violate
    return addr != net.network_address and addr != net.broadcast_address
