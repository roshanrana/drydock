"""Contract sanity: the frozen models behave as values."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from drydock.models import (
    CANONICAL_COLUMNS,
    CheckId,
    CheckResult,
    ColumnSpec,
    FeedSpec,
    Finding,
    HarnessReport,
    Severity,
    SourceFormat,
)


def test_canonical_columns_are_fixed() -> None:
    assert CANONICAL_COLUMNS[0] == "trade_id"
    assert len(CANONICAL_COLUMNS) == 7


def test_feed_spec_is_frozen_and_strict() -> None:
    spec = FeedSpec(
        client="acme",
        feed_name="cash",
        format=SourceFormat.CSV,
        columns=(ColumnSpec(source="A", target="trade_id"),),
    )
    with pytest.raises(ValidationError):
        spec.client = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        FeedSpec(
            client="x",
            feed_name="y",
            format=SourceFormat.CSV,
            columns=(),
            unknown="field",  # type: ignore[call-arg]
        )


def test_harness_report_errors_filters_warnings() -> None:
    report = HarnessReport(
        iteration=1,
        passed=False,
        checks=(
            CheckResult(
                check=CheckId.LATENCY,
                passed=True,
                findings=(
                    Finding(check=CheckId.LATENCY, severity=Severity.WARNING, message="slow"),
                ),
            ),
            CheckResult(
                check=CheckId.SCHEMA,
                passed=False,
                findings=(Finding(check=CheckId.SCHEMA, severity=Severity.ERROR, message="bad"),),
            ),
        ),
    )
    assert [f.check for f in report.errors] == [CheckId.SCHEMA]
