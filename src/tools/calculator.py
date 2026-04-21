# SPDX-License-Identifier: GPL-3.0-or-later
"""Calculator tool — safely evaluate mathematical expressions."""

import ast
import logging
import math
import operator
from typing import Any

from src.tools._base import SearchResult, Tool, ToolResult

logger = logging.getLogger(__name__)


def _safe_pow(a: Any, b: Any) -> Any:
    if isinstance(b, (int, float)) and abs(b) > 10000:
        raise ValueError("Exponent too large")
    return operator.pow(a, b)


def _safe_factorial(n: Any) -> Any:
    if isinstance(n, int) and n > 10000:
        raise ValueError("Argument too large for factorial")
    return math.factorial(n)


def _safe_comb(n: Any, k: Any) -> Any:
    if isinstance(n, int) and n > 10000:
        raise ValueError("Argument too large for comb")
    return getattr(math, "comb")(n, k)


def _safe_perm(n: Any, k: Any) -> Any:
    if isinstance(n, int) and n > 10000:
        raise ValueError("Argument too large for perm")
    return getattr(math, "perm")(n, k)


# Allowed operators
_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: _safe_pow,
    ast.Mod: operator.mod,
    ast.BitXor: operator.xor,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Allowed math functions and constants
_MATH_NAMES = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
_MATH_NAMES["factorial"] = _safe_factorial
if hasattr(math, "comb"):
    _MATH_NAMES["comb"] = _safe_comb
if hasattr(math, "perm"):
    _MATH_NAMES["perm"] = _safe_perm
if hasattr(math, "pow"):
    _MATH_NAMES["pow"] = _safe_pow


def _eval_ast(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise TypeError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.BinOp):
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        op = _OPERATORS.get(type(node.op))
        if op is None:
            raise TypeError(f"Unsupported operator: {type(node.op)}")
        return op(left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand)
        op = _OPERATORS.get(type(node.op))
        if op is None:
            raise TypeError(f"Unsupported unary operator: {type(node.op)}")
        return op(operand)
    elif isinstance(node, ast.Call):
        func = _eval_ast(node.func)
        args = [_eval_ast(arg) for arg in node.args]
        if not callable(func):
            raise TypeError(f"Unsupported function call: {func}")
        return func(*args)
    elif isinstance(node, ast.Name):
        if node.id in _MATH_NAMES:
            return _MATH_NAMES[node.id]
        if node.id == "math":
            return math
        raise NameError(f"Unsupported variable/function: {node.id}")
    elif isinstance(node, ast.Attribute):
        # support math.pi etc
        val = _eval_ast(node.value)
        if val == math:
            if node.attr in _MATH_NAMES:
                return _MATH_NAMES[node.attr]
        raise AttributeError(f"Unsupported attribute: {node.attr}")
    else:
        raise TypeError(f"Unsupported AST node: {type(node)}")


class CalculatorTool(Tool):
    """Evaluate mathematical expressions safely."""

    name = "calculate"
    description = (
        "Evaluate a mathematical expression safely. "
        "Useful for arithmetic, trigonometry, and general math. "
        "Supports standard Python math functions (e.g., sin, cos, sqrt, log)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate (e.g., '2 + 2', 'math.sin(math.pi / 2)').",
            },
        },
        "required": ["expression"],
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        expr: str = args.get("expression", "").strip()
        if not expr:
            return ToolResult(tool_name=self.name, error="'expression' is required.")

        try:
            tree = ast.parse(expr, mode="eval")
            result = _eval_ast(tree)

            # format nicely
            if isinstance(result, float) and result.is_integer():
                result = int(result)

            snippet = f"{expr} = {result}"
            return ToolResult(
                tool_name=self.name,
                results=[SearchResult(path="calc", snippet=snippet)],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Calculator error for '%s': %s", expr, exc)
            return ToolResult(
                tool_name=self.name,
                error=f"Error evaluating expression: {exc}",
            )
