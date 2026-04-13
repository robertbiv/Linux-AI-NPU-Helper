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


def _register_file_tools(registry: ToolRegistry, cfg: dict) -> None:
    from src.tools.find_files      import FindFilesTool
    from src.tools.search_in_files import SearchInFilesTool

    default_path   = cfg.get("search_path", str(Path.home()))
    blocked_paths: list[str] = cfg.get("blocked_paths", [])

    registry.register_lazy(
        name=FindFilesTool.name,
        description=FindFilesTool.description,
        schema=FindFilesTool.parameters_schema,
        factory=lambda: FindFilesTool(default_search_path=default_path),
    )
    registry.register_lazy(
        name=SearchInFilesTool.name,
        description=SearchInFilesTool.description,
        schema=SearchInFilesTool.parameters_schema,
        factory=lambda: SearchInFilesTool(
            default_search_path=default_path,
            blocked_paths=blocked_paths,
        ),
    )


def _register_web_tools(registry: ToolRegistry, cfg: dict) -> None:
    from src.tools.web_search      import WebSearchTool
    from src.tools.web_fetch       import WebFetchTool

    web_cfg        = cfg.get("web_search", {})
    default_engine = web_cfg.get("engine", "duckduckgo")
    extra_engines: dict[str, str] = web_cfg.get("engines", {})

    fetch_cfg      = cfg.get("web_fetch", {})
    fetch_enabled  = bool(fetch_cfg.get("enabled", False))

    registry.register_lazy(
        name=WebSearchTool.name,
        description=WebSearchTool.description,
        schema=WebSearchTool.parameters_schema,
        factory=lambda: WebSearchTool(
            default_engine=default_engine,
            engines=extra_engines,
        ),
    )
    if fetch_enabled:
        registry.register_lazy(
            name=WebFetchTool.name,
            description=WebFetchTool.description,
            schema=WebFetchTool.parameters_schema,
            factory=lambda: WebFetchTool(
                max_response_chars=int(fetch_cfg.get("max_response_chars", 8_000)),
                allowed_content_types=fetch_cfg.get("allowed_content_types"),
                domain_allowlist=fetch_cfg.get("domain_allowlist"),
                domain_blocklist=fetch_cfg.get("domain_blocklist"),
                max_redirects=int(fetch_cfg.get("max_redirects", 5)),
                connect_timeout=float(fetch_cfg.get("connect_timeout", 5.0)),
                read_timeout=float(fetch_cfg.get("read_timeout", 15.0)),
            ),
        )


def _register_system_tools(registry: ToolRegistry, cfg: dict, global_unload: bool) -> None:
    from src.tools.man_reader      import ManPageTool
    from src.tools.system_control  import SystemControlTool
    from src.tools.system_info     import SystemInfoTool
    from src.tools.process_info    import ProcessInfoTool

    man_cfg        = cfg.get("man_reader", {})
    man_enabled    = bool(man_cfg.get("enabled", True))
    man_max_chars  = int(man_cfg.get("max_chars", 8_000))
    man_sections   = man_cfg.get("default_sections", ["SYNOPSIS", "OPTIONS", "EXAMPLES"])
    man_unload     = bool(man_cfg.get("unload_after_use", True))

    sc_cfg         = cfg.get("system_control", {})
    sc_enabled     = bool(sc_cfg.get("enabled", True))
    sc_unload      = bool(sc_cfg.get("unload_after_use", global_unload))

    si_cfg         = cfg.get("system_info", {})
    si_enabled     = bool(si_cfg.get("enabled", True))
    si_unload      = bool(si_cfg.get("unload_after_use", global_unload))

    pi_cfg         = cfg.get("process_info", {})
    pi_enabled     = bool(pi_cfg.get("enabled", True))
    pi_unload      = bool(pi_cfg.get("unload_after_use", global_unload))

    if man_enabled:
        registry.register_lazy(
            name=ManPageTool.name,
            description=ManPageTool.description,
            schema=ManPageTool.parameters_schema,
            factory=lambda: ManPageTool(
                max_chars=man_max_chars,
                default_sections=man_sections,
            ),
            unload_after_use=man_unload,
        )
    if sc_enabled:
        registry.register_lazy(
            name=SystemControlTool.name,
            description=SystemControlTool.description,
            schema=SystemControlTool.parameters_schema,
            factory=SystemControlTool,
            unload_after_use=sc_unload,
        )
    if si_enabled:
        registry.register_lazy(
            name=SystemInfoTool.name,
            description=SystemInfoTool.description,
            schema=SystemInfoTool.parameters_schema,
            factory=SystemInfoTool,
            unload_after_use=si_unload,
        )
    if pi_enabled:
        registry.register_lazy(
            name=ProcessInfoTool.name,
            description=ProcessInfoTool.description,
            schema=ProcessInfoTool.parameters_schema,
            factory=ProcessInfoTool,
            unload_after_use=pi_unload,
        )


def _register_app_tools(registry: ToolRegistry, cfg: dict, global_unload: bool) -> None:
    from src.tools.app             import AppTool
    from src.tools.installed_apps  import InstalledAppsTool

    app_cfg        = cfg.get("app", {})
    app_enabled    = bool(app_cfg.get("enabled", True))
    app_unload     = bool(app_cfg.get("unload_after_use", global_unload))

    ia_cfg         = cfg.get("installed_apps", {})
    ia_enabled     = bool(ia_cfg.get("enabled", True))
    ia_unload      = bool(ia_cfg.get("unload_after_use", global_unload))

    if app_enabled:
        registry.register_lazy(
            name=AppTool.name,
            description=AppTool.description,
            schema=AppTool.parameters_schema,
            factory=AppTool,
            unload_after_use=app_unload,
        )
    if ia_enabled:
        registry.register_lazy(
            name=InstalledAppsTool.name,
            description=InstalledAppsTool.description,
            schema=InstalledAppsTool.parameters_schema,
            factory=InstalledAppsTool,
            unload_after_use=ia_unload,
        )


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
