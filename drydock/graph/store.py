"""Run store: SQLite rows plus per-iteration files (docs/design/03-lld.md section 7.2).

Rows live in ``runs`` and ``iterations``; the artifact files of every iteration live under
``runs/<run_id>/iter-N/`` next to ``report.json``. ``RunRecord`` is immutable, so ``update``
returns a fresh record instead of mutating one. The connection is opened with
``check_same_thread=False`` so the dashboard's worker threads can read it; writes are
serialised by a lock. Call ``close()`` (or use the store as a context manager) so Windows
can delete the database file afterwards.
"""

from __future__ import annotations

import builtins
import difflib
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from drydock.errors import DrydockError, RunNotFound
from drydock.models import Finding, HarnessReport, PipelineArtifact, RunRecord, RunStatus, utcnow
from drydock.paths import DB_PATH, RUNS_DIR

ArtifactFile = Literal["pipeline.py", "dag.py", "mapping.yaml"]
ARTIFACT_FILES: tuple[ArtifactFile, ...] = ("pipeline.py", "dag.py", "mapping.yaml")
ARTIFACT_META = "artifact.json"
REPORT_FILE = "report.json"

_UPDATABLE = frozenset(RunRecord.model_fields) - {"run_id", "created_at"}

DDL = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        client TEXT NOT NULL,
        provider TEXT NOT NULL,
        status TEXT NOT NULL,
        iterations INT NOT NULL DEFAULT 0,
        max_iterations INT NOT NULL DEFAULT 3,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        approved_by TEXT,
        decision_note TEXT,
        final_passed INT,
        artifact_dir TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS iterations (
        run_id TEXT NOT NULL,
        iteration INT NOT NULL,
        passed INT,
        wall_ms INT NOT NULL DEFAULT 0,
        report_json TEXT,
        PRIMARY KEY (run_id, iteration)
    )
    """,
)

_RUN_COLUMNS = (
    "run_id",
    "client",
    "provider",
    "status",
    "iterations",
    "max_iterations",
    "created_at",
    "updated_at",
    "approved_by",
    "decision_note",
    "final_passed",
    "artifact_dir",
)


def artifact_files(artifact: PipelineArtifact) -> dict[ArtifactFile, str]:
    """The three deployable files of an artifact, keyed by their on-disk name."""
    return {
        "pipeline.py": artifact.pipeline_py,
        "dag.py": artifact.dag_py,
        "mapping.yaml": artifact.mapping_yaml,
    }


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with ``\\n`` newlines regardless of platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _row_to_record(row: sqlite3.Row) -> RunRecord:
    passed = row["final_passed"]
    return RunRecord(
        run_id=row["run_id"],
        client=row["client"],
        provider=row["provider"],
        status=RunStatus(row["status"]),
        iterations=row["iterations"],
        max_iterations=row["max_iterations"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        approved_by=row["approved_by"],
        decision_note=row["decision_note"],
        final_passed=None if passed is None else bool(passed),
        artifact_dir=row["artifact_dir"],
    )


def _record_to_params(record: RunRecord) -> dict[str, Any]:
    params = record.model_dump(mode="json")
    params["final_passed"] = None if record.final_passed is None else int(record.final_passed)
    return params


class RunStore:
    """SQLite-backed run ledger plus the ``runs/<run_id>/iter-N`` artifact directories."""

    def __init__(self, db_path: Path = DB_PATH, runs_dir: Path = RUNS_DIR) -> None:
        self.db_path = db_path
        self.runs_dir = runs_dir
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            for statement in DDL:
                self._conn.execute(statement)

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        """Close the connection; idempotent."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ runs

    def create(self, record: RunRecord) -> None:
        placeholders = ", ".join(f":{column}" for column in _RUN_COLUMNS)
        sql = f"INSERT INTO runs ({', '.join(_RUN_COLUMNS)}) VALUES ({placeholders})"
        try:
            with self._lock, self._conn:
                self._conn.execute(sql, _record_to_params(record))
        except sqlite3.IntegrityError as exc:
            raise DrydockError(f"run {record.run_id!r} already exists") from exc

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFound(f"no run with id {run_id!r}")
        return _row_to_record(row)

    def update(self, run_id: str, **fields: Any) -> RunRecord:
        """Apply ``fields`` to the run and return the new record (``updated_at`` refreshed)."""
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise DrydockError(f"cannot update run field(s): {sorted(unknown)}")
        current = self.get(run_id)
        updated = current.model_copy(update={**fields, "updated_at": utcnow()})
        params = _record_to_params(updated)
        assignments = ", ".join(f"{column} = :{column}" for column in _RUN_COLUMNS[1:])
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE runs SET {assignments} WHERE run_id = :run_id", params)
        return updated

    def list(self, limit: int = 50) -> builtins.list[RunRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    # ------------------------------------------------------------------ iterations

    def iteration_dir(self, run_id: str, iteration: int) -> Path:
        return self.runs_dir / run_id / f"iter-{iteration}"

    def save_iteration(
        self, run_id: str, artifact: PipelineArtifact, report: HarnessReport | None
    ) -> Path:
        """Write ``runs/<id>/iter-N/``: the three artifact files, artifact.json, report.json."""
        self.get(run_id)
        folder = self.iteration_dir(run_id, artifact.iteration)
        for name, text in artifact_files(artifact).items():
            write_text(folder / name, text)
        write_text(folder / ARTIFACT_META, artifact.model_dump_json(indent=2) + "\n")
        report_json = None if report is None else report.model_dump_json(indent=2)
        if report_json is not None:
            write_text(folder / REPORT_FILE, report_json + "\n")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO iterations"
                " (run_id, iteration, passed, wall_ms, report_json) VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    artifact.iteration,
                    None if report is None else int(report.passed),
                    0 if report is None else report.wall_ms,
                    report_json,
                ),
            )
        return folder

    def list_iterations(self, run_id: str) -> builtins.list[dict[str, Any]]:
        """``[{"iteration", "passed", "errors": [Finding dumps], "wall_ms"}]`` in order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT iteration, passed, wall_ms, report_json FROM iterations"
                " WHERE run_id = ? ORDER BY iteration",
                (run_id,),
            ).fetchall()
        return [_iteration_summary(row) for row in rows]

    def load_iteration(
        self, run_id: str, iteration: int
    ) -> tuple[PipelineArtifact, HarnessReport | None]:
        folder = self.iteration_dir(run_id, iteration)
        meta = folder / ARTIFACT_META
        if not meta.is_file():
            raise RunNotFound(f"run {run_id!r} has no iteration {iteration}")
        artifact = PipelineArtifact.model_validate_json(meta.read_text(encoding="utf-8"))
        report_path = folder / REPORT_FILE
        report = None
        if report_path.is_file():
            report = HarnessReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        return artifact, report

    def diff(self, run_id: str, iteration: int, file: ArtifactFile) -> str:
        """Unified diff of ``file`` between ``iteration - 1`` and ``iteration`` ("" for 1)."""
        if file not in ARTIFACT_FILES:
            raise DrydockError(f"unknown artifact file {file!r}")
        if iteration <= 1:
            return ""
        before, _ = self.load_iteration(run_id, iteration - 1)
        after, _ = self.load_iteration(run_id, iteration)
        lines = difflib.unified_diff(
            artifact_files(before)[file].splitlines(keepends=True),
            artifact_files(after)[file].splitlines(keepends=True),
            fromfile=f"iter-{iteration - 1}/{file}",
            tofile=f"iter-{iteration}/{file}",
        )
        return "".join(lines)


def _iteration_summary(row: sqlite3.Row) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if row["report_json"]:
        report = HarnessReport.model_validate_json(row["report_json"])
        errors = [_finding_dump(finding) for finding in report.errors]
    passed = row["passed"]
    return {
        "iteration": row["iteration"],
        "passed": None if passed is None else bool(passed),
        "errors": errors,
        "wall_ms": row["wall_ms"],
    }


def _finding_dump(finding: Finding) -> dict[str, Any]:
    return finding.model_dump(mode="json")


__all__ = [
    "ARTIFACT_FILES",
    "ArtifactFile",
    "RunStore",
    "artifact_files",
    "write_text",
]
