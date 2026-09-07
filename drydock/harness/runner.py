"""Sandbox entry point and runtime jail (LLD section 4, layer 2).

Usage inside the scratch directory::

    python -I runner.py pipeline.py <sample> dag.py <outdir>

writes ``<outdir>/out.json`` (rows) and ``<outdir>/dag_out.json`` (DAG structure).

Pure stdlib. The harness copies this file next to the generated ``pipeline.py`` /
``dag.py`` and the ``airflow_shim`` package, then executes it in a fresh interpreter.
It is never imported by the orchestrator process. Exit codes: 0 ok, 1 the pipeline stage
raised (traceback on stderr), 2 usage error. DAG import problems never change the exit
code; they are reported through the ``error`` key of ``dag_out.json``.

Before importing the generated ``pipeline.py`` the runner installs an in-process jail:
``open`` is confined to reads inside the work directory, dangerous ``os`` capabilities are
replaced with a raiser, and a denylist of modules is poisoned so importing them fails. The
runner keeps its own references to what it needs (``json``, ``importlib.util``, ``pathlib``,
the real ``open``) before the jail goes up, and writes its outputs through the real ``open``
to the explicitly allowed output directory.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import traceback
from collections.abc import Iterable, Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

EXIT_OK = 0
EXIT_PIPELINE_FAILED = 1
EXIT_USAGE = 2
ARGUMENT_COUNT = 4
USAGE = "usage: runner.py pipeline.py <sample> dag.py <outdir>"
# The sandbox sets this in the child's environment; the jail mutates interpreter globals, so
# it must only run in the throwaway subprocess, never when a unit test calls main() in-process.
JAIL_ENV_VAR = "DRYDOCK_JAIL"
OUT_NAME = "out.json"
DAG_OUT_NAME = "dag_out.json"
WRITE_MODE_CHARS = frozenset("wax+")

# References captured before the jail is installed; the jail must not disturb them.
_REAL_OPEN = builtins.open

# os capabilities disabled in-process (only those that exist on this platform are touched).
_OS_DISABLED: tuple[str, ...] = (
    "system",
    "popen",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "spawnv",
    "spawnve",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "fork",
    "forkpty",
    "kill",
    "killpg",
    "remove",
    "unlink",
    "rename",
    "replace",
    "rmdir",
    "mkdir",
    "makedirs",
    "removedirs",
    "chmod",
    "chown",
    "startfile",
    "open",
    "fdopen",
    "link",
    "symlink",
    "truncate",
    "putenv",
    "unsetenv",
)

# Modules poisoned so ``import <name>`` (or ``__import__``) raises inside generated code.
# ``importlib`` is deliberately absent: the standard library (``dataclasses`` -> ``inspect``
# -> ``importlib.machinery``) needs it, and the static guard already rejects a generated
# ``import importlib`` because it is not on the allowlist.
_POISONED_MODULES: tuple[str, ...] = (
    "subprocess",
    "socket",
    "ssl",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "multiprocessing",
    "ctypes",
    "shutil",
    "tempfile",
    "glob",
    "sqlite3",
    "pickle",
    "shelve",
    "marshal",
    "code",
    "codeop",
    "pty",
    "signal",
    "resource",
    "webbrowser",
)


def _disabled(name: str) -> Any:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError(f"drydock sandbox: {name} is disabled")

    return _raise


def _jailed_open(workdir: Path) -> Any:
    def opener(
        file: Any,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not isinstance(mode, str) or WRITE_MODE_CHARS & set(mode):
            raise PermissionError(f"drydock sandbox: write mode {mode!r} is disabled")
        if isinstance(file, int):
            raise PermissionError("drydock sandbox: opening a raw file descriptor is disabled")
        try:
            resolved = Path(os.fspath(file)).resolve()
        except (TypeError, ValueError) as exc:
            raise PermissionError(f"drydock sandbox: cannot resolve path {file!r}") from exc
        if resolved != workdir and not resolved.is_relative_to(workdir):
            raise PermissionError(f"drydock sandbox: read outside workdir is disabled: {resolved}")
        return _REAL_OPEN(file, mode, *args, **kwargs)

    return opener


class _DenyFinder:
    """Meta-path finder that refuses a fixed denylist, belt-and-braces for late imports."""

    def __init__(self, denied: Iterable[str]) -> None:
        self._denied = frozenset(denied)

    def find_spec(self, fullname: str, _path: Any = None, _target: Any = None) -> None:
        root = fullname.partition(".")[0]
        if root in self._denied:
            raise ImportError(f"drydock sandbox: importing {fullname!r} is disabled")
        return None


def install_jail(workdir: Path) -> None:
    """Confine ``open`` to reads inside ``workdir``, disable os capabilities, poison imports."""
    jailed = _jailed_open(workdir)
    builtins.open = jailed
    io.open = jailed
    for name in _OS_DISABLED:
        if hasattr(os, name):
            setattr(os, name, _disabled(f"os.{name}"))
    sys.meta_path.insert(0, _DenyFinder(_POISONED_MODULES))
    for name in _POISONED_MODULES:
        sys.modules[name] = None  # type: ignore[assignment]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {path}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)  # same semantics as a failed regular import
        raise
    return module


def _write_json(path: Path, payload: Any) -> None:
    with _REAL_OPEN(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")


def run_pipeline(pipeline_path: Path, sample: Path, out_path: Path) -> int:
    """Import ``pipeline.py``, run ``transform(extract(sample))`` and dump the rows."""
    module = _load_module("pipeline", pipeline_path)
    extract = getattr(module, "extract", None)
    transform = getattr(module, "transform", None)
    if not callable(extract) or not callable(transform):
        raise TypeError("pipeline.py must define extract(path) and transform(rows)")
    rows = transform(extract(str(sample)))
    if not isinstance(rows, list):
        raise TypeError(f"transform() must return a list, got {type(rows).__name__}")
    _write_json(out_path, rows)
    return len(rows)


def _empty_dag(error: str) -> dict[str, Any]:
    return {"dag_id": None, "schedule": None, "tasks": [], "edges": [], "error": error}


def run_dag(dag_path: Path, out_path: Path) -> None:
    """Import ``dag.py`` under the shim and dump the first recorded DAG."""
    try:
        _load_module("dag", dag_path)
        import airflow  # the poison denylist does not touch the shim

        dags = airflow.registered_dags()
        payload = dags[0].to_dict() if dags else _empty_dag("dag.py did not instantiate a DAG")
    except Exception:  # any failure is evidence for H6, not a crash
        payload = _empty_dag(traceback.format_exc())
    _write_json(out_path, payload)


def main(argv: list[str]) -> int:
    if len(argv) != ARGUMENT_COUNT:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    here = Path(__file__).resolve().parent
    sys.path[:0] = [str(here / "airflow_shim"), str(here)]
    sys.dont_write_bytecode = True
    pipeline_path, sample, dag_path, outdir = (Path(arg) for arg in argv)
    out_path = outdir / OUT_NAME
    dag_out = outdir / DAG_OUT_NAME
    if os.environ.get(JAIL_ENV_VAR) == "1":
        install_jail(here)
    failed = False
    try:
        run_pipeline(pipeline_path, sample, out_path)
    except BaseException:  # reported to the parent via stderr + exit code
        traceback.print_exc()
        failed = True
    run_dag(dag_path, dag_out)
    return EXIT_PIPELINE_FAILED if failed else EXIT_OK


def _cli(argv: Sequence[str]) -> int:
    return main(list(argv))


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
