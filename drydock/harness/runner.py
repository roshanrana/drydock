"""Sandbox entry point (LLD section 4).

Usage inside the scratch directory::

    python -I runner.py pipeline.py <sample> out.json dag.py dag_out.json

Pure stdlib. The harness copies this file next to the generated ``pipeline.py`` /
``dag.py`` and the ``airflow_shim`` package, then executes it in a fresh interpreter.
It is never imported by the orchestrator process. Exit codes: 0 ok, 1 the pipeline stage
raised (traceback on stderr), 2 usage error. DAG import problems never change the exit
code; they are reported through the ``error`` key of ``dag_out.json``.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

EXIT_OK = 0
EXIT_PIPELINE_FAILED = 1
EXIT_USAGE = 2
ARGUMENT_COUNT = 5
USAGE = "usage: runner.py pipeline.py <sample> out.json dag.py dag_out.json"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)  # same semantics as a failed regular import
        raise
    return module


def _write_json(path: Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
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
        shim = importlib.import_module("airflow")
        dags = shim.registered_dags()
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
    pipeline_path, sample, out_path, dag_path, dag_out = (Path(arg) for arg in argv)
    failed = False
    try:
        run_pipeline(pipeline_path, sample, out_path)
    except Exception:  # reported to the parent via stderr + exit code
        traceback.print_exc()
        failed = True
    run_dag(dag_path, dag_out)
    return EXIT_PIPELINE_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
