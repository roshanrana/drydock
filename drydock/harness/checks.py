"""Static AST guard and the six harness checks (LLD section 4).

Everything here is a pure function over source text or sandbox output. Nothing imports
or executes generated code; the guard runs before ``runner.py`` is ever spawned.
"""

from __future__ import annotations

import ast
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from drydock.harness.sandbox import SandboxResult
from drydock.models import (
    CANONICAL_COLUMNS,
    CheckId,
    CheckResult,
    FeedSpec,
    Finding,
    SampleProfile,
    Severity,
)

PIPELINE_ALLOWED_MODULES = frozenset(
    {
        "__future__",
        "csv",
        "json",
        "decimal",
        "datetime",
        "re",
        "io",
        "os.path",
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
        "rmdir",
        "touch",
        "rename",
        "symlink_to",
        "hardlink_to",
        "chmod",
    }
)
FORBIDDEN_DUNDERS = frozenset(
    {"__builtins__", "__import__", "__subclasses__", "__globals__", "__code__", "__loader__"}
)
WRITE_MODE_CHARS = frozenset("wax+")
DYNAMIC_MODE = "<dynamic>"
TRACEBACK_MARKER = "Traceback (most recent call last)"
AMOUNT_RE = re.compile(r"^-?\d+\.\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
EXPECTED_TASKS: tuple[str, ...] = ("extract", "transform", "load")
EXPECTED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {("extract", "transform"), ("transform", "load")}
)
SUM_TOLERANCE = Decimal("0.005")
LATENCY_WARNING_FRACTION = 0.5
MAX_EVIDENCE_ROWS = 3
STDERR_TAIL_CHARS = 2000


@dataclass(frozen=True)
class SampleRun:
    """Everything the checks need to know about one sandbox execution."""

    name: str
    profile: SampleProfile | None
    result: SandboxResult
    rows: list[Any] | None
    dag: dict[str, Any] | None
    error: str | None = None


# --------------------------------------------------------------------------- #
# Static guard                                                                 #
# --------------------------------------------------------------------------- #


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
            elif name in FORBIDDEN_CALLS:
                yield f"{name}()", node.lineno
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_DUNDERS:
            yield node.attr, node.lineno
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_DUNDERS:
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


# --------------------------------------------------------------------------- #
# Check helpers                                                                #
# --------------------------------------------------------------------------- #


def _finding(check: CheckId, message: str, **evidence: Any) -> Finding:
    return Finding(check=check, severity=Severity.ERROR, message=message, evidence=evidence)


def _warning(check: CheckId, message: str, **evidence: Any) -> Finding:
    return Finding(check=check, severity=Severity.WARNING, message=message, evidence=evidence)


def _result(check: CheckId, findings: Sequence[Finding], *, skipped: bool = False) -> CheckResult:
    has_error = any(f.severity == Severity.ERROR for f in findings)
    return CheckResult(check=check, passed=not has_error and not skipped, findings=tuple(findings))


def _skipped(check: CheckId, reason: str) -> CheckResult:
    return _result(check, [_warning(check, f"skipped: {reason}")], skipped=True)


def _executed(runs: Sequence[SampleRun]) -> list[SampleRun]:
    return [run for run in runs if run.rows is not None]


def _dict_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict)]


# --------------------------------------------------------------------------- #
# H1 runtime                                                                   #
# --------------------------------------------------------------------------- #


def _runtime_reasons(run: SampleRun) -> list[str]:
    reasons: list[str] = []
    if run.result.timed_out:
        reasons.append("timed out")
    if run.result.exit_code != 0 and not run.result.timed_out:
        reasons.append(f"exit code {run.result.exit_code}")
    if TRACEBACK_MARKER in run.result.stderr:
        reasons.append("traceback on stderr")
    if run.rows is None:
        reasons.append(run.error or "out.json missing")
    return reasons


def check_runtime(runs: Sequence[SampleRun], static: Sequence[Finding]) -> CheckResult:
    if not static and not runs:
        return _skipped(CheckId.RUNTIME, "nothing was executed (dag.py guard hit or no samples)")
    findings = list(static)
    for run in runs:
        reasons = _runtime_reasons(run)
        if not reasons:
            continue
        findings.append(
            _finding(
                CheckId.RUNTIME,
                f"{run.name}: {'; '.join(reasons)}",
                sample=run.name,
                reasons=reasons,
                exit_code=run.result.exit_code,
                timed_out=run.result.timed_out,
                wall_ms=run.result.wall_ms,
                stderr_tail=run.result.stderr[-STDERR_TAIL_CHARS:],
            )
        )
    duration = sum(run.result.wall_ms for run in runs)
    return _result(CheckId.RUNTIME, findings).model_copy(update={"duration_ms": duration})


# --------------------------------------------------------------------------- #
# H2 schema                                                                    #
# --------------------------------------------------------------------------- #


def _valid_date(value: str) -> bool:
    if not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def row_violation(row: Any) -> str | None:
    """Return why ``row`` violates the canonical contract, or None when it is clean."""
    if not isinstance(row, dict):
        return f"row is {type(row).__name__}, not dict"
    if tuple(row.keys()) != CANONICAL_COLUMNS:
        return "keys differ from CANONICAL_COLUMNS"
    for key, value in row.items():
        if not isinstance(value, str):
            return f"{key} is {type(value).__name__}, not str"
    if not AMOUNT_RE.fullmatch(row["amount"]):
        return f"amount {row['amount']!r} is not a signed 2dp decimal string"
    if not _valid_date(row["value_date"]):
        return f"value_date {row['value_date']!r} is not YYYY-MM-DD"
    if not CURRENCY_RE.fullmatch(row["currency"]):
        return f"currency {row['currency']!r} is not ISO-4217 upper-case"
    return None


def check_schema(runs: Sequence[SampleRun]) -> CheckResult:
    executed = _executed(runs)
    if not executed:
        return _skipped(CheckId.SCHEMA, "no sandbox output to inspect")
    findings: list[Finding] = []
    for run in executed:
        offending = [
            {"index": index, "reason": reason, "row": row}
            for index, row in enumerate(run.rows or [])
            if (reason := row_violation(row)) is not None
        ]
        if offending:
            findings.append(
                _finding(
                    CheckId.SCHEMA,
                    f"{run.name}: {len(offending)} row(s) violate the canonical schema",
                    sample=run.name,
                    violations=len(offending),
                    offending_rows=offending[:MAX_EVIDENCE_ROWS],
                )
            )
    return _result(CheckId.SCHEMA, findings)


# --------------------------------------------------------------------------- #
# H3 completeness                                                              #
# --------------------------------------------------------------------------- #


def check_completeness(runs: Sequence[SampleRun]) -> CheckResult:
    executed = _executed(runs)
    if not executed:
        return _skipped(CheckId.COMPLETENESS, "no sandbox output to inspect")
    findings: list[Finding] = []
    for run in executed:
        actual = len(run.rows or [])
        if run.profile is None:
            findings.append(
                _finding(
                    CheckId.COMPLETENESS,
                    f"{run.name}: no SampleProfile in manifest",
                    sample=run.name,
                    actual=actual,
                )
            )
        elif actual != run.profile.expected_rows:
            findings.append(
                _finding(
                    CheckId.COMPLETENESS,
                    f"{run.name}: expected {run.profile.expected_rows} rows, got {actual}",
                    sample=run.name,
                    expected=run.profile.expected_rows,
                    actual=actual,
                )
            )
    return _result(CheckId.COMPLETENESS, findings)


# --------------------------------------------------------------------------- #
# H4 drift                                                                     #
# --------------------------------------------------------------------------- #


def _amount_sum(rows: Sequence[dict[str, Any]]) -> tuple[Decimal, int]:
    total = Decimal("0")
    unparseable = 0
    for row in rows:
        try:
            total += Decimal(str(row.get("amount")))
        except InvalidOperation:
            unparseable += 1
    return total, unparseable


def _null_rate(rows: Sequence[dict[str, Any]], column: str) -> float:
    if not rows:
        return 0.0
    nulls = sum(1 for row in rows if row.get(column) in (None, ""))
    return nulls / len(rows)


def _distinct(rows: Sequence[dict[str, Any]], column: str) -> int:
    return len(
        {
            value if isinstance(value, str) else repr(value)
            for value in (r.get(column) for r in rows)
        }
    )


def _drift_findings(run: SampleRun, profile: SampleProfile, tolerance: float) -> list[Finding]:
    rows = _dict_rows(run.rows or [])
    findings: list[Finding] = []
    actual_sum, unparseable = _amount_sum(rows)
    expected_sum = Decimal(profile.amount_sum)
    if abs(actual_sum - expected_sum) > SUM_TOLERANCE:
        findings.append(
            _finding(
                CheckId.DRIFT,
                f"{run.name}: amount sum {actual_sum} differs from baseline {expected_sum}",
                sample=run.name,
                expected_sum=str(expected_sum),
                actual_sum=str(actual_sum),
                unparseable_amounts=unparseable,
            )
        )
    for column, expected in profile.null_rate.items():
        observed = _null_rate(rows, column)
        if abs(observed - expected) > tolerance:
            findings.append(
                _finding(
                    CheckId.DRIFT,
                    f"{run.name}: null rate of {column} is {observed:.4f}, baseline {expected:.4f}",
                    sample=run.name,
                    column=column,
                    expected=expected,
                    observed=observed,
                    tolerance=tolerance,
                )
            )
    for column, expected_count in profile.distinct.items():
        observed_count = _distinct(rows, column)
        if observed_count != expected_count:
            findings.append(
                _finding(
                    CheckId.DRIFT,
                    f"{run.name}: {observed_count} distinct {column}, baseline {expected_count}",
                    sample=run.name,
                    column=column,
                    expected=expected_count,
                    observed=observed_count,
                )
            )
    return findings


def check_drift(runs: Sequence[SampleRun], tolerance: float) -> CheckResult:
    executed = _executed(runs)
    if not executed:
        return _skipped(CheckId.DRIFT, "no sandbox output to inspect")
    findings: list[Finding] = []
    skipped = False
    for run in executed:
        if run.profile is None:
            findings.append(_warning(CheckId.DRIFT, f"skipped: {run.name} has no SampleProfile"))
            skipped = True
            continue
        findings.extend(_drift_findings(run, run.profile, tolerance))
    return _result(CheckId.DRIFT, findings, skipped=skipped)


# --------------------------------------------------------------------------- #
# H5 latency                                                                   #
# --------------------------------------------------------------------------- #


def check_latency(runs: Sequence[SampleRun], budget_ms: int) -> CheckResult:
    executed = _executed(runs)
    if not executed:
        return _skipped(CheckId.LATENCY, "no completed sandbox run to time")
    findings: list[Finding] = []
    for run in executed:
        wall = run.result.wall_ms
        evidence = {"sample": run.name, "wall_ms": wall, "budget_ms": budget_ms}
        if wall > budget_ms:
            findings.append(
                _finding(CheckId.LATENCY, f"{run.name}: {wall} ms > budget", **evidence)
            )
        elif wall > budget_ms * LATENCY_WARNING_FRACTION:
            findings.append(
                _warning(CheckId.LATENCY, f"{run.name}: {wall} ms > 50% of budget", **evidence)
            )
    return _result(CheckId.LATENCY, findings)


# --------------------------------------------------------------------------- #
# H6 dag contract                                                              #
# --------------------------------------------------------------------------- #


def _dag_mismatches(dag: dict[str, Any], spec: FeedSpec) -> list[Finding]:
    expected_id = f"{spec.client}__{spec.feed_name}"
    edges = {tuple(edge) for edge in dag.get("edges", []) if len(edge) == 2}
    comparisons: list[tuple[str, Any, Any]] = [
        ("dag_id", expected_id, dag.get("dag_id")),
        ("schedule", spec.schedule_cron, dag.get("schedule")),
        ("tasks", sorted(EXPECTED_TASKS), sorted(str(t) for t in dag.get("tasks", []))),
        ("edges", sorted(list(e) for e in EXPECTED_EDGES), sorted(list(e) for e in edges)),
    ]
    return [
        _finding(
            CheckId.DAG_CONTRACT,
            f"{field} differs from contract",
            field=field,
            expected=expected,
            actual=actual,
        )
        for field, expected, actual in comparisons
        if expected != actual
    ]


def check_dag_contract(
    runs: Sequence[SampleRun], spec: FeedSpec, static: Sequence[Finding]
) -> CheckResult:
    if static:
        return _result(CheckId.DAG_CONTRACT, list(static))
    dags = [run.dag for run in runs if run.dag is not None]
    if not dags:
        return _skipped(CheckId.DAG_CONTRACT, "dag_out.json was not produced")
    imported = next((dag for dag in dags if not dag.get("error")), None)
    if imported is not None:
        return _result(CheckId.DAG_CONTRACT, _dag_mismatches(imported, spec))
    error = str(dags[0]["error"])
    if any(_runtime_reasons(run) for run in runs):
        # dag.py imports pipeline; when the pipeline stage failed the DAG failure is a
        # consequence of H1, so it is reported as a warning rather than a second error.
        return _result(
            CheckId.DAG_CONTRACT,
            [_warning(CheckId.DAG_CONTRACT, "skipped: dag.py import failed after H1", error=error)],
            skipped=True,
        )
    return _result(
        CheckId.DAG_CONTRACT,
        [_finding(CheckId.DAG_CONTRACT, "dag.py failed to import", error=error)],
    )


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #


def _timed(build: Callable[[], CheckResult]) -> CheckResult:
    started = time.perf_counter()
    result = build()
    elapsed = int((time.perf_counter() - started) * 1000)
    return result.model_copy(update={"duration_ms": result.duration_ms + elapsed})


def run_checks(
    runs: Sequence[SampleRun],
    spec: FeedSpec,
    pipeline_findings: Sequence[Finding],
    dag_findings: Sequence[Finding],
    *,
    latency_budget_ms: int,
    drift_tolerance: float,
) -> tuple[CheckResult, ...]:
    """The six CheckResults, always in CheckId order."""
    return (
        _timed(lambda: check_runtime(runs, pipeline_findings)),
        _timed(lambda: check_schema(runs)),
        _timed(lambda: check_completeness(runs)),
        _timed(lambda: check_drift(runs, drift_tolerance)),
        _timed(lambda: check_latency(runs, latency_budget_ms)),
        _timed(lambda: check_dag_contract(runs, spec, dag_findings)),
    )


__all__ = [
    "DAG_ALLOWED_MODULES",
    "PIPELINE_ALLOWED_MODULES",
    "SampleRun",
    "check_completeness",
    "check_dag_contract",
    "check_drift",
    "check_latency",
    "check_runtime",
    "check_schema",
    "row_violation",
    "run_checks",
    "scan_dag",
    "scan_pipeline",
    "scan_source",
]
