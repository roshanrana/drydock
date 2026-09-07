"""Fails only H4: the sign of one row (T002) is flipped, so the amount total drifts.

Schema, row count, null rates, distinct counts and the DAG are all unchanged.
"""

import csv
from datetime import datetime
from decimal import Decimal

HEADER_ROWS = 1
TRAILER_ROWS = 1
TWO_PLACES = Decimal("0.01")
FLIPPED_TRADE = "T002"


def extract(path):
    with open(path, encoding="utf-8", newline="") as handle:
        records = [r for r in csv.reader(handle) if any(cell.strip() for cell in r)]
    header = records[0]
    body = records[HEADER_ROWS : len(records) - TRAILER_ROWS]
    return [dict(zip(header, record)) for record in body]


def _amount(row):
    amount = Decimal(row["Amount"].replace(",", "")).quantize(TWO_PLACES)
    signed = -amount if row["DrCr"] == "D" else amount
    return -signed if row["TradeRef"] == FLIPPED_TRADE else signed


def transform(rows):
    out = []
    for row in rows:
        out.append(
            {
                "trade_id": row["TradeRef"],
                "account_id": row["Acct"],
                "value_date": datetime.strptime(row["TradeDate"], "%d/%m/%Y").strftime("%Y-%m-%d"),
                "amount": f"{_amount(row):.2f}",
                "currency": row["Ccy"].upper(),
                "counterparty": row["Cpty"],
                "description": row["Memo"],
            }
        )
    return out


def load(rows):
    return len(rows)
