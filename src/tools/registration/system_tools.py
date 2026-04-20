# SPDX-License-Identifier: GPL-3.0-or-later
"""System tool registration."""

from src.tools._base import ToolRegistry


def _register_system_tools(
    registry: ToolRegistry, cfg: dict, global_unload: bool
) -> None:
    from src.tools.man_reader import ManPageTool
    from src.tools.system_control import SystemControlTool
    from src.tools.system_info import SystemInfoTool
    from src.tools.process_info import ProcessInfoTool
    from src.tools.screenshot_tool import ScreenshotTool

    man_cfg = cfg.get("man_reader", {})
    man_enabled = bool(man_cfg.get("enabled", True))
    man_max_chars = int(man_cfg.get("max_chars", 8_000))
    man_sections = man_cfg.get("default_sections", ["SYNOPSIS", "OPTIONS", "EXAMPLES"])
    man_unload = bool(man_cfg.get("unload_after_use", True))

    sc_cfg = cfg.get("system_control", {})
    sc_enabled = bool(sc_cfg.get("enabled", True))
    sc_unload = bool(sc_cfg.get("unload_after_use", global_unload))

    si_cfg = cfg.get("system_info", {})
    si_enabled = bool(si_cfg.get("enabled", True))
    si_unload = bool(si_cfg.get("unload_after_use", global_unload))

    pi_cfg = cfg.get("process_info", {})
    pi_enabled = bool(pi_cfg.get("enabled", True))
    pi_unload = bool(pi_cfg.get("unload_after_use", global_unload))

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

    ss_cfg = cfg.get("screenshot", {})
    ss_enabled = bool(ss_cfg.get("enabled", True))
    ss_unload = bool(ss_cfg.get("unload_after_use", True))

    if ss_enabled:
        registry.register_lazy(
            name=ScreenshotTool.name,
            description=ScreenshotTool.description,
            schema=ScreenshotTool.parameters_schema,
            factory=ScreenshotTool,
            unload_after_use=ss_unload,
        )
