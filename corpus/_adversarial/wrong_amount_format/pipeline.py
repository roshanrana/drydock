"""acme-treasury daily_cash pipeline. Almost right: amounts are passed through verbatim.

Thousands separators are kept ("1,250.00"), so amount no longer matches the canonical
2 dp decimal pattern. H2 schema must catch this.
"""

import csv
from datetime import datetime

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


def _date(raw: str) -> str:
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date().isoformat()


def transform(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "trade_id": row["TradeRef"].strip(),
            "account_id": row["Acct"].strip(),
            "value_date": _date(row["ValueDate"]),
            "amount": row["Amount"].strip(),  # thousands separators kept
            "currency": row["Ccy"].strip().upper(),
            "counterparty": row["Cpty"].strip(),
            "description": row["Narrative"].strip(),
        }
        for row in rows
    ]


def load(rows: list[dict[str, str]]) -> int:
    return len(rows)
