"""acme-treasury daily_cash pipeline. Almost right: correct output, forbidden behaviour.

The module imports socket (network access is banned in the sandbox). The static guard
must reject the import before a single line executes, which is why the sleep below can
never be observed: H1 runtime is the only finding this case can produce.
"""

import csv
import socket
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


def _warm_up() -> None:
    # "Reachability check" against the client's SFTP host. Never allowed in the sandbox.
    try:
        socket.getaddrinfo("sftp.acme-treasury.example", 22)
    except OSError:
        pass


def extract(path: str) -> list[dict[str, str]]:
    _warm_up()
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
