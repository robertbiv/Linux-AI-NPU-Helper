# SPDX-License-Identifier: GPL-3.0-or-later
"""File tool registration."""

from pathlib import Path
from src.tools._base import ToolRegistry


def _register_file_tools(registry: ToolRegistry, cfg: dict) -> None:
    from src.tools.find_files import FindFilesTool
    from src.tools.search_in_files import SearchInFilesTool

    default_path = cfg.get("search_path", str(Path.home()))
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
