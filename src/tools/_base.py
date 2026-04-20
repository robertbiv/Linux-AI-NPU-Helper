# SPDX-License-Identifier: GPL-3.0-or-later
"""Base types and registry for the tools package."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """A single hit returned by a tool."""

    path: str
    """Absolute (or relative) path of the matching file."""

    line_number: int | None = None
    """Line number of the match inside the file (content searches only)."""

    snippet: str = ""
    """Matching text excerpt (content searches only)."""

    score: float = 0.0
    """Optional relevance score (higher = more relevant)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line_number": self.line_number,
            "snippet": self.snippet,
            "score": self.score,
        }

    def __str__(self) -> str:
        if self.line_number is not None:
            return f"{self.path}:{self.line_number}: {self.snippet}"
        return self.path


@dataclass
class ToolResult:
    """Aggregated output from a single tool invocation."""

    tool_name: str
    results: list[SearchResult] = field(default_factory=list)
    error: str = ""
    truncated: bool = False
    """True when the result list was clipped to ``max_results``."""

    def to_text(self, max_display: int = 20) -> str:
        """Format the result as a human-readable string for the AI/UI."""
        if self.error:
            return f"[{self.tool_name}] Error: {self.error}"
        if not self.results:
            return f"[{self.tool_name}] No results found."
        lines = [
            f"[{self.tool_name}] {len(self.results)} result(s)"
            + (" (truncated)" if self.truncated else "")
            + ":"
        ]
        for r in self.results[:max_display]:
            lines.append(f"  {r}")
        if len(self.results) > max_display:
            lines.append(f"  … and {len(self.results) - max_display} more")
        return "\n".join(lines)


# ── Base Tool ─────────────────────────────────────────────────────────────────


class Tool:
    """Abstract base for all built-in tools."""

    #: Short identifier used in tool-call markers: ``[TOOL: name {...}]``
    name: str = ""

    #: One-line description shown to the AI in the system prompt.
    description: str = ""

    #: JSON schema of the arguments this tool accepts.
    parameters_schema: dict[str, Any] = {}

    def run(self, args: dict[str, Any]) -> ToolResult:  # noqa: ANN001
        raise NotImplementedError

    def schema_text(self) -> str:
        """Return a compact description for inclusion in the system prompt."""
        params = ", ".join(
            f"{k}: {v.get('type', 'string')}"
            for k, v in self.parameters_schema.get("properties", {}).items()
        )
        return f"  {self.name}({params}) — {self.description}"


# ── ToolPermissions ───────────────────────────────────────────────────────────


class ToolPermissions:
    """Encapsulates the allow/disallow/approval rules for tool dispatch.

    Resolution order (highest to lowest precedence):
    1. ``disallowed`` — tool is **always blocked**, no override.
    2. ``allowed``    — if non-empty, only tools in this set may run.
    3. ``requires_approval`` — tool may run, but only after the user confirms.

    Args:
        allowed:
            Whitelist of tool names the AI may call.  An empty set means *all*
            registered tools are allowed (subject to the disallowed list).
        disallowed:
            Blacklist of tool names that are completely blocked.  Takes precedence
            over ``allowed``.
        requires_approval:
            Tool names that need explicit user confirmation before executing.
            The approval callback receives the tool name and the argument dict and
            must return ``True`` to proceed.
        approve_callback:
            Called as ``approve_callback(tool_name, args) -> bool`` when a tool
            in ``requires_approval`` is invoked.  Defaults to a terminal prompt.
    """

    def __init__(
        self,
        allowed: list[str] | None = None,
        disallowed: list[str] | None = None,
        requires_approval: list[str] | None = None,
        approve_callback: "Callable[[str, dict], bool] | None" = None,
    ) -> None:
        self._allowed: frozenset[str] = frozenset(allowed or [])
        self._disallowed: frozenset[str] = frozenset(disallowed or [])
        self._requires_approval: frozenset[str] = frozenset(requires_approval or [])
        self._approve = approve_callback or _terminal_approve

    # ── Inspection helpers ────────────────────────────────────────────────────

    def is_disallowed(self, name: str) -> bool:
        return name in self._disallowed

    def is_allowed(self, name: str) -> bool:
        """Return True if *name* passes the whitelist check.

        If no whitelist is configured (empty set) every tool passes.
        """
        if self._allowed:
            return name in self._allowed
        return True

    def needs_approval(self, name: str) -> bool:
        return name in self._requires_approval

    # ── Gate ──────────────────────────────────────────────────────────────────

    def check(self, tool_name: str, args: dict) -> "ToolResult | None":
        """Enforce permissions for *tool_name* with *args*.

        Returns:
            ToolResult | None
            A ``ToolResult`` with an error message if the tool is blocked or
            the user declines.  ``None`` means the tool **may proceed**.
        """
        if self.is_disallowed(tool_name):
            logger.info("Tool %r is disallowed by configuration.", tool_name)
            return ToolResult(
                tool_name=tool_name,
                error=f"Tool '{tool_name}' is disabled.",
            )

        if not self.is_allowed(tool_name):
            logger.info(
                "Tool %r is not in the allowed list %s.",
                tool_name,
                sorted(self._allowed),
            )
            return ToolResult(
                tool_name=tool_name,
                error=(
                    f"Tool '{tool_name}' is not permitted. "
                    f"Allowed tools: {', '.join(sorted(self._allowed)) or 'none'}."
                ),
            )

        if self.needs_approval(tool_name):
            if not self._approve(tool_name, args):
                logger.info("User declined approval for tool %r.", tool_name)
                return ToolResult(
                    tool_name=tool_name,
                    error=f"Tool '{tool_name}' was not approved by the user.",
                )

        return None  # all checks passed — proceed

    # ── Visible tools (for system prompt) ────────────────────────────────────

    def visible_names(self, all_names: list[str]) -> list[str]:
        """Return the subset of *all_names* that are advertised to the AI.

        Disallowed tools and tools outside the whitelist are hidden from the
        system prompt so the AI doesn't even try to call them.
        """
        return [
            n for n in all_names if not self.is_disallowed(n) and self.is_allowed(n)
        ]


def _terminal_approve(tool_name: str, args: dict) -> bool:
    """Default approval callback: asks the user on the terminal."""
    args_preview = json.dumps(args, ensure_ascii=False)
    try:
        print(f"\n⚙  The AI wants to use tool '{tool_name}':")
        print(f"   Arguments: {args_preview}\n")
        answer = input("Allow? [y/N] ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ── ToolDescriptor ────────────────────────────────────────────────────────────


@dataclass
class ToolDescriptor:
    """Metadata + factory for a single tool — the instance is created lazily.

    The descriptor holds everything the :class:`ToolRegistry` needs to:
    - Advertise the tool to the AI (name, description, schema) **without**
      instantiating it.
    - Create the tool instance on first use via *factory*.
    - Release the instance after use when *unload_after_use* is ``True``.

    ## Lifecycle

    .. code-block:: text

        UNLOADED  ──(get_instance)──►  LOADED  ──(release)──►  UNLOADED
                                          │
                                     run() called here

    The transition back to UNLOADED is triggered automatically by
    :meth:`ToolRegistry.dispatch` when *unload_after_use* is ``True``, or
    manually via :meth:`ToolRegistry.unload` / :meth:`ToolRegistry.unload_all`.
    """

    name: str
    description: str
    parameters_schema: dict
    factory: Callable[[], Tool]
    unload_after_use: bool = False

    # Private — managed by get_instance() / release()
    _instance: Tool | None = field(default=None, init=False, repr=False)

    # ── Instance lifecycle ────────────────────────────────────────────────────

    def get_instance(self) -> Tool:
        """Return the live tool instance, creating it on first call."""
        if self._instance is None:
            logger.debug("Lazy-loading tool: %s", self.name)
            self._instance = self.factory()
        return self._instance

    def release(self) -> None:
        """Release the tool instance so it can be garbage-collected."""
        if self._instance is not None:
            logger.debug("Unloading tool: %s", self.name)
            self._instance = None

    @property
    def is_loaded(self) -> bool:
        """``True`` if the tool instance is currently in memory."""
        return self._instance is not None

    # ── System-prompt metadata ────────────────────────────────────────────────

    def schema_text(self) -> str:
        """Return a compact one-line description for the AI system prompt.

        Reads only from the descriptor fields — never touches the instance.
        """
        props = self.parameters_schema.get("properties", {})
        params = ", ".join(f"{k}: {v.get('type', 'string')}" for k, v in props.items())
        return f"  {self.name}({params}) — {self.description}"


# ── ToolRegistry ──────────────────────────────────────────────────────────────


class ToolRegistry:
    """Registry of all available tools.

    Tools are stored as :class:`ToolDescriptor` objects and instantiated
    **lazily** — only when ``dispatch()`` actually calls them.  After each
    call the instance can optionally be released (unloaded) so it is
    garbage-collected, keeping memory usage at a minimum.

    ## Key properties

    - **Zero startup cost**: registering tools is free; nothing is imported
      or constructed until the first ``dispatch()`` for that tool.
    - **Selective unloading**: set ``unload_after_use=True`` per tool (or
      globally via config) to release instances between calls.
    - **System-prompt generation** uses descriptor metadata only — no tool
      is ever instantiated just to build the prompt.
    - **Permission enforcement** via :class:`ToolPermissions` happens before
      the tool instance is even loaded, so blocked tools cost nothing.
    """

    _CALL_RE = re.compile(r"\[TOOL:\s*(\w+)\s*(\{.*?\})\]", re.DOTALL)

    def __init__(
        self,
        permissions: ToolPermissions | None = None,
        unload_after_use: bool = False,
    ) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._permissions = permissions or ToolPermissions()
        self._default_unload = unload_after_use

    # ── Registration ──────────────────────────────────────────────────────────

    def register_lazy(
        self,
        name: str,
        description: str,
        schema: dict,
        factory: Callable[[], Tool],
        *,
        unload_after_use: bool | None = None,
    ) -> None:
        """Register a tool using a factory function (primary API).

        The factory is only called on the first ``dispatch()`` for this tool.
        Subsequent calls reuse the cached instance unless *unload_after_use*
        is ``True``, in which case the instance is released after every call.

        Args:
            name:
                Tool name used in ``[TOOL: name {...}]`` markers.
            description:
                One-line description shown to the AI in the system prompt.
            schema:
                JSON Schema dict for the tool's parameters.
            factory:
                Zero-argument callable that returns a fresh ``Tool`` instance.
            unload_after_use:
                Override the registry's default unload policy for this tool.
                ``None`` → inherit the registry default.
        """
        unload = self._default_unload if unload_after_use is None else unload_after_use
        self._descriptors[name] = ToolDescriptor(
            name=name,
            description=description,
            parameters_schema=schema,
            factory=factory,
            unload_after_use=unload,
        )
        logger.debug("Registered tool (lazy): %s  unload_after_use=%s", name, unload)

    def register(self, tool: Tool) -> None:
        """Register an already-constructed tool instance (convenience API).

        The instance is wrapped in a descriptor so it participates in the
        same lazy-load / unload lifecycle.  The instance is considered
        pre-loaded (``is_loaded == True``) immediately after registration.
        """
        desc = ToolDescriptor(
            name=tool.name,
            description=getattr(tool, "description", ""),
            parameters_schema=getattr(tool, "parameters_schema", {}),
            factory=lambda t=tool: t,
            unload_after_use=self._default_unload,
        )
        desc._instance = tool  # already loaded
        self._descriptors[tool.name] = desc
        logger.debug("Registered tool (eager): %s", tool.name)

    # ── Inspection ────────────────────────────────────────────────────────────

    def get(self, name: str) -> Tool | None:
        """Return the tool instance for *name*, loading it if needed."""
        desc = self._descriptors.get(name)
        if desc is None:
            return None
        return desc.get_instance()

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        """Return the :class:`ToolDescriptor` for *name*."""
        return self._descriptors.get(name)

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._descriptors)

    def loaded_names(self) -> list[str]:
        """Return names of tools whose instances are currently in memory."""
        return [n for n, d in self._descriptors.items() if d.is_loaded]

    # ── Load / unload ─────────────────────────────────────────────────────────

    def unload(self, name: str) -> bool:
        """Release the instance for tool *name*.

        Returns ``True`` if the tool was loaded and is now released,
        ``False`` if the tool is unknown or was already unloaded.
        """
        desc = self._descriptors.get(name)
        if desc and desc.is_loaded:
            desc.release()
            return True
        return False

    def unload_all(self) -> list[str]:
        """Release all currently loaded tool instances.

        Returns the list of tool names that were unloaded.
        """
        released = []
        for name, desc in self._descriptors.items():
            if desc.is_loaded:
                desc.release()
                released.append(name)
        if released:
            logger.debug("Unloaded %d tool(s): %s", len(released), released)
        return released

    # ── System-prompt generation ──────────────────────────────────────────────

    def system_prompt_section(self) -> str:
        """Return the block injected into the AI system prompt.

        Only lists tools the AI is permitted to call.
        **No tool instance is created** — reads descriptor metadata only.
        """
        visible = self._permissions.visible_names(list(self._descriptors))
        if not visible:
            return ""

        lines = [
            "## Available tools",
            "",
            "You have access to the following tools. When you need to use one,",
            "output exactly one line in this format (valid JSON, on a single line):",
            "",
            '  [TOOL: tool_name {"arg": "value"}]',
            "",
            "Wait for the tool result before continuing your response.",
            "Only call one tool per response turn.",
            "",
            "Tools:",
        ]
        for name in visible:
            lines.append(self._descriptors[name].schema_text())
        lines.append("")
        return "\n".join(lines)

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def dispatch(self, call_text: str) -> ToolResult | None:
        """Parse and execute a ``[TOOL: name {...}]`` call from the AI.

        ## Lifecycle per call

        1. Parse *call_text* — return ``None`` if no marker found.
        2. Permission check (allow/disallow/approval) — return error result
           if blocked.  **No instance is created for blocked tools.**
        3. Lazily load the tool instance via ``descriptor.get_instance()``.
        4. Run ``tool.run(args)`` and collect the result.
        5. If ``descriptor.unload_after_use`` is ``True``, release the
           instance immediately so memory is reclaimed.

        Args:
            call_text:
                Text containing a ``[TOOL: name {...}]`` marker.

        Returns:
            ToolResult | None
            Result of the tool call, or ``None`` if no marker was found.
        """
        m = self._CALL_RE.search(call_text)
        if not m:
            return None

        tool_name = m.group(1).strip()
        args_str = m.group(2).strip()

        # 1. Unknown tool — report visible tools, not all tools
        desc = self._descriptors.get(tool_name)
        if desc is None:
            logger.warning("AI called unknown tool %r", tool_name)
            visible = self._permissions.visible_names(list(self._descriptors))
            return ToolResult(
                tool_name=tool_name,
                error=(
                    f"Unknown tool: '{tool_name}'. "
                    f"Available: {', '.join(visible) or 'none'}."
                ),
            )

        # 2. Parse JSON args
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError as exc:
            return ToolResult(
                tool_name=tool_name,
                error=f"Invalid tool arguments (not valid JSON): {exc}",
            )

        # 3. Permission gate — no instance created if blocked
        blocked = self._permissions.check(tool_name, args)
        if blocked is not None:
            return blocked

        # 4. Validate and sanitise AI-supplied arguments before dispatch
        try:
            from src.security import validate_tool_args

            args = validate_tool_args(args, schema=desc.parameters_schema)
        except (ValueError, TypeError) as exc:
            return ToolResult(
                tool_name=tool_name,
                error=f"Tool argument validation failed: {exc}",
            )

        # 5. Lazy-load and run
        tool = desc.get_instance()
        logger.info("Dispatching tool '%s' args=%s", tool_name, args)
        result = tool.run(args)

        # 6. Optional unload after use
        if desc.unload_after_use:
            desc.release()

        return result

    def find_calls(self, text: str) -> list[str]:
        """Return all ``[TOOL: ...]`` substrings found in *text*."""
        return [m.group(0) for m in self._CALL_RE.finditer(text)]
