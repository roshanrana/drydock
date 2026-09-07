"""Manifest-like stand-in plus the spec/profile baselines for tests/fixtures/pipelines.

``drydock.corpus.Manifest`` (T-001) is not a dependency of the harness tests; anything with a
``samples`` sequence of ``SampleProfile`` satisfies ``drydock.harness.ManifestLike``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from drydock.models import ColumnSpec, FeedSpec, SampleProfile, SourceFormat

FIXTURES = Path(__file__).parent / "pipelines"
SAMPLE = FIXTURES / "acme_ledger.csv"
EXPECTED_ROWS = 6
AMOUNT_SUM = "-940.50"
NULL_RATE = {"description": 1 / 6}
DISTINCT = {"currency": 3, "counterparty": 3, "account_id": 3}


@dataclass(frozen=True)
class ManifestStub:
    """Satisfies ``ManifestLike``: a read-only ``samples`` sequence of profiles."""

    samples: tuple[SampleProfile, ...]


def make_spec() -> FeedSpec:
    return FeedSpec(
        client="acme",
        feed_name="ledger",
        format=SourceFormat.CSV,
        header_rows=1,
        trailer_rows=1,
        expected_row_count=EXPECTED_ROWS,
        columns=(
            ColumnSpec(source="TradeRef", target="trade_id"),
            ColumnSpec(source="Acct", target="account_id"),
            ColumnSpec(
                source="TradeDate", target="value_date", dtype="date", date_format="%d/%m/%Y"
            ),
            ColumnSpec(
                source="Amount",
                target="amount",
                dtype="decimal",
                sign_column="DrCr",
                negative_marker="D",
            ),
            ColumnSpec(source="DrCr", target=None),
            ColumnSpec(source="Ccy", target="currency"),
            ColumnSpec(source="Cpty", target="counterparty"),
            ColumnSpec(source="Memo", target="description"),
        ),
    )


def profile_for(path: Path) -> SampleProfile:
    data = path.read_bytes()
    return SampleProfile(
        name=path.name,
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        expected_rows=EXPECTED_ROWS,
        amount_sum=AMOUNT_SUM,
        null_rate=NULL_RATE,
        distinct=DISTINCT,
    )


def make_manifest(*paths: Path) -> ManifestStub:
    return ManifestStub(samples=tuple(profile_for(p) for p in (paths or (SAMPLE,))))
