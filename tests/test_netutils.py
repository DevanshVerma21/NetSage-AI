"""Tests for the pure IPv4 helpers the rule engine depends on."""

from __future__ import annotations

import pytest

from backend.app.netutils import (
    is_host_usable,
    is_valid_netmask,
    ip_in_network,
    mask_to_prefix,
    network_of,
    parse_ip,
    prefix_to_mask,
    same_subnet,
)


@pytest.mark.parametrize(
    "mask,expected",
    [
        ("255.255.255.0", True),
        ("255.255.255.255", True),
        ("255.255.254.0", True),
        ("0.0.0.0", True),
        ("255.255.0.255", False),  # non-contiguous — a real Packet Tracer typo
        ("255.0.255.0", False),
        ("255.255.255.1", False),
        ("999.1.1.1", False),
        ("", False),
        (None, False),
    ],
)
def test_is_valid_netmask(mask, expected):
    assert is_valid_netmask(mask) is expected


@pytest.mark.parametrize(
    "mask,prefix",
    [("255.255.255.0", 24), ("255.255.0.0", 16), ("255.255.255.252", 30), ("0.0.0.0", 0)],
)
def test_mask_to_prefix(mask, prefix):
    assert mask_to_prefix(mask) == prefix


def test_mask_to_prefix_rejects_invalid_mask():
    assert mask_to_prefix("255.255.0.255") is None


@pytest.mark.parametrize("prefix,mask", [(24, "255.255.255.0"), (30, "255.255.255.252"), (0, "0.0.0.0")])
def test_prefix_to_mask(prefix, mask):
    assert prefix_to_mask(prefix) == mask


def test_prefix_to_mask_rejects_out_of_range():
    with pytest.raises(ValueError):
        prefix_to_mask(33)


def test_network_of():
    net = network_of("192.168.20.15", "255.255.255.0")
    assert str(net) == "192.168.20.0/24"


def test_network_of_returns_none_on_bad_input():
    assert network_of("192.168.20.15", "255.255.0.255") is None
    assert network_of("not-an-ip", "255.255.255.0") is None


def test_same_subnet():
    assert same_subnet("192.168.20.15", "192.168.20.1", "255.255.255.0") is True
    assert same_subnet("192.168.20.15", "192.168.30.1", "255.255.255.0") is False


def test_same_subnet_returns_none_when_undecidable():
    """None means 'cannot evaluate' and callers must not treat it as False."""
    assert same_subnet("192.168.20.15", "192.168.20.1", "255.255.0.255") is None


def test_ip_in_network():
    assert ip_in_network("192.168.30.10", "192.168.30.0", "255.255.255.0") is True
    assert ip_in_network("192.168.40.10", "192.168.30.0", "255.255.255.0") is False
    # A default route covers everything.
    assert ip_in_network("8.8.8.8", "0.0.0.0", "0.0.0.0") is True


def test_is_host_usable():
    assert is_host_usable("192.168.20.15", "255.255.255.0") is True
    assert is_host_usable("192.168.20.0", "255.255.255.0") is False  # network address
    assert is_host_usable("192.168.20.255", "255.255.255.0") is False  # broadcast
    assert is_host_usable("10.0.0.1", "255.255.255.254") is True  # /31 has no broadcast


def test_parse_ip():
    assert str(parse_ip(" 192.168.1.1 ")) == "192.168.1.1"
    assert parse_ip("192.168.1.256") is None
    assert parse_ip(None) is None
