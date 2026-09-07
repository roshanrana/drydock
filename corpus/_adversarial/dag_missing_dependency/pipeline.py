"""acme-treasury daily_cash pipeline. Fully correct; the defect is in dag.py."""

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
    return [
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


def load(rows: list[dict[str, str]]) -> int:
    return len(rows)
