"""Tests for src/tools.py — ManPageTool, permissions, WebSearchTool, etc."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.tools import (
    ToolPermissions,
    ToolRegistry,
    ToolResult,
    SearchResult,
    build_default_registry,
)
from src.tools.find_files      import FindFilesTool
from src.tools.search_in_files import SearchInFilesTool
from src.tools.web_search      import WebSearchTool
from src.tools.web_fetch       import WebFetchTool
from src.tools.man_reader      import ManPageTool, _extract_sections, _strip_man_formatting
from src.tools.system_control  import SystemControlTool
from src.tools.app             import AppTool
from src.tools.system_info     import SystemInfoTool


# ── _strip_man_formatting ─────────────────────────────────────────────────────


def test_strip_ansi_codes():
    text = "\x1b[1mBold\x1b[0m normal"
    assert _strip_man_formatting(text) == "Bold normal"


def test_strip_backspace_bold():
    # "l\bl" is the overprint encoding for bold 'l'
    text = "l\bls\bs"
    assert _strip_man_formatting(text) == "ls"


def test_strip_underline():
    # "_\bc" means underlined 'c'
    text = "_\bc_\ba_\bt"
    assert _strip_man_formatting(text) == "cat"


def test_strip_combined():
    text = "\x1b[4mU\x1b[0m_\bN"
    assert _strip_man_formatting(text) == "UN"


# ── _extract_sections ─────────────────────────────────────────────────────────

_SAMPLE_MAN = """\
LS(1)                     User Commands                    LS(1)

NAME
       ls - list directory contents

SYNOPSIS
       ls [OPTION]... [FILE]...

DESCRIPTION
       List information about the FILEs.

OPTIONS
       -a, --all
              do not ignore entries starting with .

       -l     use a long listing format

EXAMPLES
       ls -la /tmp
"""


def test_extract_synopsis_only():
    result = _extract_sections(_SAMPLE_MAN, ["SYNOPSIS"])
    assert "ls [OPTION]" in result
    assert "do not ignore" not in result


def test_extract_multiple_sections():
    result = _extract_sections(_SAMPLE_MAN, ["SYNOPSIS", "OPTIONS"])
    assert "ls [OPTION]" in result
    assert "--all" in result
    assert "List information" not in result


def test_extract_nonexistent_section_returns_empty():
    result = _extract_sections(_SAMPLE_MAN, ["NONEXISTENT"])
    assert result.strip() == ""


def test_extract_empty_sections_returns_all():
    result = _extract_sections(_SAMPLE_MAN, [])
    assert "NAME" in result or "ls" in result


# ── ManPageTool ───────────────────────────────────────────────────────────────


def _make_completed_process(stdout: str, returncode: int = 0, stderr: str = ""):
    p = MagicMock()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


class TestManPageTool:
    def test_rejects_empty_command(self):
        tool = ManPageTool()
        result = tool.run({"command": ""})
        assert result.error
        assert not result.results

    def test_rejects_invalid_command_name(self):
        tool = ManPageTool()
        for bad in ["ls; rm -rf /", "../etc/passwd", "cmd$(inject)"]:
            result = tool.run({"command": bad})
            assert result.error, f"Expected error for {bad!r}"

    @patch("shutil.which", return_value=None)
    def test_man_not_installed(self, _which):
        tool = ManPageTool()
        result = tool.run({"command": "ls"})
        assert "not installed" in result.error

    @patch("shutil.which", return_value="/usr/bin/man")
    @patch("subprocess.run")
    def test_successful_lookup(self, mock_run, _which):
        mock_run.return_value = _make_completed_process(_SAMPLE_MAN)
        tool = ManPageTool(max_chars=5000, default_sections=["SYNOPSIS", "OPTIONS"])
        result = tool.run({"command": "ls"})
        assert not result.error
        assert result.results
        assert "ls [OPTION]" in result.results[0].snippet

    @patch("shutil.which", return_value="/usr/bin/man")
    @patch("subprocess.run")
    def test_unknown_command_returns_error(self, mock_run, _which):
        mock_run.return_value = _make_completed_process("", returncode=1,
                                                        stderr="No manual entry for notacommand")
        tool = ManPageTool()
        result = tool.run({"command": "notacommand"})
        assert result.error
        assert "notacommand" in result.error

    @patch("shutil.which", return_value="/usr/bin/man")
    @patch("subprocess.run")
    def test_truncation(self, mock_run, _which):
        long_text = "A" * 20_000
        mock_run.return_value = _make_completed_process(long_text)
        tool = ManPageTool(max_chars=100, default_sections=[])
        result = tool.run({"command": "ls"})
        assert result.truncated
        assert len(result.results[0].snippet) == 100

    @patch("shutil.which", return_value="/usr/bin/man")
    @patch("subprocess.run")
    def test_caller_can_request_sections(self, mock_run, _which):
        mock_run.return_value = _make_completed_process(_SAMPLE_MAN)
        tool = ManPageTool(default_sections=["DESCRIPTION"])
        result = tool.run({"command": "ls", "sections": ["EXAMPLES"]})
        assert not result.error
        assert "ls -la /tmp" in result.results[0].snippet

    @patch("shutil.which", return_value="/usr/bin/man")
    @patch("subprocess.run")
    def test_man_section_number_passed(self, mock_run, _which):
        mock_run.return_value = _make_completed_process(_SAMPLE_MAN)
        tool = ManPageTool(default_sections=[])
        tool.run({"command": "passwd", "man_section": "5"})
        call_args = mock_run.call_args[0][0]
        assert "5" in call_args
        assert "passwd" in call_args

    @patch("shutil.which", return_value="/usr/bin/man")
    @patch("subprocess.run")
    def test_fallback_to_full_page_when_sections_missing(self, mock_run, _which):
        # Page that has no standard section headers
        plain_page = "This command does something.\nUsage: cmd [options]\n"
        mock_run.return_value = _make_completed_process(plain_page)
        tool = ManPageTool(default_sections=["OPTIONS"])
        result = tool.run({"command": "cmd"})
        # Should fall back to the full page text
        assert not result.error
        assert "cmd [options]" in result.results[0].snippet


# ── ToolPermissions ───────────────────────────────────────────────────────────


class TestToolPermissions:
    def test_disallowed_blocks_all(self):
        perms = ToolPermissions(disallowed=["dangerous_tool"])
        blocked = perms.check("dangerous_tool", {})
        assert blocked is not None
        assert "disabled" in blocked.error

    def test_disallowed_takes_precedence_over_allowed(self):
        perms = ToolPermissions(allowed=["dangerous_tool"],
                                disallowed=["dangerous_tool"])
        blocked = perms.check("dangerous_tool", {})
        assert blocked is not None

    def test_allowed_whitelist_permits_listed_tool(self):
        perms = ToolPermissions(allowed=["find_files", "search_in_files"])
        assert perms.check("find_files", {}) is None
        assert perms.check("search_in_files", {}) is None

    def test_allowed_whitelist_blocks_unlisted_tool(self):
        perms = ToolPermissions(allowed=["find_files"])
        blocked = perms.check("web_search", {})
        assert blocked is not None
        assert "not permitted" in blocked.error

    def test_empty_allowed_permits_everything(self):
        perms = ToolPermissions(allowed=[])
        assert perms.check("any_tool", {}) is None

    def test_requires_approval_calls_callback_true(self):
        callback = MagicMock(return_value=True)
        perms = ToolPermissions(requires_approval=["web_search"],
                                approve_callback=callback)
        result = perms.check("web_search", {"query": "test"})
        assert result is None
        callback.assert_called_once_with("web_search", {"query": "test"})

    def test_requires_approval_calls_callback_false(self):
        callback = MagicMock(return_value=False)
        perms = ToolPermissions(requires_approval=["web_search"],
                                approve_callback=callback)
        result = perms.check("web_search", {"query": "test"})
        assert result is not None
        assert "not approved" in result.error

    def test_visible_names_excludes_disallowed(self):
        perms = ToolPermissions(disallowed=["web_search"])
        visible = perms.visible_names(["find_files", "web_search", "read_man_page"])
        assert "web_search" not in visible
        assert "find_files" in visible

    def test_visible_names_respects_allowlist(self):
        perms = ToolPermissions(allowed=["find_files"])
        visible = perms.visible_names(["find_files", "web_search", "read_man_page"])
        assert visible == ["find_files"]


# ── ToolRegistry dispatch ─────────────────────────────────────────────────────


class TestToolRegistry:
    def _registry_with_mock_tool(self, tool_name="test_tool"):
        registry = ToolRegistry()
        tool = MagicMock(spec=["name", "run", "schema_text"])
        tool.name = tool_name
        tool.schema_text.return_value = f"  {tool_name}() — test"
        tool.run.return_value = ToolResult(tool_name=tool_name,
                                           results=[], error="")
        registry.register(tool)
        return registry, tool

    def test_dispatch_returns_none_for_no_match(self):
        registry, _ = self._registry_with_mock_tool()
        assert registry.dispatch("no tool call here") is None

    def test_dispatch_calls_correct_tool(self):
        registry, tool = self._registry_with_mock_tool("find_files")
        registry.dispatch('[TOOL: find_files {"pattern": "*.py"}]')
        tool.run.assert_called_once_with({"pattern": "*.py"})

    def test_dispatch_unknown_tool_returns_error(self):
        registry, _ = self._registry_with_mock_tool()
        result = registry.dispatch('[TOOL: nonexistent {"x": 1}]')
        assert result is not None
        assert result.error

    def test_dispatch_invalid_json_returns_error(self):
        registry, _ = self._registry_with_mock_tool("find_files")
        result = registry.dispatch('[TOOL: find_files {not valid json}]')
        assert result is not None
        assert "JSON" in result.error

    def test_dispatch_respects_disallowed(self):
        perms = ToolPermissions(disallowed=["find_files"])
        registry = ToolRegistry(permissions=perms)
        tool = MagicMock()
        tool.name = "find_files"
        registry.register(tool)
        result = registry.dispatch('[TOOL: find_files {"pattern": "*.py"}]')
        assert result is not None
        assert result.error
        tool.run.assert_not_called()

    def test_find_calls_extracts_all_markers(self):
        registry = ToolRegistry()
        text = (
            'some text [TOOL: find_files {"pattern": "*.pdf"}] '
            'more text [TOOL: web_search {"query": "hello"}]'
        )
        calls = registry.find_calls(text)
        assert len(calls) == 2
        assert 'find_files' in calls[0]
        assert 'web_search' in calls[1]

    def test_system_prompt_excludes_disallowed(self):
        perms = ToolPermissions(disallowed=["web_search"])
        registry = ToolRegistry(permissions=perms)
        for name in ("find_files", "web_search", "read_man_page"):
            t = MagicMock()
            t.name = name
            t.schema_text.return_value = f"  {name}() — desc"
            registry.register(t)
        prompt = registry.system_prompt_section()
        assert "web_search" not in prompt
        assert "find_files" in prompt


# ── WebSearchTool ─────────────────────────────────────────────────────────────


class TestWebSearchTool:
    @patch("subprocess.Popen")
    def test_opens_correct_url(self, mock_popen):
        tool = WebSearchTool(default_engine="duckduckgo")
        result = tool.run({"query": "hello world"})
        assert not result.error
        call_args = mock_popen.call_args[0][0]
        assert call_args[0] == "xdg-open"
        assert "hello+world" in call_args[1] or "hello%20world" in call_args[1]

    @patch("subprocess.Popen")
    def test_engine_override(self, mock_popen):
        tool = WebSearchTool(default_engine="duckduckgo")
        result = tool.run({"query": "test", "engine": "brave"})
        assert not result.error
        url = mock_popen.call_args[0][0][1]
        assert "brave.com" in url

    def test_unknown_engine_returns_error(self):
        tool = WebSearchTool(default_engine="duckduckgo")
        result = tool.run({"query": "test", "engine": "doesnotexist"})
        assert result.error

    def test_empty_query_returns_error(self):
        tool = WebSearchTool()
        result = tool.run({"query": ""})
        assert result.error

    @patch("subprocess.Popen", side_effect=FileNotFoundError)
    def test_xdg_open_missing_returns_error(self, _popen):
        tool = WebSearchTool()
        result = tool.run({"query": "test"})
        assert result.error
        assert "xdg-open" in result.error


# ── SearchInFilesTool blocked_paths ───────────────────────────────────────────


class TestSearchInFilesBlocked:
    def test_blocked_path_returns_error(self, tmp_path):
        blocked = str(tmp_path)
        tool = SearchInFilesTool(
            default_search_path=str(tmp_path),
            blocked_paths=[blocked],
        )
        result = tool.run({"query": "secret", "path": blocked})
        assert result.error
        assert "not permitted" in result.error

    def test_non_blocked_path_proceeds(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "note.txt").write_text("hello world")
        blocked = tmp_path / "secrets"
        blocked.mkdir()

        tool = SearchInFilesTool(
            default_search_path=str(allowed),
            blocked_paths=[str(blocked)],
        )
        # Should not error — just may find no results
        result = tool.run({"query": "hello", "path": str(allowed)})
        assert not result.error


# ── build_default_registry ────────────────────────────────────────────────────


class TestBuildDefaultRegistry:
    def test_all_default_tools_registered(self):
        registry = build_default_registry()
        names = registry.names()
        assert "find_files" in names
        assert "search_in_files" in names
        assert "web_search" in names
        assert "read_man_page" in names

    def test_man_reader_disabled_removes_tool(self):
        registry = build_default_registry({"man_reader": {"enabled": False}})
        assert "read_man_page" not in registry.names()

    def test_permissions_wired_from_config(self):
        registry = build_default_registry({
            "disallowed": ["web_search"],
            "requires_approval": [],
        })
        result = registry.dispatch('[TOOL: web_search {"query": "hi"}]')
        assert result is not None
        assert result.error

    def test_custom_web_search_engine(self):
        registry = build_default_registry({
            "web_search": {
                "engine": "brave",
                "engines": {"brave": "https://search.brave.com/search?q={query}"},
            }
        })
        tool = registry.get("web_search")
        assert tool is not None
        assert tool._default_engine == "brave"  # type: ignore[attr-defined]

    def test_man_reader_max_chars_passed(self):
        registry = build_default_registry({
            "man_reader": {"enabled": True, "max_chars": 1234}
        })
        tool = registry.get("read_man_page")
        assert tool._max_chars == 1234  # type: ignore[attr-defined]

class TestWebFetchTool:
    @patch("requests.Session")
    def test_web_fetch_request_exception(self, mock_session_cls):
        import requests
        tool = WebFetchTool()
        mock_session_instance = mock_session_cls.return_value
        mock_session_instance.get.side_effect = requests.exceptions.RequestException("Mocked network error")

        result = tool.run({"url": "https://example.com"})

        assert "Request failed: Mocked network error" in result.error
