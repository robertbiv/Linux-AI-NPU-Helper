import pytest
import math
from src.tools.calculator import CalculatorTool, _safe_pow, _safe_factorial, _safe_comb, _safe_perm

def test_calculator_tool_invalid_args():
    tool = CalculatorTool()
    res = tool.run({})
    assert "'expression' is required" in res.error

def test_calculator_tool_basic():
    tool = CalculatorTool()

    # Arithmetic
    res = tool.run({"expression": "2 + 2"})
    assert "2 + 2 = 4" in res.results[0].snippet

    # Floats that are integers
    res = tool.run({"expression": "4.0"})
    assert "4.0 = 4" in res.results[0].snippet

def test_calculator_tool_operators():
    tool = CalculatorTool()
    assert "= 5" in tool.run({"expression": "10 / 2"}).results[0].snippet
    assert "= 5" in tool.run({"expression": "11 // 2"}).results[0].snippet
    assert "= 1" in tool.run({"expression": "11 % 2"}).results[0].snippet
    assert "= -1" in tool.run({"expression": "-1"}).results[0].snippet
    assert "= 1" in tool.run({"expression": "+1"}).results[0].snippet
    assert "= 3" in tool.run({"expression": "1 ^ 2"}).results[0].snippet # 1 XOR 2 = 3

def test_calculator_tool_math_functions():
    tool = CalculatorTool()

    # math.sin(math.pi / 2)
    res = tool.run({"expression": "math.sin(math.pi / 2)"})
    assert "= 1" in res.results[0].snippet

    res = tool.run({"expression": "sin(pi / 2)"})
    assert "= 1" in res.results[0].snippet

    res = tool.run({"expression": "pow(2, 3)"})
    assert "= 8" in res.results[0].snippet

def test_calculator_tool_safe_wrappers_ok():
    tool = CalculatorTool()
    assert "= 8" in tool.run({"expression": "2 ** 3"}).results[0].snippet
    assert "= 120" in tool.run({"expression": "factorial(5)"}).results[0].snippet
    if hasattr(math, "comb"):
        assert "= 10" in tool.run({"expression": "comb(5, 2)"}).results[0].snippet
    if hasattr(math, "perm"):
        assert "= 20" in tool.run({"expression": "perm(5, 2)"}).results[0].snippet

def test_calculator_tool_safe_wrappers_limits():
    tool = CalculatorTool()

    res = tool.run({"expression": "2 ** 10001"})
    assert "Error evaluating expression" in res.error
    assert "Exponent too large" in res.error

    res = tool.run({"expression": "factorial(10001)"})
    assert "Argument too large for factorial" in res.error

    if hasattr(math, "comb"):
        res = tool.run({"expression": "comb(10001, 2)"})
        assert "Argument too large for comb" in res.error

    if hasattr(math, "perm"):
        res = tool.run({"expression": "perm(10001, 2)"})
        assert "Argument too large for perm" in res.error

def test_calculator_tool_exceptions():
    tool = CalculatorTool()

    # Unsupported node
    res = tool.run({"expression": "[1, 2, 3]"})
    assert "Unsupported AST node" in res.error

    # Unsupported constant
    res = tool.run({"expression": "'string'"})
    assert "Unsupported constant type" in res.error

    # Unsupported operator
    res = tool.run({"expression": "1 > 2"})
    assert "Unsupported AST node" in res.error # Compare is not supported

    # Unsupported unary
    res = tool.run({"expression": "not 1"})
    assert "Unsupported unary operator" in res.error
    res = tool.run({"expression": "~1"}) # Invert
    assert "Unsupported unary operator" in res.error

    # Unsupported function call (not callable)
    res = tool.run({"expression": "math(1)"})
    assert "Unsupported function call" in res.error

    # NameError
    res = tool.run({"expression": "unknown_var"})
    assert "Unsupported variable/function: unknown_var" in res.error

    # AttributeError
    res = tool.run({"expression": "math.unknown_attr"})
    assert "Unsupported attribute: unknown_attr" in res.error

    res = tool.run({"expression": "sin.unknown_attr"})
    assert "Unsupported attribute: unknown_attr" in res.error

    # Unsupported BinOp op
    # BitAnd is not in _OPERATORS
    res = tool.run({"expression": "1 & 2"})
    assert "Unsupported operator" in res.error
