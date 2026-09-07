"""acme-treasury daily_cash pipeline. Almost right: transform drops the final row.

The author treated the last line as a trailer even though the feed has trailer_rows: 0,
so every run emits expected_row_count - 1 rows. H3 completeness must catch this.
"""

import csv
from datetime import datetime
from decimal import Decimal

CANONICAL_COLUMNS = [
    "trade_id",
    "account_id",
    "value_date",
    "amount",
    "currency",
    "counterparty",
    "description",
]


def extract(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _amount(raw: str) -> str:
    return f"{Decimal(raw.replace(',', '').strip()):.2f}"


def _date(raw: str) -> str:
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date().isoformat()


def transform(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = [
        {
            "trade_id": row["TradeRef"].strip(),
            "account_id": row["Acct"].strip(),
            "value_date": _date(row["ValueDate"]),
            "amount": _amount(row["Amount"]),
            "currency": row["Ccy"].strip().upper(),
            "counterparty": row["Cpty"].strip(),
            "description": row["Narrative"].strip(),
        }
        for row in rows
    ]
    return out[:-1]  # "trailer" that does not exist


def load(rows: list[dict[str, str]]) -> int:
    return len(rows)
