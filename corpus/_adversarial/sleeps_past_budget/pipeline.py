"""acme-treasury daily_cash pipeline. Almost right: correct output, forbidden behaviour.

Nothing forbidden is imported and the output is correct, but extract sleeps for six
seconds per file, past the H5 latency budget. The harness must reject it on wall time.
"""

import csv
import time
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

SLEEP_SECONDS = 6



def extract(path: str) -> list[dict[str, str]]:
    time.sleep(SLEEP_SECONDS)
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
