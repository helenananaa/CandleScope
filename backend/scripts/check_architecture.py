"""Check Python dependency boundaries without importing the application.

Run from backend: python -B scripts/check_architecture.py
The HTTP tree and app.main own composition. Business packages cannot depend on
either, including through relative imports, package initializers or re-exports.
"""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path


@dataclass(frozen=True)
class Dependency:
    target: str
    line: int


def dependencies(source: str, module: str, *, is_package: bool = False) -> list[Dependency]:
    tree = ast.parse(source)
    package = module if is_package else module.rpartition(".")[0]
    aliases: dict[str, str] = {}
    constants: dict[str, str] = {"__package__": package}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module in {"importlib", "builtins"}:
            for item in node.names:
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"

    def literal(node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = literal(node.left), literal(node.right)
            return left + right if left is not None and right is not None else None
        return None

    # Simple module constants used by literal dynamic imports. Runtime-selected
    # plugins are not statically knowable; isolated import tests cover real paths.
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = literal(node.value)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is not None:
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value

    def qualified(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + "." + node.attr
        return ""

    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(Dependency(item.name, node.lineno) for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            base = resolve_name(name, package) if node.level else name
            result.append(Dependency(base, node.lineno))
            result.extend(Dependency(f"{base}.{item.name}", node.lineno) for item in node.names if item.name != "*")
        elif isinstance(node, ast.Call) and node.args:
            function = qualified(node.func)
            if function not in {"importlib.import_module", "__import__", "builtins.__import__"}:
                continue
            name = literal(node.args[0])
            if name is None:
                continue
            if function == "importlib.import_module" and name.startswith("."):
                package_arg = node.args[1] if len(node.args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == "package"), None,
                )
                parent = literal(package_arg)
                if parent is None:
                    continue
                name = resolve_name(name, parent)
            result.append(Dependency(name, node.lineno))
    return result


def dependency_graph(app_root: Path) -> dict[str, list[Dependency]]:
    graph = {}
    for path in sorted(app_root.rglob("*.py")):
        parts = path.relative_to(app_root.parent).with_suffix("").parts
        is_package = parts[-1] == "__init__"
        module = ".".join(parts[:-1] if is_package else parts)
        graph[module] = dependencies(path.read_text(encoding="utf-8"), module, is_package=is_package)
    # Importing a child always executes its parent initializers. Include these
    # edges so a package re-export cannot conceal an HTTP dependency.
    for module, edges in graph.items():
        parent = module.rpartition(".")[0]
        if parent in graph:
            edges.append(Dependency(parent, 1))
    return graph


def within(module: str, namespace: str) -> bool:
    return module == namespace or module.startswith(namespace + ".")


def dependency_path(graph: dict[str, list[Dependency]], start: str, forbidden: tuple[str, ...]) -> list[str] | None:
    queue = deque([(start, [start])])
    seen = {start}
    while queue:
        module, path = queue.popleft()
        for edge in graph.get(module, []):
            target = edge.target
            if any(within(target, name) for name in forbidden):
                return [*path, target]
            # from package import value can refer to a symbol, not a module.
            while target and target not in graph:
                target = target.rpartition(".")[0]
            if target and target not in seen:
                seen.add(target)
                queue.append((target, [*path, target]))
    return None


def violations(app_root: Path) -> list[str]:
    graph = dependency_graph(app_root)
    errors = []
    for module, edges in graph.items():
        if within(module, "app.api") or module == "app.main":
            continue
        for edge in edges:
            if within(edge.target, "app.api") or within(edge.target, "app.main"):
                errors.append(f"{module}:{edge.line} -> {edge.target}: business code cannot import HTTP composition")
    # Contracts and presentation/catalog services are transport independent,
    # including transitively. Only the outer adapters map domain errors to HTTP.
    owners = (
        "app.backtest.request_contracts", "app.backtest.native_contracts",
        "app.backtest.snapshot_validation", "app.replay.request_contracts",
        "app.exchanges.symbol_catalog", "app.exchanges.discovery_catalog",
        "app.data_engine.market_data.order_book_contract",
        "app.data_engine.market_data.order_book_projection",
        "app.data_engine.market_data.order_book_auto",
    )
    for owner in owners:
        if owner in graph:
            path = dependency_path(graph, owner, ("app.api", "app.main", "fastapi", "starlette"))
            if path:
                errors.append(" -> ".join(path) + ": shared business owner depends on HTTP")
    errors.extend(training_violations(app_root, graph))
    return sorted(set(errors))


def training_violations(app_root: Path, graph: dict[str, list[Dependency]]) -> list[str]:
    """Keep extracted replay owners independent and preserve one writer owner.

    This is a static contract for ordinary Python imports and calls, not a
    sandbox for arbitrary runtime code. Transaction/failure tests are separate.
    """
    prefix = "app.replay.training."
    components = tuple(prefix + name for name in (
        "admission_service", "order_service", "display_service", "ordered_playback",
        "advance_service", "review_service",
    ))
    rules = tuple(prefix + name for name in (
        "admission_rules", "order_rules", "control_rules", "service_validation",
        "command_projection", "display_state",
    ))
    errors = []
    for module in graph:
        persistence = within(module, prefix + "persistence")
        repository = within(module, prefix + "repositories")
        if persistence or repository or module in rules:
            forbidden = (prefix + "storage", prefix + "service", *components)
            if persistence or module in rules:
                forbidden += (prefix + "repositories",)
            if module in rules:
                forbidden += (prefix + "persistence", "app.replay.storage")
        elif module in components:
            forbidden = (prefix + "service",)
        else:
            continue
        path = dependency_path(graph, module, forbidden)
        if path:
            errors.append(" -> ".join(path) + ": replay responsibility points back to its coordinator")
        if not (persistence or repository):
            continue
        relative = Path(*module.split(".")[1:])
        source = app_root / relative.with_suffix(".py")
        if not source.exists():
            source = app_root / relative / "__init__.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases[item.asname or item.name] = item.name
            elif isinstance(node, ast.ImportFrom):
                for item in node.names:
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"

        def qualified(node: ast.AST) -> str:
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return qualified(node.value) + "." + node.attr
            return ""

        for node in ast.walk(tree):
            reason = None
            if isinstance(node, ast.Call):
                name = qualified(node.func)
                leaf = name.rpartition(".")[2]
                if leaf in {"commit", "rollback", "ReplaySQLiteStore", "ThreadPoolExecutor"} or name in {
                    "sqlite3.connect", "sqlite3.Connection", "threading.Thread",
                }:
                    reason = "repositories and operations must reuse the caller's SQLite owner"
                if persistence and leaf in {
                    "run_extension_write", "run_extension_read", "publish", "create_task", "to_thread",
                }:
                    reason = "persistence operations cannot schedule work or publish state"
                if leaf in {"execute", "executescript"} and node.args:
                    sql = node.args[0]
                    if isinstance(sql, ast.Constant) and isinstance(sql.value, str):
                        # Also catch transaction statements after another statement.
                        words = [part.strip().upper().split() for part in sql.value.split(";")]
                        if any(part and part[0] in {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "END"} for part in words):
                            reason = "transaction boundaries belong to ReplaySQLiteStore"
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                if any(isinstance(item.context_expr, ast.Name) and item.context_expr.id in {"connection", "conn"} for item in node.items):
                    reason = "connection context managers implicitly commit or roll back"
            elif persistence and isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
                reason = "connection-local persistence operations must stay synchronous"
            if reason:
                errors.append(f"{module}:{node.lineno}: {reason}")
    return errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "app"
    failures = violations(root)
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print("Backend architecture passed: HTTP-independent business owners; replay responsibilities and SQLite ownership preserved.")
