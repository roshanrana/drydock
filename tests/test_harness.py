"""Tests for drydock.harness: sandbox, static guard, the six checks, runner and Airflow shim.

Fixtures live under tests/fixtures/pipelines (own spec, sample and pipelines); nothing here
depends on corpus/ or drydock/corpus.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from drydock import corpus
from drydock.harness import ManifestLike, SandboxError, checks, evaluate, runner, sandbox
from drydock.harness.checks import SampleRun
from drydock.harness.sandbox import SandboxResult, run_in_sandbox
from drydock.models import (
    CANONICAL_COLUMNS,
    CheckId,
    CheckResult,
    HarnessReport,
    IngestionPlan,
    PipelineArtifact,
    Severity,
)
from drydock.providers.fake import (
    FakeProvider,
    parse_options_from_spec,
    validations_from_spec,
)
from tests.fixtures.manifest_stub import (
    AMOUNT_SUM,
    EXPECTED_ROWS,
    FIXTURES,
    SAMPLE,
    ManifestStub,
    make_manifest,
    make_spec,
    profile_for,
)

FAST_TIMEOUT_S = 20.0
DATA_CHECKS = (
    CheckId.SCHEMA,
    CheckId.COMPLETENESS,
    CheckId.DRIFT,
    CheckId.LATENCY,
    CheckId.DAG_CONTRACT,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_artifact(
    pipeline: str = "good_pipeline.py",
    dag: str = "good_dag.py",
    *,
    pipeline_source: str | None = None,
    dag_source: str | None = None,
) -> PipelineArtifact:
    return PipelineArtifact(
        pipeline_py=pipeline_source if pipeline_source is not None else fixture(pipeline),
        dag_py=dag_source if dag_source is not None else fixture(dag),
        mapping_yaml="client: acme\nfeed: ledger\nformat: csv\nfields: []\n",
        iteration=1,
        generator="test",
    )


def judge(
    artifact: PipelineArtifact,
    *,
    samples: Sequence[Path] | None = None,
    manifest: ManifestLike | None = None,
    **kwargs: Any,
) -> HarnessReport:
    kwargs.setdefault("timeout_s", FAST_TIMEOUT_S)
    return evaluate(
        artifact,
        make_spec(),
        manifest if manifest is not None else make_manifest(),
        list(samples or [SAMPLE]),
        iteration=1,
        **kwargs,
    )


def failing_checks(report: HarnessReport) -> set[CheckId]:
    return {f.check for f in report.errors}


def result_for(report: HarnessReport, check: CheckId) -> CheckResult:
    return next(c for c in report.checks if c.check == check)


def canonical_row(index: int, amount: str = "10.00") -> dict[str, str]:
    values = (f"T{index:03d}", "A1", "2025-01-03", amount, "USD", "Globex", "memo")
    return dict(zip(CANONICAL_COLUMNS, values, strict=True))


def sandbox_result(**overrides: Any) -> SandboxResult:
    base: dict[str, Any] = {
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "wall_ms": 10,
        "timed_out": False,
    }
    return SandboxResult(**{**base, **overrides})


def make_run(rows: list[Any] | None, **overrides: Any) -> SampleRun:
    base: dict[str, Any] = {
        "name": SAMPLE.name,
        "profile": profile_for(SAMPLE),
        "result": sandbox_result(),
        "rows": rows,
        "dag": None,
        "error": None,
    }
    return SampleRun(**{**base, **overrides})


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


# --------------------------------------------------------------------------- #
# evaluate(): end-to-end through the subprocess sandbox                        #
# --------------------------------------------------------------------------- #


def test_good_pipeline_passes_every_check() -> None:
    report = judge(make_artifact())

    assert report.passed
    assert report.errors == ()
    assert [c.check for c in report.checks] == list(CheckId)
    assert all(c.passed for c in report.checks)
    assert report.rows_emitted == EXPECTED_ROWS
    assert report.sandbox == "subprocess"
    assert report.iteration == 1
    assert report.wall_ms >= result_for(report, CheckId.RUNTIME).duration_ms


def test_workdir_is_kept_and_shim_records_dag_structure(tmp_path: Path) -> None:
    report = judge(make_artifact(), workdir=tmp_path)

    scratch = tmp_path / "00_acme_ledger"
    assert report.passed
    for name in ("pipeline.py", "dag.py", "runner.py", "out.json", "dag_out.json", SAMPLE.name):
        assert (scratch / name).is_file()
    assert (scratch / "airflow_shim" / "airflow" / "operators" / "python.py").is_file()
    dag_out = json.loads((scratch / "dag_out.json").read_text(encoding="utf-8"))
    assert dag_out == {
        "dag_id": "acme__ledger",
        "schedule": "0 6 * * 1-5",
        "tasks": ["extract", "transform", "load"],
        "edges": [["extract", "transform"], ["transform", "load"]],
    }
    rows = json.loads((scratch / "out.json").read_text(encoding="utf-8"))
    assert [tuple(r) for r in rows] == [CANONICAL_COLUMNS] * EXPECTED_ROWS


def test_generated_code_never_enters_the_orchestrator_process() -> None:
    judge(make_artifact())

    for name in ("pipeline", "dag", "airflow", "airflow.operators.python"):
        assert name not in sys.modules


def test_multiple_samples_are_all_evaluated(tmp_path: Path) -> None:
    second = tmp_path / "second_ledger.csv"
    shutil.copy(SAMPLE, second)

    report = judge(
        make_artifact(), samples=[SAMPLE, second], manifest=make_manifest(SAMPLE, second)
    )

    assert report.passed
    assert report.rows_emitted == 2 * EXPECTED_ROWS


@pytest.mark.parametrize(
    ("pipeline", "dag", "expected"),
    [
        ("bad_h2_schema_pipeline.py", "good_dag.py", CheckId.SCHEMA),
        ("bad_h3_completeness_pipeline.py", "good_dag.py", CheckId.COMPLETENESS),
        ("bad_h4_drift_pipeline.py", "good_dag.py", CheckId.DRIFT),
        ("good_pipeline.py", "bad_h6_dag.py", CheckId.DAG_CONTRACT),
    ],
)
def test_each_bad_fixture_fails_exactly_one_check(
    pipeline: str, dag: str, expected: CheckId
) -> None:
    report = judge(make_artifact(pipeline, dag))

    assert not report.passed
    assert failing_checks(report) == {expected}


def test_h2_evidence_lists_at_most_three_offending_rows() -> None:
    report = judge(make_artifact("bad_h2_schema_pipeline.py"))

    finding = result_for(report, CheckId.SCHEMA).findings[0]
    # 4 of the 6 amounts lose their trailing zero (99.99 and 10.01 stay well-formed).
    assert finding.evidence["violations"] == 4
    assert len(finding.evidence["offending_rows"]) == 3
    assert finding.evidence["offending_rows"][0]["row"]["amount"] == "1250"


def test_h3_evidence_reports_expected_and_actual() -> None:
    report = judge(make_artifact("bad_h3_completeness_pipeline.py"))

    finding = result_for(report, CheckId.COMPLETENESS).findings[0]
    assert finding.evidence["expected"] == EXPECTED_ROWS
    assert finding.evidence["actual"] == EXPECTED_ROWS - 1


def test_h4_evidence_reports_both_sums() -> None:
    report = judge(make_artifact("bad_h4_drift_pipeline.py"))

    finding = result_for(report, CheckId.DRIFT).findings[0]
    assert finding.evidence["expected_sum"] == AMOUNT_SUM
    assert finding.evidence["actual_sum"] == "-339.50"


def test_h5_slow_pipeline_fails_only_latency() -> None:
    report = judge(make_artifact("bad_h5_latency_pipeline.py"), latency_budget_ms=200)

    assert failing_checks(report) == {CheckId.LATENCY}
    finding = result_for(report, CheckId.LATENCY).findings[0]
    assert finding.evidence["budget_ms"] == 200
    assert finding.evidence["wall_ms"] > 200


def test_h6_evidence_shows_missing_edge() -> None:
    report = judge(make_artifact(dag="bad_h6_dag.py"))

    finding = result_for(report, CheckId.DAG_CONTRACT).findings[0]
    assert finding.evidence["field"] == "edges"
    assert finding.evidence["actual"] == [["extract", "transform"]]


def test_h6_wrong_dag_id_and_schedule() -> None:
    dag_source = (
        fixture("good_dag.py")
        .replace('"acme__ledger"', '"wrong"')
        .replace('"0 6 * * 1-5"', '"@daily"')
    )
    report = judge(make_artifact(dag_source=dag_source))

    fields = {f.evidence["field"] for f in result_for(report, CheckId.DAG_CONTRACT).findings}
    assert failing_checks(report) == {CheckId.DAG_CONTRACT}
    assert fields == {"dag_id", "schedule"}


def test_h6_dag_import_error_is_reported_not_crashed() -> None:
    report = judge(
        make_artifact(dag_source=fixture("good_dag.py") + '\nraise RuntimeError("dag boom")\n')
    )

    assert failing_checks(report) == {CheckId.DAG_CONTRACT}
    finding = result_for(report, CheckId.DAG_CONTRACT).findings[0]
    assert "dag boom" in finding.evidence["error"]
    assert result_for(report, CheckId.RUNTIME).passed


def test_h6_forbidden_import_in_dag_blocks_execution(tmp_path: Path) -> None:
    report = judge(
        make_artifact(dag_source="import os\n" + fixture("good_dag.py")), workdir=tmp_path
    )

    assert failing_checks(report) == {CheckId.DAG_CONTRACT}
    finding = result_for(report, CheckId.DAG_CONTRACT).findings[0]
    assert finding.evidence["forbidden_import"] == "os"
    assert list(tmp_path.iterdir()) == []
    assert not result_for(report, CheckId.RUNTIME).passed  # skipped, not silently green


# --------------------------------------------------------------------------- #
# H1: static guard, runtime failures and timeouts                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("snippet", "key", "value"),
    [
        ("import socket\n", "forbidden_import", "socket"),
        ("import requests\n", "forbidden_import", "requests"),
        ("import subprocess\n", "forbidden_import", "subprocess"),
        ('open("marker.txt", "w").write("x")\n', "forbidden_call", "open(mode='w')"),
    ],
)
def test_static_guard_is_h1_error_and_code_is_not_executed(
    tmp_path: Path, snippet: str, key: str, value: str
) -> None:
    artifact = make_artifact(pipeline_source=snippet + fixture("good_pipeline.py"))

    report = judge(artifact, workdir=tmp_path)

    runtime = result_for(report, CheckId.RUNTIME)
    assert not report.passed
    assert failing_checks(report) == {CheckId.RUNTIME}
    assert any(f.evidence.get(key) == value for f in runtime.findings)
    assert list(tmp_path.iterdir()) == []
    for check in DATA_CHECKS:
        result = result_for(report, check)
        assert not result.passed
        assert [f.severity for f in result.findings] == [Severity.WARNING]


def test_timeout_is_h1_error_with_timed_out_evidence() -> None:
    artifact = make_artifact(
        pipeline_source="import time\ntime.sleep(5)\n" + fixture("good_pipeline.py")
    )

    report = judge(artifact, timeout_s=0.5)

    runtime = result_for(report, CheckId.RUNTIME)
    assert failing_checks(report) == {CheckId.RUNTIME}
    assert runtime.findings[0].evidence["timed_out"] is True
    assert "timed out" in runtime.findings[0].evidence["reasons"]
    assert not result_for(report, CheckId.LATENCY).passed


def test_pipeline_exception_is_h1_error_with_traceback() -> None:
    artifact = make_artifact(pipeline_source='raise ValueError("boom")\n')

    report = judge(artifact)

    finding = result_for(report, CheckId.RUNTIME).findings[0]
    dag_contract = result_for(report, CheckId.DAG_CONTRACT)
    assert failing_checks(report) == {CheckId.RUNTIME}
    # dag.py imports the broken pipeline; that follow-on failure is a warning, not H6 noise.
    assert not dag_contract.passed
    assert [f.severity for f in dag_contract.findings] == [Severity.WARNING]
    assert finding.evidence["exit_code"] == runner.EXIT_PIPELINE_FAILED
    assert "traceback on stderr" in finding.evidence["reasons"]
    assert "out.json missing" in finding.evidence["reasons"]
    assert "boom" in finding.evidence["stderr_tail"]


def test_transform_not_returning_a_list_is_h1_error() -> None:
    source = fixture("good_pipeline.py").replace("    return out\n", "    return {'rows': out}\n")

    report = judge(make_artifact(pipeline_source=source))

    assert failing_checks(report) == {CheckId.RUNTIME}
    assert (
        "must return a list"
        in result_for(report, CheckId.RUNTIME).findings[0].evidence["stderr_tail"]
    )


def test_missing_profile_is_h3_error_and_h4_skipped() -> None:
    report = judge(make_artifact(), manifest=ManifestStub(samples=()))

    assert failing_checks(report) == {CheckId.COMPLETENESS}
    drift = result_for(report, CheckId.DRIFT)
    assert not drift.passed
    assert all(f.severity == Severity.WARNING for f in drift.findings)


# --------------------------------------------------------------------------- #
# Static guard unit tests                                                      #
# --------------------------------------------------------------------------- #


def test_scan_pipeline_accepts_allowlisted_constructs() -> None:
    source = (
        "from __future__ import annotations\n"
        "import csv, json, io\n"
        "import collections.abc\n"
        "from pathlib import Path\n"
        "def f(p):\n"
        "    open(p, encoding='utf-8'); open(p); Path(p).open(); io.open(p, 'r')\n"
        "    return 'a'.replace('a', 'b')\n"
    )
    assert checks.scan_pipeline(source) == ()


@pytest.mark.parametrize(
    ("source", "key", "value"),
    [
        ("import os\n", "forbidden_import", "os"),
        ("from os import system\n", "forbidden_import", "os.system"),
        ("from . import sibling\n", "forbidden_import", "."),
        ("import sys\n", "forbidden_import", "sys"),
        ("from pathlib import Path\nPath('x').write_text('y')\n", "forbidden_call", "write_text()"),
        ("from pathlib import Path\nPath('x').open('w')\n", "forbidden_call", "open(mode='w')"),
        ("open('x', mode)\n", "forbidden_call", "open(mode='<dynamic>')"),
        ("open('x', mode='a')\n", "forbidden_call", "open(mode='a')"),
        ("import io\nio.open('x', 'r+')\n", "forbidden_call", "open(mode='r+')"),
        ("import io\nio.FileIO('x', 'w')\n", "forbidden_call", "FileIO(mode='w')"),
        ("eval('1')\n", "forbidden_call", "eval()"),
        ("__import__('os')\n", "forbidden_call", "__import__()"),
        ("().__class__.__subclasses__()\n", "forbidden_call", "__subclasses__"),
    ],
)
def test_scan_pipeline_rejects(source: str, key: str, value: str) -> None:
    findings = checks.scan_pipeline(source)

    assert findings
    assert all(f.check == CheckId.RUNTIME and f.severity == Severity.ERROR for f in findings)
    assert any(f.evidence.get(key) == value for f in findings)


def test_scan_syntax_error_is_a_finding() -> None:
    findings = checks.scan_pipeline("def (:\n")

    assert len(findings) == 1
    assert "syntax_error" in findings[0].evidence
    assert findings[0].evidence["lineno"] == 1


def test_scan_dag_allowlist() -> None:
    clean = (
        "from datetime import datetime\nfrom airflow import DAG\n"
        "from airflow.operators.python import PythonOperator\nimport pipeline\n"
    )
    assert checks.scan_dag(clean) == ()
    dirty = checks.scan_dag(clean + "import csv\n")
    assert [f.check for f in dirty] == [CheckId.DAG_CONTRACT]
    assert dirty[0].evidence["forbidden_import"] == "csv"


# --------------------------------------------------------------------------- #
# Check unit tests on synthetic sandbox output                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        (["not", "a", "dict"], "not dict"),
        ({"trade_id": "T1"}, "keys differ"),
        ({**canonical_row(1), "amount": 10}, "amount is int"),
        ({**canonical_row(1), "amount": "10"}, "signed 2dp"),
        ({**canonical_row(1), "amount": "1,000.00"}, "signed 2dp"),
        ({**canonical_row(1), "value_date": "03/01/2025"}, "YYYY-MM-DD"),
        ({**canonical_row(1), "value_date": "2025-13-01"}, "YYYY-MM-DD"),
        ({**canonical_row(1), "currency": "usd"}, "ISO-4217"),
    ],
)
def test_row_violation_messages(row: Any, fragment: str) -> None:
    reason = checks.row_violation(row)

    assert reason is not None
    assert fragment in reason


def test_row_violation_accepts_clean_row() -> None:
    assert checks.row_violation(canonical_row(1, "-0.05")) is None


def test_check_schema_caps_evidence_at_three_rows() -> None:
    rows: list[Any] = [canonical_row(i, "1") for i in range(5)]

    result = checks.check_schema([make_run(rows)])

    assert not result.passed
    assert result.findings[0].evidence["violations"] == 5
    assert len(result.findings[0].evidence["offending_rows"]) == 3


def test_check_drift_null_rate_distinct_and_unparseable_amounts() -> None:
    rows: list[Any] = [canonical_row(i) for i in range(4)]
    rows[0] = {**rows[0], "amount": "abc"}
    profile = profile_for(SAMPLE).model_copy(
        update={
            "amount_sum": "40.00",
            "null_rate": {"description": 0.5},
            "distinct": {"currency": 2},
        }
    )

    result = checks.check_drift([make_run(rows, profile=profile)], tolerance=0.05)

    columns = {f.evidence.get("column") for f in result.findings}
    assert not result.passed
    assert columns == {None, "description", "currency"}
    sum_finding = next(f for f in result.findings if "expected_sum" in f.evidence)
    assert sum_finding.evidence["unparseable_amounts"] == 1


def test_check_drift_within_tolerance_passes() -> None:
    rows: list[Any] = [canonical_row(i) for i in range(4)]
    profile = profile_for(SAMPLE).model_copy(
        update={
            "amount_sum": "40.004",
            "null_rate": {"description": 0.04},
            "distinct": {"currency": 1},
        }
    )

    result = checks.check_drift([make_run(rows, profile=profile)], tolerance=0.05)

    assert result.passed
    assert result.findings == ()


def test_check_latency_warns_above_half_budget() -> None:
    result = checks.check_latency([make_run([], result=sandbox_result(wall_ms=150))], budget_ms=200)

    assert result.passed
    assert [f.severity for f in result.findings] == [Severity.WARNING]


def test_check_runtime_flags_traceback_even_with_exit_zero() -> None:
    stderr = "Traceback (most recent call last):\n  ...\nValueError: x\n"

    result = checks.check_runtime([make_run([], result=sandbox_result(stderr=stderr))], static=())

    assert not result.passed
    assert result.findings[0].evidence["reasons"] == ["traceback on stderr"]


def test_check_dag_contract_extra_edge_and_missing_output() -> None:
    dag = {
        "dag_id": "acme__ledger",
        "schedule": "0 6 * * 1-5",
        "tasks": ["extract", "transform", "load"],
        "edges": [["extract", "transform"], ["transform", "load"], ["extract", "load"]],
    }

    extra = checks.check_dag_contract([make_run([], dag=dag)], make_spec(), static=())
    missing = checks.check_dag_contract([make_run([])], make_spec(), static=())

    assert [f.evidence["field"] for f in extra.findings] == ["edges"]
    assert not missing.passed
    assert missing.findings[0].message.startswith("skipped")


def test_run_checks_with_nothing_executed_returns_six_skipped_results() -> None:
    results = checks.run_checks(
        [], make_spec(), (), (), latency_budget_ms=100, drift_tolerance=0.05
    )

    assert [r.check for r in results] == list(CheckId)
    assert all(not r.passed for r in results)
    assert all(f.severity == Severity.WARNING for r in results for f in r.findings)


# --------------------------------------------------------------------------- #
# Sandbox unit tests                                                           #
# --------------------------------------------------------------------------- #


def test_sandbox_env_is_minimal() -> None:
    env = sandbox.sandbox_env()

    assert set(env) <= {"PATH", "SYSTEMROOT", "PYTHONIOENCODING"}
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert ("SYSTEMROOT" in env) == (sys.platform == "win32")


def test_python_argv_uses_sys_executable_for_subprocess() -> None:
    assert sandbox.python_argv("subprocess") == [sys.executable, "-I", "-X", "utf8"]
    assert sandbox.python_argv("docker") == ["python", "-I", "-X", "utf8"]


def test_docker_argv_matches_lld(tmp_path: Path) -> None:
    outdir = tmp_path / "out"
    outdir.mkdir()
    argv = sandbox.docker_argv(tmp_path, outdir, ["python", "-I", "runner.py"], name="drydock-test")

    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--pids-limit") + 1] == "64"
    assert argv[argv.index("--memory") + 1] == "512m"
    assert "--read-only" in argv
    assert f"{tmp_path.resolve()}:/work:ro" in argv
    assert f"{outdir.resolve()}:/out" in argv
    assert argv[argv.index("-w") + 1] == "/work"
    assert argv[-4:] == [sandbox.DOCKER_IMAGE, "python", "-I", "runner.py"]


def test_docker_kind_without_binary_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(SandboxError, match="docker"):
        run_in_sandbox(tmp_path, ["python", "-c", "pass"], timeout_s=1, kind="docker")


def test_missing_workdir_raises(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="workdir"):
        run_in_sandbox(tmp_path / "nope", [sys.executable, "-c", "pass"], timeout_s=1)


def test_unlaunchable_command_raises(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="start"):
        run_in_sandbox(tmp_path, ["drydock-no-such-binary-xyz"], timeout_s=1)


def test_run_in_sandbox_captures_output_and_exit_code(tmp_path: Path) -> None:
    code = "import sys; print('hi'); print('err', file=sys.stderr); sys.exit(3)"

    result = run_in_sandbox(tmp_path, [sys.executable, "-c", code], timeout_s=FAST_TIMEOUT_S)

    assert result.exit_code == 3
    assert result.stdout.strip() == "hi"
    assert result.stderr.strip() == "err"
    assert not result.timed_out
    assert result.wall_ms >= 0


def test_run_in_sandbox_timeout(tmp_path: Path) -> None:
    result = run_in_sandbox(
        tmp_path, [sys.executable, "-c", "import time; time.sleep(5)"], timeout_s=0.3
    )

    assert result.timed_out
    assert result.exit_code == sandbox.TIMEOUT_EXIT_CODE


def test_docker_timeout_attempts_container_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_calls: list[list[str]] = []
    popen_commands: list[list[str]] = []

    class FakePopen:
        def __init__(self, command: list[str], **_kwargs: Any) -> None:
            popen_commands.append(list(command))
            self.pid = 4321
            self.returncode: int | None = None
            self._reaped = False

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            if not self._reaped:
                self._reaped = True
                raise subprocess.TimeoutExpired(popen_commands[-1], timeout or 1, output=b"partial")
            return b"partial", b""

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        run_calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_in_sandbox(tmp_path, ["python", "-I", "runner.py"], timeout_s=1, kind="docker")

    assert result.timed_out
    assert result.stdout == "partial"
    rm_call = next(c for c in run_calls if c[:3] == ["docker", "rm", "-f"])
    assert rm_call[3] == popen_commands[0][popen_commands[0].index("--name") + 1]


@pytest.mark.parametrize("client", corpus.list_clients())
def test_every_clean_generated_pipeline_passes_all_checks(client: str) -> None:
    spec = corpus.load_spec(client)
    plan = IngestionPlan(
        client=spec.client,
        feed_name=spec.feed_name,
        format=spec.format,
        parse_options=parse_options_from_spec(spec),
        column_map=spec.columns,
        validations=validations_from_spec(spec),
        schedule_cron=spec.schedule_cron,
    )
    # iteration=2 => the clean template with no fault injection.
    artifact = FakeProvider().generate(plan, spec, iteration=2, seed=0, previous=None, report=None)
    samples = corpus.list_samples(client)

    manifest = corpus.load_manifest(client)
    report = evaluate(artifact, spec, manifest, samples, iteration=2, timeout_s=FAST_TIMEOUT_S)

    if manifest.scenario.expected_outcome == "escalate":
        # meridian-legacy is unsatisfiable by design (the spec claims one more row than the
        # sample holds); the clean template must fail *only* completeness, never a guard or
        # runtime-jail check, which would signal the hardening broke legitimate generation.
        assert failing_checks(report) == {CheckId.COMPLETENESS}
        runtime = result_for(report, CheckId.RUNTIME)
        assert runtime.passed, [f.message for f in runtime.findings]
    else:
        assert report.passed, f"{client}: {[f.message for f in report.errors]}"
        assert all(c.passed for c in report.checks)


def test_docker_read_only_mount_blocks_writes(tmp_path: Path) -> None:
    if not docker_available():
        pytest.skip("docker binary or daemon not available")
    # Exercise the mount itself, below the guard/jail: a plain write to /work must fail
    # because the work directory is bind-mounted read-only.
    outdir = tmp_path / "out"
    outdir.mkdir()
    result = run_in_sandbox(
        tmp_path,
        ["python", "-c", "open('/work/escape.txt', 'w')"],
        timeout_s=600,
        kind="docker",
        outdir=outdir,
    )
    assert result.exit_code != 0
    # EROFS from the read-only mount, or EACCES when the kernel checks directory
    # permissions first; either way the write was refused below the guard and jail.
    denied = ("Read-only file system", "Errno 30", "Permission denied", "Errno 13")
    assert any(marker in result.stderr for marker in denied), result.stderr[-400:]
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.skipif(not docker_available(), reason="docker binary or daemon not available")
def test_docker_sandbox_runs_good_pipeline() -> None:
    report = judge(make_artifact(), sandbox="docker", timeout_s=600, latency_budget_ms=600_000)

    assert report.sandbox == "docker"
    assert report.errors == ()
    assert report.rows_emitted == EXPECTED_ROWS


# --------------------------------------------------------------------------- #
# runner.py in-process (it is stdlib only; the shim is resolved from the repo) #
# --------------------------------------------------------------------------- #


@pytest.fixture
def isolated_modules(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name in {"pipeline", "dag"} or name.startswith("airflow"):
            del sys.modules[name]


def stage(
    tmp_path: Path, *, pipeline_source: str | None = None, dag_source: str | None = None
) -> list[str]:
    (tmp_path / "pipeline.py").write_text(
        pipeline_source if pipeline_source is not None else fixture("good_pipeline.py"),
        encoding="utf-8",
    )
    (tmp_path / "dag.py").write_text(
        dag_source if dag_source is not None else fixture("good_dag.py"), encoding="utf-8"
    )
    shutil.copy(SAMPLE, tmp_path / SAMPLE.name)
    return [
        str(tmp_path / "pipeline.py"),
        str(tmp_path / SAMPLE.name),
        str(tmp_path / "dag.py"),
        str(tmp_path),
    ]


@pytest.mark.usefixtures("isolated_modules")
def test_runner_main_writes_rows_and_dag_structure(tmp_path: Path) -> None:
    rc = runner.main(stage(tmp_path))

    rows = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    dag_out = json.loads((tmp_path / "dag_out.json").read_text(encoding="utf-8"))
    assert rc == runner.EXIT_OK
    assert len(rows) == EXPECTED_ROWS
    assert dag_out["edges"] == [["extract", "transform"], ["transform", "load"]]
    assert "error" not in dag_out


def test_runner_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert runner.main(["only", "two"]) == runner.EXIT_USAGE
    assert "usage" in capsys.readouterr().err


@pytest.mark.usefixtures("isolated_modules")
def test_runner_pipeline_failure_still_records_dag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = (
        "def extract(path):\n    raise ValueError('boom')\n\n"
        "def transform(rows):\n    return rows\n\n"
        "def load(rows):\n    return 0\n"
    )

    rc = runner.main(stage(tmp_path, pipeline_source=source))

    assert rc == runner.EXIT_PIPELINE_FAILED
    assert "boom" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()
    dag_out = json.loads((tmp_path / "dag_out.json").read_text(encoding="utf-8"))
    assert dag_out["dag_id"] == "acme__ledger"


@pytest.mark.usefixtures("isolated_modules")
def test_runner_requires_extract_and_transform(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = runner.main(stage(tmp_path, pipeline_source="def transform(rows):\n    return rows\n"))

    assert rc == runner.EXIT_PIPELINE_FAILED
    assert "must define extract" in capsys.readouterr().err


@pytest.mark.usefixtures("isolated_modules")
def test_runner_failed_import_leaves_no_module_behind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = runner.main(stage(tmp_path, pipeline_source="raise ValueError('at import')\n"))

    assert rc == runner.EXIT_PIPELINE_FAILED
    assert "at import" in capsys.readouterr().err
    assert "pipeline" not in sys.modules


@pytest.mark.usefixtures("isolated_modules")
def test_runner_dag_without_dag_object_is_recorded_as_error(tmp_path: Path) -> None:
    rc = runner.main(stage(tmp_path, dag_source="x = 1\n"))

    dag_out = json.loads((tmp_path / "dag_out.json").read_text(encoding="utf-8"))
    assert rc == runner.EXIT_OK
    assert "did not instantiate" in dag_out["error"]
    assert dag_out["tasks"] == []


@pytest.mark.usefixtures("isolated_modules")
def test_shim_supports_lists_explicit_dag_and_set_methods(tmp_path: Path) -> None:
    dag_source = (
        "from airflow import DAG\n"
        "from airflow.operators.python import PythonOperator\n"
        "import pipeline\n"
        "dag = DAG('acme__ledger', schedule_interval='0 6 * * 1-5')\n"
        "a = PythonOperator(task_id='extract', python_callable=pipeline.extract, dag=dag)\n"
        "b = PythonOperator(task_id='transform', python_callable=pipeline.transform, dag=dag)\n"
        "c = PythonOperator(task_id='load', python_callable=pipeline.load, dag=dag)\n"
        "[a, b] >> c\n"
        "c << a\n"
        "a.set_downstream(b)\n"
        "b.set_upstream(a)\n"
        "[b] << a\n"
    )

    rc = runner.main(stage(tmp_path, dag_source=dag_source))

    dag_out = json.loads((tmp_path / "dag_out.json").read_text(encoding="utf-8"))
    assert rc == runner.EXIT_OK
    assert dag_out["schedule"] == "0 6 * * 1-5"
    assert dag_out["tasks"] == ["extract", "transform", "load"]
    assert dag_out["edges"] == [
        ["extract", "load"],
        ["transform", "load"],
        ["extract", "transform"],
    ]


@pytest.mark.usefixtures("isolated_modules")
def test_shim_rejects_operator_outside_dag_context(tmp_path: Path) -> None:
    dag_source = (
        "from airflow.operators.python import PythonOperator\n"
        "import pipeline\n"
        "PythonOperator(task_id='extract', python_callable=pipeline.extract)\n"
    )

    runner.main(stage(tmp_path, dag_source=dag_source))

    dag_out = json.loads((tmp_path / "dag_out.json").read_text(encoding="utf-8"))
    assert "outside a DAG context" in dag_out["error"]
