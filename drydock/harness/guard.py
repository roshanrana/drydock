"""Layer 1: the static AST guard (LLD section 4).

Pure functions over source text. Nothing here imports or executes generated code; the
guard runs before ``runner.py`` is ever spawned. ``checks.py`` re-exports the public names
so existing callers keep importing them from ``drydock.harness.checks``.

The guard allowlists *imports* and, on top of that, rejects the attribute/name hops that a
2026-09-07 review used to reach a real capability through an allowed module
(``import os.path as osp; osp.os.system(...)``). It is deliberately conservative: anything
it cannot prove safe is a finding, and a finding means the code is never executed.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from drydock.models import CheckId, Finding, Severity

# Import allowlist. ``os.path`` was removed after the review: the generated pipelines never
# import it (verified against providers/templates.py), and keeping it in the allowlist gave
# the ``osp.os`` attribute hop an entry point. ``pathlib`` stays, jailed at runtime (layer 2).
PIPELINE_ALLOWED_MODULES = frozenset(
    {
        "__future__",
        "csv",
        "json",
        "decimal",
        "datetime",
        "re",
        "io",
        "pathlib",
        "typing",
        "dataclasses",
        "collections",
        "itertools",
        "functools",
        "math",
        "string",
        "time",  # needed so a slow pipeline (H5) is a latency finding, not a guard hit
    }
)
DAG_ALLOWED_MODULES = frozenset(
    {"__future__", "airflow", "airflow.operators.python", "datetime", "pipeline"}
)
OPEN_LIKE_CALLS = frozenset({"open", "FileIO"})

# Call names that are a capability no matter what object they hang off. ``replace`` is
# deliberately absent: ``str.replace`` is used pervasively by legitimate transforms, so
# ``pathlib.Path.replace`` is closed at layer 2 (os.replace is disabled) rather than here.
FORBIDDEN_CALLS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "breakpoint",
        "input",
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "touch",
        "rename",
        "remove",
        "symlink_to",
        "hardlink_to",
        "link_to",
        "chmod",
        "system",
        "popen",
        "startfile",
        "fork",
        "forkpty",
        "kill",
        "killpg",
    }
)
# Any call whose name starts with one of these is a capability (execv, execl, execve,
# spawnl, spawnv, ...). Generated code never calls such a name.
FORBIDDEN_CALL_PREFIXES: tuple[str, ...] = ("exec", "spawn")

# Attribute names that reach a module/object we do not allow, used for the "attribute hop"
# escape (``typing.sys``, ``re.functools.sys``, ``x.__globals__``, ``sys.modules[...]``).
# Every attribute whose name starts with ``_`` is rejected as well; the generated pipelines
# only ever touch public attributes, so this costs nothing and closes the dunder walk.
FORBIDDEN_ATTRS = frozenset(
    {
        "os",
        "sys",
        "posix",
        "nt",
        "ntpath",
        "posixpath",
        "subprocess",
        "builtins",
        "importlib",
        "modules",
        "__builtins__",
        "__import__",
        "__loader__",
        "__spec__",
        "__dict__",
        "__class__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "__globals__",
        "__code__",
        "__closure__",
        "__self__",
        "__func__",
        "__init__",
        "__new__",
        "__getattribute__",
    }
)
# Bare identifiers that must never be referenced at all.
FORBIDDEN_NAMES = frozenset({"__builtins__", "__import__", "__loader__", "__spec__"})

WRITE_MODE_CHARS = frozenset("wax+")
DYNAMIC_MODE = "<dynamic>"


def _module_allowed(name: str, allowed: frozenset[str]) -> bool:
    return name in allowed or any(name.startswith(f"{prefix}.") for prefix in allowed)


def _import_violations(tree: ast.AST, allowed: frozenset[str]) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name, allowed):
                    yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                yield f"{'.' * node.level}{base}", node.lineno
            elif not _module_allowed(base, allowed):
                for alias in node.names:
                    if not _module_allowed(f"{base}.{alias.name}", allowed):
                        yield f"{base}.{alias.name}", node.lineno


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_forbidden_call(name: str) -> bool:
    return name in FORBIDDEN_CALLS or name.startswith(FORBIDDEN_CALL_PREFIXES)


def _attr_forbidden(attr: str) -> bool:
    return attr in FORBIDDEN_ATTRS or attr.startswith("_")


def _mode_position(func: ast.expr) -> int:
    """``open(path, mode)`` / ``io.open(path, mode)`` vs ``Path.open(mode)``."""
    if isinstance(func, ast.Name):
        return 1
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return 1 if func.value.id == "io" else 0
    return 0


def _open_mode(call: ast.Call) -> str:
    position = _mode_position(call.func)
    mode_node: ast.expr | None = call.args[position] if len(call.args) > position else None
    if mode_node is None:
        mode_node = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if mode_node is None:
        return "r"
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return DYNAMIC_MODE


def _call_violations(tree: ast.AST) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in OPEN_LIKE_CALLS:
                mode = _open_mode(node)
                if mode == DYNAMIC_MODE or WRITE_MODE_CHARS & set(mode):
                    yield f"{name}(mode={mode!r})", node.lineno
            elif name is not None and _is_forbidden_call(name):
                yield f"{name}()", node.lineno
        elif isinstance(node, ast.Attribute) and _attr_forbidden(node.attr):
            yield node.attr, node.lineno
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            yield node.id, node.lineno


def scan_source(source: str, allowed: frozenset[str], check: CheckId) -> tuple[Finding, ...]:
    """AST allowlist scan. Any finding means the code must not be executed."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        evidence = {"syntax_error": exc.msg, "lineno": exc.lineno}
        return (
            Finding(
                check=check, severity=Severity.ERROR, message="syntax error", evidence=evidence
            ),
        )
    findings = [
        Finding(
            check=check,
            severity=Severity.ERROR,
            message=f"forbidden import {name!r} (line {lineno})",
            evidence={"forbidden_import": name, "lineno": lineno},
        )
        for name, lineno in _import_violations(tree, allowed)
    ]
    findings.extend(
        Finding(
            check=check,
            severity=Severity.ERROR,
            message=f"forbidden call {desc} (line {lineno})",
            evidence={"forbidden_call": desc, "lineno": lineno},
        )
        for desc, lineno in _call_violations(tree)
    )
    return tuple(findings)


def scan_pipeline(source: str) -> tuple[Finding, ...]:
    return scan_source(source, PIPELINE_ALLOWED_MODULES, CheckId.RUNTIME)


def scan_dag(source: str) -> tuple[Finding, ...]:
    return scan_source(source, DAG_ALLOWED_MODULES, CheckId.DAG_CONTRACT)


__all__ = [
    "DAG_ALLOWED_MODULES",
    "FORBIDDEN_ATTRS",
    "FORBIDDEN_CALLS",
    "FORBIDDEN_NAMES",
    "OPEN_LIKE_CALLS",
    "PIPELINE_ALLOWED_MODULES",
    "scan_dag",
    "scan_pipeline",
    "scan_source",
]
