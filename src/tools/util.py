"""Small things a model is bad at on its own: knowing the date, doing arithmetic."""
import ast
import datetime
import operator

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
       ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / // % ** are allowed")


def now() -> str:
    """Today's date and the current time, with the day of the week and the timezone."""
    moment = datetime.datetime.now().astimezone()
    return moment.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")


def calculate(expression: str) -> str:
    """Work out an arithmetic expression exactly, instead of guessing at it.

    Args:
        expression: something like (1420.50 * 12) / 3
    """
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except Exception as e:
        return f"error: {e}"
