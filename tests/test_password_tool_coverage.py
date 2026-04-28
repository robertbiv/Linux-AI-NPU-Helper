import pytest
from src.tools.password_tool import PasswordGeneratorTool

def test_password_tool_defaults():
    tool = PasswordGeneratorTool()
    res = tool.run({})
    assert "Generated password (16 chars):" in res.results[0].snippet

    pwd = res.results[0].snippet.split("): ")[1]
    assert len(pwd) == 16
    assert any(c.islower() for c in pwd)
    assert any(c.isupper() for c in pwd)
    assert any(c.isdigit() for c in pwd)
    assert any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in pwd)

def test_password_tool_custom():
    tool = PasswordGeneratorTool()
    res = tool.run({"length": 8, "include_symbols": False})
    assert "Generated password (8 chars):" in res.results[0].snippet

    pwd = res.results[0].snippet.split("): ")[1]
    assert len(pwd) == 8
    assert not any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in pwd)

def test_password_tool_bounds():
    tool = PasswordGeneratorTool()

    # Min bound
    res = tool.run({"length": 2})
    assert "Generated password (4 chars):" in res.results[0].snippet

    # Max bound
    res = tool.run({"length": 200})
    assert "Generated password (128 chars):" in res.results[0].snippet

def test_password_tool_invalid_length():
    tool = PasswordGeneratorTool()
    res = tool.run({"length": "invalid"})
    assert "Generated password (16 chars):" in res.results[0].snippet

def test_password_tool_regenerate_loop():
    # Force the choice to be all 'a' the first time, to trigger the regeneration loop
    import secrets
    original_choice = secrets.choice
    call_count = [0]

    def fake_choice(seq):
        call_count[0] += 1
        if call_count[0] <= 16:
            return 'a'
        return original_choice(seq)

    tool = PasswordGeneratorTool()
    import unittest.mock
    with unittest.mock.patch("secrets.choice", side_effect=fake_choice):
        res = tool.run({"length": 16, "include_symbols": True})
        assert "Generated password (16 chars):" in res.results[0].snippet
        assert call_count[0] > 16
