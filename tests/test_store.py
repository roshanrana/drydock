"""RunStore: SQLite rows, iteration files and diffs (LLD section 7.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.errors import DrydockError, RunNotFound
from drydock.graph.store import ARTIFACT_FILES, RunStore, artifact_files, write_text
from drydock.models import (
    CheckId,
    CheckResult,
    Finding,
    HarnessReport,
    PipelineArtifact,
    RunRecord,
    RunStatus,
    Severity,
    utcnow,
)

RUN_ID = "acme-treasury-00000000000000-abcdef"


def make_record(run_id: str = RUN_ID, **overrides: object) -> RunRecord:
    base: dict[str, object] = {
        "run_id": run_id,
        "client": "acme-treasury",
        "provider": "fake",
        "status": RunStatus.PLANNING,
        "artifact_dir": f"runs/{run_id}",
    }
    return RunRecord.model_validate({**base, **overrides})


def make_artifact(iteration: int, body: str = "return rows") -> PipelineArtifact:
    return PipelineArtifact(
        pipeline_py=f"def extract(path):\n    {body}\n",
        dag_py="from airflow import DAG\n",
        mapping_yaml=f"iteration: {iteration}\n",
        iteration=iteration,
        generator="fake",
        notes=f"iteration {iteration}",
    )


def make_report(iteration: int, *, passed: bool) -> HarnessReport:
    findings: tuple[Finding, ...] = ()
    if not passed:
        findings = (
            Finding(check=CheckId.RUNTIME, severity=Severity.ERROR, message="boom"),
            Finding(check=CheckId.RUNTIME, severity=Severity.WARNING, message="meh"),
        )
    checks = tuple(
        CheckResult(
            check=check,
            passed=passed or check != CheckId.RUNTIME,
            findings=findings if check == CheckId.RUNTIME else (),
        )
        for check in CheckId
    )
    return HarnessReport(iteration=iteration, passed=passed, checks=checks, wall_ms=42)


# --------------------------------------------------------------------------- #
# Runs                                                                         #
# --------------------------------------------------------------------------- #


def test_create_then_get_round_trips_every_field(store: RunStore) -> None:
    record = make_record(approved_by="ana", decision_note="fine", final_passed=True)
    store.create(record)
    loaded = store.get(RUN_ID)
    assert loaded == record


def test_get_unknown_run_raises_run_not_found(store: RunStore) -> None:
    with pytest.raises(RunNotFound, match="nope"):
        store.get("nope")


def test_create_duplicate_run_raises_drydock_error(store: RunStore) -> None:
    store.create(make_record())
    with pytest.raises(DrydockError, match="already exists"):
        store.create(make_record())


def test_update_returns_new_record_and_leaves_input_untouched(store: RunStore) -> None:
    original = make_record()
    store.create(original)
    updated = store.update(RUN_ID, status=RunStatus.APPROVED, iterations=2, final_passed=True)
    assert updated is not original
    assert original.status is RunStatus.PLANNING
    assert updated.status is RunStatus.APPROVED
    assert updated.iterations == 2
    assert updated.final_passed is True
    assert updated.updated_at >= original.updated_at
    assert store.get(RUN_ID) == updated


def test_update_rejects_unknown_or_immutable_fields(store: RunStore) -> None:
    store.create(make_record())
    with pytest.raises(DrydockError, match="bogus"):
        store.update(RUN_ID, bogus=1)
    with pytest.raises(DrydockError, match="created_at"):
        store.update(RUN_ID, created_at=utcnow())


def test_update_unknown_run_raises_run_not_found(store: RunStore) -> None:
    with pytest.raises(RunNotFound):
        store.update("missing", status=RunStatus.FAILED)


def test_list_is_newest_first_and_honours_limit(store: RunStore) -> None:
    for index in range(3):
        store.create(make_record(f"run-{index}"))
    listed = store.list()
    assert [r.run_id for r in listed] == ["run-2", "run-1", "run-0"]
    assert [r.run_id for r in store.list(limit=2)] == ["run-2", "run-1"]


def test_close_is_idempotent_and_context_manager_closes(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "db.sqlite", tmp_path / "runs")
    store.close()
    store.close()
    with RunStore(tmp_path / "db2.sqlite", tmp_path / "runs") as other:
        other.create(make_record())
    with pytest.raises(Exception, match="closed"):
        other.get(RUN_ID)


# --------------------------------------------------------------------------- #
# Iterations                                                                   #
# --------------------------------------------------------------------------- #


def test_save_iteration_writes_files_and_row(store: RunStore, runs_dir: Path) -> None:
    store.create(make_record())
    folder = store.save_iteration(RUN_ID, make_artifact(1), make_report(1, passed=False))

    assert folder == runs_dir / RUN_ID / "iter-1"
    assert sorted(p.name for p in folder.iterdir()) == [
        "artifact.json",
        "dag.py",
        "mapping.yaml",
        "pipeline.py",
        "report.json",
    ]
    assert (folder / "pipeline.py").read_bytes().count(b"\r\n") == 0
    summaries = store.list_iterations(RUN_ID)
    assert len(summaries) == 1
    assert summaries[0]["iteration"] == 1
    assert summaries[0]["passed"] is False
    assert summaries[0]["wall_ms"] == 42
    assert [e["message"] for e in summaries[0]["errors"]] == ["boom"]


def test_save_iteration_without_report_records_unknown_verdict(store: RunStore) -> None:
    store.create(make_record())
    folder = store.save_iteration(RUN_ID, make_artifact(1), None)
    assert not (folder / "report.json").exists()
    artifact, report = store.load_iteration(RUN_ID, 1)
    assert artifact == make_artifact(1)
    assert report is None
    assert store.list_iterations(RUN_ID) == [
        {"iteration": 1, "passed": None, "errors": [], "wall_ms": 0}
    ]


def test_save_iteration_for_unknown_run_raises(store: RunStore) -> None:
    with pytest.raises(RunNotFound):
        store.save_iteration("ghost", make_artifact(1), None)


def test_load_iteration_round_trips_artifact_and_report(store: RunStore) -> None:
    store.create(make_record())
    report = make_report(2, passed=True)
    store.save_iteration(RUN_ID, make_artifact(2), report)
    artifact, loaded = store.load_iteration(RUN_ID, 2)
    assert artifact == make_artifact(2)
    assert loaded == report


def test_load_iteration_missing_raises_run_not_found(store: RunStore) -> None:
    store.create(make_record())
    with pytest.raises(RunNotFound, match="iteration 7"):
        store.load_iteration(RUN_ID, 7)


def test_save_iteration_twice_replaces_the_row(store: RunStore) -> None:
    store.create(make_record())
    store.save_iteration(RUN_ID, make_artifact(1), make_report(1, passed=False))
    store.save_iteration(RUN_ID, make_artifact(1), make_report(1, passed=True))
    assert [s["passed"] for s in store.list_iterations(RUN_ID)] == [True]


# --------------------------------------------------------------------------- #
# Diff                                                                         #
# --------------------------------------------------------------------------- #


def test_diff_is_empty_for_first_iteration(store: RunStore) -> None:
    store.create(make_record())
    store.save_iteration(RUN_ID, make_artifact(1), None)
    assert store.diff(RUN_ID, 1, "pipeline.py") == ""


def test_diff_is_unified_diff_between_consecutive_iterations(store: RunStore) -> None:
    store.create(make_record())
    store.save_iteration(RUN_ID, make_artifact(1, "return list(rows)"), None)
    store.save_iteration(RUN_ID, make_artifact(2, "return [r for r in rows]"), None)
    diff = store.diff(RUN_ID, 2, "pipeline.py")
    assert diff.startswith("--- iter-1/pipeline.py\n+++ iter-2/pipeline.py\n")
    assert "-    return list(rows)" in diff
    assert "+    return [r for r in rows]" in diff
    assert "iteration: 1" in store.diff(RUN_ID, 2, "mapping.yaml")
    assert store.diff(RUN_ID, 2, "dag.py") == ""


def test_diff_rejects_unknown_file(store: RunStore) -> None:
    store.create(make_record())
    with pytest.raises(DrydockError, match="unknown artifact file"):
        store.diff(RUN_ID, 2, "secrets.txt")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def test_artifact_files_covers_the_three_deployables() -> None:
    files = artifact_files(make_artifact(1))
    assert tuple(files) == ARTIFACT_FILES


def test_write_text_uses_lf_and_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    write_text(target, "one\ntwo\n")
    assert target.read_bytes() == b"one\ntwo\n"
