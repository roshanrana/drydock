"""Fails only H2: amounts are emitted without the mandatory two decimals ("1250" not "1250.00").

The numeric values are unchanged, so the H4 sum still matches; row count and DAG are fine.
"""

import csv
from datetime import datetime
from decimal import Decimal

HEADER_ROWS = 1
TRAILER_ROWS = 1
TWO_PLACES = Decimal("0.01")


def extract(path):
    with open(path, encoding="utf-8", newline="") as handle:
        records = [r for r in csv.reader(handle) if any(cell.strip() for cell in r)]
    header = records[0]
    body = records[HEADER_ROWS : len(records) - TRAILER_ROWS]
    return [dict(zip(header, record)) for record in body]


def _amount(row):
    amount = Decimal(row["Amount"].replace(",", "")).quantize(TWO_PLACES)
    return -amount if row["DrCr"] == "D" else amount


def _loose_amount(amount):
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def transform(rows):
    out = []
    for row in rows:
        out.append(
            {
                "trade_id": row["TradeRef"],
                "account_id": row["Acct"],
                "value_date": datetime.strptime(row["TradeDate"], "%d/%m/%Y").strftime("%Y-%m-%d"),
                "amount": _loose_amount(_amount(row)),
                "currency": row["Ccy"].upper(),
                "counterparty": row["Cpty"],
                "description": row["Memo"],
            }
        )
    return out


def load(rows):
    return len(rows)
