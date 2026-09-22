"""Finite requested-expression history, without executing strategy code."""
import ast

from .models import PreparationError

MAX_BARS = 5000
_SERIES = {"open", "high", "low", "close", "volume", "time", "hl2", "hlc3", "ohlc4", "hlcc4"}
_WINDOWS = {"sma", "wma", "highest", "lowest", "sum", "stdev", "variance", "linreg"}


def expression_lookback(expression):
    """Return prior bars needed, or None when a finite bound is not established."""
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return None
    def integer(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, right = integer(node.left), integer(node.right)
            if left is not None and right is not None and abs(left) <= MAX_BARS and abs(right) <= MAX_BARS:
                return left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
        return None
    def maximum(nodes):
        values = [history(item) for item in nodes]
        return None if None in values else max(values, default=0)
    def history(node):
        if isinstance(node, ast.Constant):
            return 0
        if isinstance(node, ast.Name):
            return 0 if node.id in _SERIES else None
        if isinstance(node, ast.Lambda):
            return history(node.body)
        if isinstance(node, ast.Subscript):
            offset, base = integer(node.slice), history(node.value)
            return base + offset if base is not None and offset is not None and offset >= 0 else None
        if isinstance(node, ast.BinOp):
            return maximum((node.left, node.right))
        if isinstance(node, ast.UnaryOp):
            return history(node.operand)
        if isinstance(node, ast.Compare):
            return maximum([node.left, *node.comparators])
        if isinstance(node, ast.BoolOp):
            return maximum(node.values)
        if isinstance(node, (ast.Tuple, ast.List)):
            return maximum(node.elts)
        if isinstance(node, ast.IfExp):
            return maximum((node.test, node.body, node.orelse))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            namespace, name = node.func.value.id, node.func.attr
            args = node.args
            # Stateful/recursive functions and user-defined calls deliberately
            # require a declaration; do not silently assume one prior bar.
            if namespace == "ta" and name in _WINDOWS:
                named = {item.arg: item.value for item in node.keywords}
                source = args[0] if args else named.get("source")
                length = args[1] if len(args) > 1 else named.get("length")
                if name in {"highest", "lowest"} and len(args) == 1 and not node.keywords:
                    source, length = ast.Name(id="close"), args[0]
                count = integer(length)
                prior = history(source) if source is not None else None
                if count is None or count < 1 or prior is None:
                    return None
                extra = maximum([*args[2:], *(item.value for item in node.keywords if item.arg not in {"source", "length"})])
                return None if extra is None else max(prior + count - 1, extra)
            if namespace == "ta" and name in {"crossover", "crossunder", "cross"} and len(args) == 2 and not node.keywords:
                prior = maximum(args)
                return None if prior is None else prior + 1
            if namespace == "math" and name in {"abs", "min", "max", "round", "floor", "ceil", "sqrt", "log", "exp", "pow"}:
                return maximum([*args, *(item.value for item in node.keywords)])
        return None
    try:
        result = history(tree.body)
    except RecursionError:
        return None
    if result is not None and result > MAX_BARS:
        raise PreparationError("WARMUP_BUDGET", "Requested-context history exceeds 5000 prior bars")
    return result
