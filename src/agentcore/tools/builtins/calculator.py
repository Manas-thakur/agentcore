"""A calculator that evaluates math with an AST walker - no ``eval()``."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from agentcore.tools.decorator import tool

_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Any] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS: dict[str, Any] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
    "factorial": math.factorial,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
MAX_EXPONENT = 10_000
MAX_FACTORIAL = 1_000


def safe_eval(expression: str) -> int | float:
    """Evaluate an arithmetic expression safely. Raises ``ValueError`` on anything else."""
    expression = expression.replace("^", "**").replace("×", "*").replace("÷", "/").strip()
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {expression!r}") from exc
    return _eval(tree.body)


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError("exponent too large")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        fn = _FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"function {node.func.id!r} is not allowed")
        args = [_eval(a) for a in node.args]
        if fn is math.factorial and args and args[0] > MAX_FACTORIAL:
            raise ValueError("factorial argument too large")
        return fn(*args)
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


@tool(category="math", timeout=5)
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression and return the result.

    Supports + - * / // % ** (or ^), parentheses, constants pi/e/tau and functions
    sqrt, sin, cos, tan, log, log10, log2, exp, abs, round, floor, ceil, min, max, factorial.

    Args:
        expression: The arithmetic expression to evaluate, e.g. "17 * 23 + 4".
    """
    result = safe_eval(expression)
    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        result = int(result)
    if isinstance(result, float):
        return f"{result:.10g}"
    return str(result)
