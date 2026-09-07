"""Frozen contracts shared by every DRYDOCK component (see docs/design/03-lld.md section 3).

Every agent, node, harness check and API endpoint speaks these types. Changing a
field here is an LLD change: update the design doc first, then every dependant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Canonical target schema                                                      #
# --------------------------------------------------------------------------- #

CANONICAL_COLUMNS: tuple[str, ...] = (
    "trade_id",
    "account_id",
    "value_date",  # ISO-8601 date, YYYY-MM-DD
    "amount",  # signed decimal string, 2 dp, "." separator, no thousands separator
    "currency",  # ISO-4217 upper-case
    "counterparty",
    "description",
)
"""Every generated pipeline must emit rows with exactly these keys, in this order."""


class Frozen(BaseModel):
    """Immutable base: contracts are values, never mutated in place."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# Client feed specification (what the Planner reads)                           #
# --------------------------------------------------------------------------- #


class SourceFormat(StrEnum):
    CSV = "csv"
    FIXED_WIDTH = "fixed_width"
    JSON_LINES = "jsonl"


class ColumnSpec(Frozen):
    """One source column and how it maps to the canonical schema."""

    source: str = Field(description="Header name, JSON key, or fixed-width slice 'start:end'.")
    target: str | None = Field(
        default=None, description="Canonical column, or None if the source column is dropped."
    )
    dtype: Literal["str", "date", "decimal", "int"] = "str"
    date_format: str | None = Field(default=None, description="strptime format when dtype=date.")
    sign_column: str | None = Field(
        default=None,
        description="If set, a DR/CR style column whose value flips the sign of a decimal field.",
    )
    negative_marker: str | None = Field(
        default=None, description="Value of sign_column that means the amount is negative."
    )
    default: str | None = None


class FeedSpec(Frozen):
    """Parsed form of the fenced yaml feed-contract block in corpus/<client>/spec.md."""

    client: str
    feed_name: str
    format: SourceFormat
    delimiter: str = ","
    encoding: str = "utf-8"
    header_rows: int = 1
    trailer_rows: int = 0
    skip_blank_lines: bool = True
    columns: tuple[ColumnSpec, ...]
    schedule_cron: str = "0 6 * * 1-5"
    expected_row_count: int | None = Field(
        default=None,
        description="Rows the sample is expected to yield after skipping header and trailer.",
    )
    quirks: tuple[str, ...] = Field(
        default=(), description="Free-text quirks from the spec prose; the LLM planner reads these."
    )


# --------------------------------------------------------------------------- #
# Planner output                                                               #
# --------------------------------------------------------------------------- #


class IngestionPlan(Frozen):
    """What the Planner decides before any code is written."""

    client: str
    feed_name: str
    format: SourceFormat
    parse_options: dict[str, Any] = Field(default_factory=dict)
    column_map: tuple[ColumnSpec, ...]
    validations: tuple[str, ...] = Field(
        default=(), description="Human-readable validation rules the pipeline must enforce."
    )
    schedule_cron: str
    task_ids: tuple[str, ...] = ("extract", "transform", "load")
    rationale: str = ""
    tool_calls: tuple[str, ...] = Field(
        default=(), description="MCP tool names the planner invoked, in order (evidence)."
    )


# --------------------------------------------------------------------------- #
# Generator output                                                             #
# --------------------------------------------------------------------------- #


class PipelineArtifact(Frozen):
    """The three files a Generator produces for one iteration."""

    pipeline_py: str = Field(
        description="Module exposing extract(path)->rows and transform(rows)->rows."
    )
    dag_py: str = Field(description="Airflow DAG using only DAG, PythonOperator and >>.")
    mapping_yaml: str = Field(description="Harbormaster-compatible field mapping document.")
    iteration: int = Field(ge=1)
    generator: str = Field(description="Provider name that produced this artifact.")
    notes: str = ""


# --------------------------------------------------------------------------- #
# Harness                                                                      #
# --------------------------------------------------------------------------- #


class CheckId(StrEnum):
    RUNTIME = "H1_runtime"
    SCHEMA = "H2_schema"
    COMPLETENESS = "H3_completeness"
    DRIFT = "H4_drift"
    LATENCY = "H5_latency"
    DAG_CONTRACT = "H6_dag_contract"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Finding(Frozen):
    check: CheckId
    severity: Severity
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class CheckResult(Frozen):
    check: CheckId
    passed: bool
    duration_ms: int = 0
    findings: tuple[Finding, ...] = ()


class HarnessReport(Frozen):
    """Verdict of one evaluator run over one PipelineArtifact."""

    iteration: int
    passed: bool
    checks: tuple[CheckResult, ...]
    rows_emitted: int = 0
    wall_ms: int = 0
    sandbox: Literal["subprocess", "docker"] = "subprocess"

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for c in self.checks for f in c.findings if f.severity == Severity.ERROR)


class SampleProfile(Frozen):
    """Baseline statistics for one sample file, pinned in corpus/<client>/manifest.json."""

    name: str
    sha256: str
    bytes: int
    expected_rows: int
    amount_sum: str = Field(
        description="Decimal string of the signed amount total after transform."
    )
    null_rate: dict[str, float] = Field(default_factory=dict)
    distinct: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Run lifecycle                                                                #
# --------------------------------------------------------------------------- #


class RunStatus(StrEnum):
    PLANNING = "planning"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    FAILED = "failed"


class RunRecord(Frozen):
    run_id: str
    client: str
    provider: str
    status: RunStatus
    iterations: int = 0
    max_iterations: int = 3
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_by: str | None = None
    decision_note: str | None = None
    final_passed: bool | None = None
    artifact_dir: str = Field(default="", description="runs/<run_id>, relative to repo root.")


class GraphState(BaseModel):
    """LangGraph state. Nodes return partial dicts; LangGraph merges them into a new state."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    client: str
    provider: str
    seed: int = 0
    max_iterations: int = 3
    iteration: int = 0
    spec: FeedSpec | None = None
    plan: IngestionPlan | None = None
    artifact: PipelineArtifact | None = None
    report: HarnessReport | None = None
    history: list[HarnessReport] = Field(default_factory=list)
    status: RunStatus = RunStatus.PLANNING
    decision: Literal["approve", "reject"] | None = None
    decision_note: str | None = None
    error: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)
