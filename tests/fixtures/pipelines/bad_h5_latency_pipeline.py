"""Fails only H5: correct output, but transform() sleeps past the latency budget.

The test evaluates it with latency_budget_ms=200 (the LLD example is sleep(6) vs 5000 ms).
"""

import csv
import time
from datetime import datetime
from decimal import Decimal

HEADER_ROWS = 1
TRAILER_ROWS = 1
TWO_PLACES = Decimal("0.01")
SLEEP_S = 0.3


def extract(path):
    with open(path, encoding="utf-8", newline="") as handle:
        records = [r for r in csv.reader(handle) if any(cell.strip() for cell in r)]
    header = records[0]
    body = records[HEADER_ROWS : len(records) - TRAILER_ROWS]
    return [dict(zip(header, record)) for record in body]


def _amount(row):
    amount = Decimal(row["Amount"].replace(",", "")).quantize(TWO_PLACES)
    return -amount if row["DrCr"] == "D" else amount


def transform(rows):
    time.sleep(SLEEP_S)
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
