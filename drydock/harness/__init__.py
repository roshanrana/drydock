"""Deterministic judge: run a PipelineArtifact in a sandbox and score it (LLD section 4).

``evaluate`` is the only entry point other components need. Generated code is never
imported here; it is written to a scratch directory and executed by ``runner.py`` in a
separate interpreter, after the static AST guard has approved it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Protocol

from drydock.harness import checks
from drydock.harness.checks import SampleRun
from drydock.harness.sandbox import (
    SandboxError,
    SandboxKind,
    SandboxResult,
    SandboxTimeout,
    python_argv,
    run_in_sandbox,
)
from drydock.models import FeedSpec, HarnessReport, PipelineArtifact, SampleProfile, Severity

HARNESS_DIR = Path(__file__).resolve().parent
RUNNER_PATH = HARNESS_DIR / "runner.py"
SHIM_DIR = HARNESS_DIR / "airflow_shim"
PIPELINE_FILE = "pipeline.py"
DAG_FILE = "dag.py"
OUT_FILE = "out.json"
DAG_OUT_FILE = "dag_out.json"
OUTDIR_NAME = "__out__"  # docker: a writable mount separate from the read-only work dir
DOCKER_OUTDIR = "/out"


class ManifestLike(Protocol):
    """Anything exposing the sample baselines; ``drydock.corpus.Manifest`` (T-001) fits."""

    @property
    def samples(self) -> Sequence[SampleProfile]: ...


def evaluate(
    artifact: PipelineArtifact,
    spec: FeedSpec,
    manifest: ManifestLike,
    samples: list[Path],
    *,
    iteration: int,
    sandbox: Literal["subprocess", "docker"] = "subprocess",
    timeout_s: float = 30.0,
    latency_budget_ms: int = 5000,
    drift_tolerance: float = 0.05,
    workdir: Path | None = None,
) -> HarnessReport:
    """Judge one artifact against every sample. Never raises for bad generated code."""
    started = time.perf_counter()
    pipeline_findings = checks.scan_pipeline(artifact.pipeline_py)
    dag_findings = checks.scan_dag(artifact.dag_py)
    runs: list[SampleRun] = []
    if not pipeline_findings and not dag_findings:
        with _scratch(workdir) as root:
            runs = [
                _run_sample(
                    root, index, artifact, sample, manifest, kind=sandbox, timeout_s=timeout_s
                )
                for index, sample in enumerate(samples)
            ]
    results = checks.run_checks(
        runs,
        spec,
        pipeline_findings,
        dag_findings,
        latency_budget_ms=latency_budget_ms,
        drift_tolerance=drift_tolerance,
    )
    has_error = any(f.severity == Severity.ERROR for c in results for f in c.findings)
    return HarnessReport(
        iteration=iteration,
        passed=not has_error,
        checks=results,
        rows_emitted=sum(len(run.rows) for run in runs if run.rows is not None),
        wall_ms=int((time.perf_counter() - started) * 1000),
        sandbox=sandbox,
    )


@contextmanager
def _scratch(workdir: Path | None) -> Iterator[Path]:
    """Caller-provided workdir is kept (evidence); a temp dir is removed afterwards."""
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        yield workdir
        return
    with tempfile.TemporaryDirectory(prefix="drydock-", ignore_cleanup_errors=True) as tmp:
        yield Path(tmp)


def _write_source(path: Path, source: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)


def _stage(scratch: Path, artifact: PipelineArtifact, sample: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    _write_source(scratch / PIPELINE_FILE, artifact.pipeline_py)
    _write_source(scratch / DAG_FILE, artifact.dag_py)
    shutil.copy2(sample, scratch / sample.name)
    shutil.copy2(RUNNER_PATH, scratch / RUNNER_PATH.name)
    shutil.copytree(
        SHIM_DIR,
        scratch / SHIM_DIR.name,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )


def _read_rows(path: Path) -> tuple[list[Any] | None, str | None]:
    if not path.is_file():
        return None, f"{path.name} missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name} unreadable: {exc}"
    if not isinstance(payload, list):
        return None, f"{path.name} is not a JSON list"
    return payload, None


def _read_dag(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _profile_for(manifest: ManifestLike, name: str) -> SampleProfile | None:
    return next((p for p in manifest.samples if p.name == name), None)


def _run_sample(
    root: Path,
    index: int,
    artifact: PipelineArtifact,
    sample: Path,
    manifest: ManifestLike,
    *,
    kind: SandboxKind,
    timeout_s: float,
) -> SampleRun:
    scratch = root / f"{index:02d}_{sample.stem}"
    _stage(scratch, artifact, sample)
    if kind == "docker":
        out_host = scratch / OUTDIR_NAME
        out_host.mkdir(parents=True, exist_ok=True)
        outdir_arg = DOCKER_OUTDIR
    else:
        out_host = scratch
        outdir_arg = "."
    argv = [
        *python_argv(kind),
        RUNNER_PATH.name,
        PIPELINE_FILE,
        sample.name,
        DAG_FILE,
        outdir_arg,
    ]
    result: SandboxResult = run_in_sandbox(
        scratch, argv, timeout_s=timeout_s, kind=kind, outdir=out_host
    )
    rows, error = _read_rows(out_host / OUT_FILE)
    return SampleRun(
        name=sample.name,
        profile=_profile_for(manifest, sample.name),
        result=result,
        rows=rows,
        dag=_read_dag(out_host / DAG_OUT_FILE),
        error=error,
    )


__all__ = [
    "ManifestLike",
    "SandboxError",
    "SandboxResult",
    "SandboxTimeout",
    "evaluate",
    "run_in_sandbox",
]
