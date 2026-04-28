import pytest
from src.tools.subnet_tool import SubnetTool
from unittest.mock import patch

def test_subnet_tool_invalid_args():
    tool = SubnetTool()
    res = tool.run({})
    assert "'network' is required" in res.error

def test_subnet_tool_ipv4():
    tool = SubnetTool()
    res = tool.run({"network": "192.168.1.5/24"})
    assert "Network: 192.168.1.0/24" in res.results[0].snippet
    assert "Netmask: 255.255.255.0" in res.results[0].snippet
    assert "Broadcast: 192.168.1.255" in res.results[0].snippet
    assert "Host Range: 192.168.1.1 - 192.168.1.254" in res.results[0].snippet

def test_subnet_tool_ipv4_31():
    tool = SubnetTool()
    res = tool.run({"network": "192.168.1.0/31"})
    assert "Network: 192.168.1.0/31" in res.results[0].snippet
    assert "Host Range: 192.168.1.0 - 192.168.1.1" in res.results[0].snippet

def test_subnet_tool_ipv4_32():
    tool = SubnetTool()
    res = tool.run({"network": "192.168.1.5/32"})
    assert "Network: 192.168.1.5/32" in res.results[0].snippet
    assert "Host Range: 192.168.1.5 - 192.168.1.5" in res.results[0].snippet

def test_subnet_tool_ipv4_empty_hosts():
    tool = SubnetTool()
    import ipaddress
    with patch("ipaddress.ip_network") as mock_net:
        mock_instance = mock_net.return_value
        mock_instance.version = 4
        mock_instance.network_address = "192.168.1.1"
        mock_instance.prefixlen = 32
        mock_instance.netmask = "255.255.255.255"
        mock_instance.num_addresses = 1
        mock_instance.broadcast_address = "192.168.1.1"
        mock_instance.hosts.return_value = []
        res = tool.run({"network": "192.168.1.1/32"})
        assert "Host Range: N/A" in res.results[0].snippet

def test_subnet_tool_ipv6():
    tool = SubnetTool()
    res = tool.run({"network": "2001:db8::/120"})
    assert "Network: 2001:db8::/120" in res.results[0].snippet
    assert "First IP: 2001:db8::" in res.results[0].snippet

def test_subnet_tool_exceptions():
    tool = SubnetTool()

    # ValueError
    res = tool.run({"network": "invalid"})
    assert "Invalid network definition" in res.error

    # Generic
    with patch("ipaddress.ip_network", side_effect=Exception("Generic Error")):
        res = tool.run({"network": "1.2.3.4/24"})
        assert "Subnet calculation failed: Generic Error" in res.error
