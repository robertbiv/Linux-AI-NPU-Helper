# SPDX-License-Identifier: GPL-3.0-or-later
"""App tool registration."""
from src.tools._base import ToolRegistry

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
