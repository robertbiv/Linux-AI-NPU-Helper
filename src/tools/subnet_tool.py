# SPDX-License-Identifier: GPL-3.0-or-later
"""Subnet tool — IP subnet calculations."""

import ipaddress
import logging
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


class SubnetTool(Tool):
    """Calculate IP subnet details."""

    name = "subnet_calc"
    description = "Calculate details for an IPv4 or IPv6 subnet (network address, broadcast, host range)."
    parameters_schema = {
        "type": "object",
        "properties": {
            "network": {
                "type": "string",
                "description": "The IP network with CIDR notation (e.g., '192.168.1.0/24' or '10.0.0.1/255.255.255.0').",
            },
        },
        "required": ["network"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        network_str = args.get("network", "").strip()

        if not network_str:
            return ToolResult(tool_name=self.name, error="'network' is required.")

        try:
            # strict=False allows host IPs with a netmask, e.g. 192.168.1.5/24
            net = ipaddress.ip_network(network_str, strict=False)

            lines = [
                f"Network: {net.network_address}/{net.prefixlen}",
                f"Netmask: {net.netmask}",
                f"Total Hosts: {net.num_addresses}",
            ]

            if net.version == 4:
                lines.append(f"Broadcast: {net.broadcast_address}")
                # Get usable host range
                hosts = list(net.hosts())
                if hosts:
                    lines.append(f"Host Range: {hosts[0]} - {hosts[-1]}")
                else:
                    lines.append("Host Range: N/A (Point-to-Point or /32)")
            else:
                # IPv6 has no specific broadcast address concept like IPv4
                # Usable hosts are practically the same as all addresses
                lines.append(f"First IP: {net[0]}")
                lines.append(f"Last IP: {net[-1]}")

            snippet = "\n".join(lines)
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path="subnet", snippet=snippet)],
            )
        except ValueError as exc:
            logger.debug("SubnetTool error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Invalid network definition: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SubnetTool error: %s", exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Subnet calculation failed: {exc}",
            )
