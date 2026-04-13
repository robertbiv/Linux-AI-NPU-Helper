# SPDX-License-Identifier: GPL-3.0-or-later
"""Public API for the tools package.

Each tool lives in its own module inside this package.  Import from here:

    from src.tools import ToolRegistry, ToolResult, build_default_registry
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.tools._base import (
    Tool,
    ToolDescriptor,
    ToolPermissions,
    ToolRegistry,
    ToolResult,
    SearchResult,
)

from src.tools.registration.file_tools import _register_file_tools
from src.tools.registration.web_tools import _register_web_tools
from src.tools.registration.system_tools import _register_system_tools
from src.tools.registration.app_tools import _register_app_tools

# Re-export so callers can do `from src.tools import ToolRegistry` etc.
__all__ = [
    "Tool",
    "ToolDescriptor",
    "ToolPermissions",
    "ToolRegistry",
    "ToolResult",
    "SearchResult",
    "build_default_registry",
]


def build_default_registry(tools_config: dict | None = None) -> ToolRegistry:
    """Create a ToolRegistry with all built-in tools registered lazily.

    Each tool is imported and instantiated only on its first dispatch call.
    Adding a new tool: create src/tools/mytool.py with a Tool subclass,
    then add a register_lazy() call here.
    """
    cfg = tools_config or {}
    global_unload: bool = bool(cfg.get("unload_after_use", False))

    default_approval = ["web_search", "web_fetch", "system_control", "app"]
    permissions = ToolPermissions(
        allowed=cfg.get("allowed", []),
        disallowed=cfg.get("disallowed", []),
        requires_approval=cfg.get("requires_approval", default_approval),
    )

    registry = ToolRegistry(permissions=permissions, unload_after_use=global_unload)

    _register_file_tools(registry, cfg)
    _register_web_tools(registry, cfg)
    _register_system_tools(registry, cfg, global_unload)
    _register_app_tools(registry, cfg, global_unload)

    return registry
