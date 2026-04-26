import pytest
from unittest.mock import patch, MagicMock
from src.tools.web_search import WebSearchTool

def test_web_search_missing_args():
    tool = WebSearchTool()
    res = tool.run({})
    assert res.error == "'query' is required."

def test_web_search_invalid_engine():
    tool = WebSearchTool()
    res = tool.run({"query": "a", "engine": "invalid_engine_name"})
    assert "Unknown engine" in res.error

def test_web_search_success():
    tool = WebSearchTool()
    with patch('subprocess.Popen') as mock_popen:
        res = tool.run({"query": "test query"})
        assert not res.error
        assert "Opened duckduckgo search" in res.results[0].snippet

def test_web_search_file_not_found():
    tool = WebSearchTool()
    with patch('subprocess.Popen', side_effect=FileNotFoundError):
        res = tool.run({"query": "test query"})
        assert "xdg-open not found" in res.error

def test_web_search_exception():
    tool = WebSearchTool()
    with patch('subprocess.Popen', side_effect=Exception("Error")):
        res = tool.run({"query": "test query"})
        assert "Error" in res.error
