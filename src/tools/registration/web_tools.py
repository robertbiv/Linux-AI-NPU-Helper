# SPDX-License-Identifier: GPL-3.0-or-later
"""Web tool registration."""
from src.tools._base import ToolRegistry

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
